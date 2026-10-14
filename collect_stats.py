import json
import subprocess
import threading
import time
from pathlib import Path


class Collector:
    def __init__(self, output):
        self.output = Path(output)
        self.stop_event = threading.Event()
        self.thread = None
        self.error = None

    def start(self):
        self.thread = threading.Thread(
            target=self.collect,
            daemon=True,
        )
        self.thread.start()

    def collect(self):
        start = time.monotonic()

        try:
            with (self.output / "qdisc.jsonl").open("w") as log:
                while not self.stop_event.is_set():
                    for router in ["mq-r1", "mq-r2"]:
                        result = subprocess.run(
                            [
                                "ip", "netns", "exec", router,
                                "tc", "-s", "-j",
                                "qdisc", "show", "dev", "wan",
                            ],
                            capture_output=True,
                            text=True,
                            check=True,
                        )

                        record = {
                            "time_s": time.monotonic() - start,
                            "namespace": router,
                            "qdiscs": json.loads(result.stdout),
                        }

                        log.write(json.dumps(record) + "\n")

                    log.flush()
                    self.stop_event.wait(0.2)

        except Exception as error:
            self.error = str(error)

    def stop(self):
        self.stop_event.set()

        if self.thread:
            self.thread.join(timeout=5)
