import os
import signal
import subprocess
import time
from pathlib import Path

from common import ROOT


class Traffic:
    def __init__(self, output):
        self.output = Path(output)
        self.processes = []
        self.logs = []
        self.clients = []
        self.servers = []

    def launch(self, namespace, arguments, log_name):
        log = (self.output / log_name).open("w")
        self.logs.append(log)

        process = subprocess.Popen(
            [
                "ip", "netns", "exec", namespace,
                *map(str, arguments),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        self.processes.append(process)
        return process

    def start_servers(self):
        for i in [1, 2]:
            process = self.launch(
                f"mq-d{i}",
                [
                    ROOT / "msquic_traffic",
                    "server", "4433",
                    ROOT / "cert.pem",
                    ROOT / "key.pem",
                ],
                f"server{i}.log",
            )

            self.servers.append(process)

        deadline = time.monotonic() + 10

        while time.monotonic() < deadline:
            if any(p.poll() is not None for p in self.servers):
                raise RuntimeError(
                    "Receiver exited. Inspect server1.log/server2.log."
                )

            ready = all(
                "READY" in
                (self.output / f"server{i}.log").read_text()
                for i in [1, 2]
            )

            if ready:
                return

            time.sleep(0.1)

        raise RuntimeError("Receivers did not become ready.")

    def start_clients(self, duration, ecn):
        for i in [1, 2]:
            process = self.launch(
                f"mq-s{i}",
                [
                    ROOT / "msquic_traffic",
                    "client",
                    f"10.10.{i + 3}.2",
                    "4433",
                    duration,
                    int(ecn),
                    self.output / f"flow{i}.csv",
                ],
                f"client{i}.log",
            )

            self.clients.append(process)

    def wait(self, duration):
        deadline = time.monotonic() + duration + 30

        while any(p.poll() is None for p in self.clients):
            if time.monotonic() > deadline:
                raise RuntimeError("Traffic timed out.")

            if any(p.poll() is not None for p in self.servers):
                raise RuntimeError("Receiver exited during traffic.")

            time.sleep(0.1)

        if any(p.returncode != 0 for p in self.clients):
            raise RuntimeError(
                "MsQuic client failed. Inspect client1.log/client2.log."
            )

    def stop(self):
        for process in self.processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

        for process in self.processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

        for log in self.logs:
            log.close()
