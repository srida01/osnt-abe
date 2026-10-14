import argparse
import fcntl
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from common import ROOT, require_root, run
from topology import create
from configure_queue import configure
from build_msquic_app import build
from generate_traffic import Traffic
from collect_stats import Collector
from plot_results import plot
from cleanup import cleanup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--msquic", required=True, type=Path)
    parser.add_argument("--library", type=Path)
    parser.add_argument("--ecn", choices=["on", "off"], default="on")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--keep-topology", action="store_true")
    args = parser.parse_args()

    require_root()

    if args.duration < 10:
        raise RuntimeError("Use a duration of at least 10 seconds.")

    for executable in [
        "ip", "tc", "ethtool", "cc",
        "openssl", "tcpdump", "ldd", "ping", "git",
    ]:
        if not shutil.which(executable):
            raise RuntimeError(f"Missing command: {executable}")

    # Prevent concurrent experiments using the same namespace names.
    lock = open("/run/lock/msquic-lab.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def interrupted(*unused):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output = ROOT / "results" / f"{timestamp}-ecn-{args.ecn}"
    output.mkdir(parents=True, exist_ok=False)

    traffic = Traffic(output)
    collector = Collector(output)

    capture = None
    capture_log = None
    created = False
    success = False

    print(f"Output folder: {output}", flush=True)

    try:
        library = build(args.msquic, args.library)

        if (
            not (ROOT / "cert.pem").exists() or
            not (ROOT / "key.pem").exists()
        ):
            run([
                "openssl", "req",
                "-x509",
                "-newkey", "rsa:2048",
                "-nodes",
                "-keyout", ROOT / "key.pem",
                "-out", ROOT / "cert.pem",
                "-days", "30",
                "-subj", "/CN=msquic-lab",
            ], stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL)

            (ROOT / "key.pem").chmod(0o600)

        commit = run(
            ["git", "-C", args.msquic, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        ).stdout.strip()

        configuration = {
            "ecn": args.ecn,
            "abe": False,
            "duration_s": args.duration,
            "msquic_commit": commit,
            "library": library,
            "access": "100 Mbps / 1 ms each direction",
            "bottleneck": "10 Mbps / 20 ms each direction",
            "aqm": "fq_codel",
            "target_ms": 5,
            "interval_ms": 100,
            "cwnd_sampling_ms": 20,
            "kernel": os.uname().release,
        }

        (output / "config.json").write_text(
            json.dumps(configuration, indent=2)
        )

        create()
        created = True

        configure(args.ecn == "on")
        traffic.start_servers()

        capture_log = (output / "capture.log").open("w")

        # Router 2 ingress sees the forward packets after router 1 AQM.
        capture = subprocess.Popen(
            [
                "ip", "netns", "exec", "mq-r2",
                "tcpdump",
                "-U",
                "-i", "wan",
                "-s", "128",
                "-w", str(output / "bottleneck.pcap"),
                "udp", "port", "4433",
            ],
            stdout=capture_log,
            stderr=capture_log,
        )

        deadline = time.monotonic() + 5

        while time.monotonic() < deadline:
            if capture.poll() is not None:
                raise RuntimeError(
                    "Packet capture failed. Inspect capture.log."
                )

            if "listening on" in (
                output / "capture.log"
            ).read_text():
                break

            time.sleep(0.1)
        else:
            raise RuntimeError("Packet capture did not become ready.")

        collector.start()

        print(
            f"Running two CUBIC flows: ECN {args.ecn}, "
            f"{args.duration} seconds...",
            flush=True,
        )

        traffic.start_clients(
            args.duration,
            args.ecn == "on",
        )
        traffic.wait(args.duration)

        collector.stop()

        if collector.error:
            raise RuntimeError(
                f"Queue statistics collection failed: {collector.error}"
            )

        summary = plot(output, args.ecn == "on")
        success = True

        print(json.dumps(summary, indent=2))
        print(f"\nGraph: {output / 'cwnd_rtt.png'}", flush=True)

    finally:
        collector.stop()
        traffic.stop()

        if capture and capture.poll() is None:
            capture.send_signal(signal.SIGINT)

            try:
                capture.wait(timeout=5)
            except subprocess.TimeoutExpired:
                capture.kill()
                capture.wait()

        if capture_log:
            capture_log.close()

        if created and not (
            args.keep_topology and success
        ):
            cleanup()

        # Make output accessible to the user who invoked sudo.
        if os.environ.get("SUDO_UID"):
            uid = int(os.environ["SUDO_UID"])
            gid = int(os.environ["SUDO_GID"])

            for path in [output, *output.rglob("*")]:
                os.chown(path, uid, gid)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("Interrupted; experiment resources cleaned up.")
    except Exception as error:
        raise SystemExit(f"FAILED: {error}")
