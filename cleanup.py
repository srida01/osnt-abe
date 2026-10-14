import os
import subprocess
import time

from common import NAMES, require_root


def cleanup():
    require_root()

    for signal_number in [15, 9]:
        for namespace in NAMES:
            result = subprocess.run(
                ["ip", "netns", "pids", namespace],
                capture_output=True,
                text=True,
            )

            for pid in result.stdout.split():
                try:
                    os.kill(int(pid), signal_number)
                except ProcessLookupError:
                    pass

        if signal_number == 15:
            time.sleep(0.3)

    for namespace in NAMES:
        subprocess.run(
            ["ip", "netns", "del", namespace],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    cleanup()
