import logging
import os
import sys


def configure_logging(log_dir: str) -> logging.Logger:
    if sys.executable and sys.executable.endswith("pythonw.exe"):
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(os.path.join(log_dir, "dictate.log"), encoding="utf-8"),
        ],
    )
    return logging.getLogger("siqspeak")
