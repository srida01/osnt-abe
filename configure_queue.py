import argparse

from common import ns, require_root


def configure(ecn):
    require_root()

    for router in ["mq-r1", "mq-r2"]:
        ns(router, [
            "tc", "qdisc", "add",
            "dev", "wan",
            "root", "handle", "1:",
            "htb", "default", "10",
        ])

        ns(router, [
            "tc", "class", "add",
            "dev", "wan",
            "parent", "1:",
            "classid", "1:10",
            "htb",
            "rate", "50mbit",
            "ceil", "50mbit",
            "burst", "60k",
        ])

        ns(router, [
            "tc", "qdisc", "add",
            "dev", "wan",
            "parent", "1:10",
            "handle", "10:",
            "netem",
            "delay", "10ms",
            "limit", "1000",
        ])

        ns(router, [
            "tc", "qdisc", "add",
            "dev", "wan",
            "parent", "10:1",
            "handle", "20:",
            "fq_codel",
            "limit", "1000",
            "target", "5ms",
            "interval", "100ms",
            "ecn" if ecn else "noecn",
        ])

    print(
        f"Bottleneck configured: ECN {'on' if ecn else 'off'}.",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ecn", choices=["on", "off"], default="on")
    args = parser.parse_args()
    configure(args.ecn == "on")
