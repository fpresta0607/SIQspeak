import logging

import sounddevice as sd

log = logging.getLogger("siqspeak")


def _get_input_devices() -> list[dict]:
    """Return list of input-capable audio devices."""
    devices = sd.query_devices()
    result = []
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0:
            result.append({"index": i, "name": d["name"]})
    return result
