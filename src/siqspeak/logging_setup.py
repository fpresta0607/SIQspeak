import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def configure_logging(log_dir: str) -> logging.Logger:
    if sys.executable and sys.executable.endswith("pythonw.exe"):
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115

    handler = RotatingFileHandler(
        os.path.join(log_dir, "dictate.log"),
        maxBytes=5 * 1024 * 1024,  # 5 MB per file
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d %(message)s", datefmt="%H:%M:%S",
    ))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return logging.getLogger("siqspeak")
