import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot(output, ecn):
    output = Path(output)
    summary = {}
    exercised = True

    figure, axes = plt.subplots(
        2, 1,
        figsize=(11, 7),
        sharex=True,
    )

    for i in [1, 2]:
        with (output / f"flow{i}.csv").open() as file:
            rows = list(csv.DictReader(file))

        if len(rows) < 10:
            raise RuntimeError(
                f"Flow {i}: insufficient cwnd samples."
            )

        times = [float(row["time_s"]) for row in rows]
        cwnd = [int(row["cwnd_bytes"]) for row in rows]
        rtt = [int(row["rtt_us"]) / 1000 for row in rows]

        if max(cwnd) <= 0:
            raise RuntimeError(f"Flow {i}: no positive cwnd.")

        elapsed = times[-1] - times[0]
        if elapsed <= 0:
            raise RuntimeError(f"Flow {i}: invalid sample timestamps.")

        axes[0].plot(
            times,
            [value / 1024 for value in cwnd],
            label=f"Flow {i}",
        )
        axes[1].plot(times, rtt, label=f"Flow {i}")

        events = max(
            int(row["ecn_congestion_events"])
            for row in rows
        )

        capable = any(
            int(row["ecn_capable"])
            for row in rows
        )

        sent_bytes = (
            int(rows[-1]["sent_bytes"]) -
            int(rows[0]["sent_bytes"])
        )

        summary[f"flow{i}"] = {
            "samples": len(rows),
            "ecn_capable_observed": capable,
            "ecn_congestion_events": events,
            "suspected_lost_packets":
                int(rows[-1]["lost_packets"]),
            "average_udp_payload_mbps":
                sent_bytes * 8 / elapsed / 1e6,
        }

        exercised = exercised and capable and events > 0

    axes[0].set_ylabel("Congestion window (KiB)")
    axes[1].set_ylabel("RTT (ms)")
    axes[1].set_xlabel(
        "Time since each connection established (s)"
    )

    axes[0].set_title(
        f"MsQuic CUBIC — ECN {'on' if ecn else 'off'}"
        " — ABE not implemented"
    )

    for axis in axes:
        axis.legend()
        axis.grid(alpha=0.25)

    figure.tight_layout()
    figure.savefig(output / "cwnd_rtt.png", dpi=180)
    plt.close(figure)

    summary["ecn_requested"] = ecn
    summary["ecn_exercised_both_flows"] = (
        bool(exercised) if ecn else None
    )

    (output / "summary.json").write_text(
        json.dumps(summary, indent=2)
    )

    if ecn and not exercised:
        raise RuntimeError(
            "Graph saved, but ECN was not exercised on both flows. "
            "Inspect summary.json, qdisc.jsonl and bottleneck.pcap."
        )

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--ecn", choices=["on", "off"], default="on")
    args = parser.parse_args()

    plot(args.output, args.ecn == "on")
