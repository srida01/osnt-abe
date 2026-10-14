import json
import subprocess

from common import NAMES, ns, require_root, run


def create():
    require_root()

    existing = {
        item["name"]
        for item in json.loads(
            run(
                ["ip", "-j", "netns", "list"],
                capture_output=True,
                text=True,
            ).stdout
        )
    }

    collisions = existing.intersection(NAMES)
    if collisions:
        raise RuntimeError(
            f"Existing lab namespaces: {sorted(collisions)}. "
            "Run cleanup.py before starting another experiment."
        )

    made = []

    try:
        for name in NAMES:
            run(["ip", "netns", "add", name])
            made.append(name)
            ns(name, ["ip", "link", "set", "lo", "up"])

        def connect(a, interface_a, address_a,
                    b, interface_b, address_b):
            run([
                "ip", "link", "add", "mqlab-a",
                "type", "veth",
                "peer", "name", "mqlab-b",
            ])

            run(["ip", "link", "set", "mqlab-a", "netns", a])
            run(["ip", "link", "set", "mqlab-b", "netns", b])

            endpoints = [
                (a, "mqlab-a", interface_a, address_a),
                (b, "mqlab-b", interface_b, address_b),
            ]

            for name, temporary, interface, address in endpoints:
                ns(name, [
                    "ip", "link", "set",
                    temporary, "name", interface,
                ])
                ns(name, [
                    "ip", "addr", "add",
                    address, "dev", interface,
                ])
                ns(name, [
                    "ip", "link", "set", interface, "up",
                ])
                ns(name, [
                    "ethtool", "-K", interface,
                    "gro", "off",
                    "gso", "off",
                    "tso", "off",
                ], stdout=subprocess.DEVNULL)

        connect(
            "mq-s1", "eth0", "10.10.1.2/24",
            "mq-r1", "s1", "10.10.1.1/24",
        )
        connect(
            "mq-s2", "eth0", "10.10.2.2/24",
            "mq-r1", "s2", "10.10.2.1/24",
        )
        connect(
            "mq-r1", "wan", "10.10.3.1/24",
            "mq-r2", "wan", "10.10.3.2/24",
        )
        connect(
            "mq-r2", "d1", "10.10.4.1/24",
            "mq-d1", "eth0", "10.10.4.2/24",
        )
        connect(
            "mq-r2", "d2", "10.10.5.1/24",
            "mq-d2", "eth0", "10.10.5.2/24",
        )

        gateways = [
            ("mq-s1", "10.10.1.1"),
            ("mq-s2", "10.10.2.1"),
            ("mq-d1", "10.10.4.1"),
            ("mq-d2", "10.10.5.1"),
        ]

        for name, gateway in gateways:
            ns(name, [
                "ip", "route", "add",
                "default", "via", gateway,
            ])

        for router in ["mq-r1", "mq-r2"]:
            ns(router, [
                "sysctl", "-qw", "net.ipv4.ip_forward=1",
            ])

        for subnet in [4, 5]:
            ns("mq-r1", [
                "ip", "route", "add",
                f"10.10.{subnet}.0/24",
                "via", "10.10.3.2",
            ])

        for subnet in [1, 2]:
            ns("mq-r2", [
                "ip", "route", "add",
                f"10.10.{subnet}.0/24",
                "via", "10.10.3.1",
            ])

        access_interfaces = {
            "mq-s1": ["eth0"],
            "mq-s2": ["eth0"],
            "mq-d1": ["eth0"],
            "mq-d2": ["eth0"],
            "mq-r1": ["s1", "s2"],
            "mq-r2": ["d1", "d2"],
        }

        for name, interfaces in access_interfaces.items():
            for interface in interfaces:
                ns(name, [
                    "tc", "qdisc", "add",
                    "dev", interface,
                    "root", "netem",
                    "delay", "1ms",
                    "rate", "100mbit",
                    "limit", "1000",
                ])

        for source, destination in [
            ("mq-s1", "10.10.4.2"),
            ("mq-s2", "10.10.5.2"),
        ]:
            ns(source, [
                "ping", "-c", "1", "-W", "2", destination,
            ], stdout=subprocess.DEVNULL)

        print("Topology created; both routes passed ping.", flush=True)

    except BaseException:
        for name in reversed(made):
            subprocess.run(["ip", "netns", "del", name])
        raise


if __name__ == "__main__":
    create()
