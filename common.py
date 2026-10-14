from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parent

NAMES = [
    "mq-s1", "mq-s2",
    "mq-r1", "mq-r2",
    "mq-d1", "mq-d2",
]


def run(args, **kwargs):
    return subprocess.run(
        [str(x) for x in args],
        check=True,
        **kwargs,
    )


def ns(name, args, **kwargs):
    return run(
        ["ip", "netns", "exec", name, *args],
        **kwargs,
    )


def require_root():
    if os.geteuid() != 0:
        raise SystemExit("Run this command with sudo.")
