import logging

import sounddevice as sd

log = logging.getLogger("siqspeak")

# Non-mic input device name fragments to exclude
_EXCLUDE = {"stereo mix", "what u hear", "loopback", "wave out"}


def _get_input_devices() -> list[dict]:
    """Return list of microphone-type input devices (WASAPI only, no loopback)."""
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()

    # Find WASAPI host API index
    wasapi_idx = None
    for i, api in enumerate(hostapis):
        if "WASAPI" in api["name"]:
            wasapi_idx = i
            break

    result = []
    for i, d in enumerate(devices):
        if d["max_input_channels"] <= 0:
            continue
        # Filter to WASAPI if available
        if wasapi_idx is not None and d["hostapi"] != wasapi_idx:
            continue
        # Exclude non-mic inputs
        name_lower = d["name"].lower()
        if any(ex in name_lower for ex in _EXCLUDE):
            continue
        result.append({"index": i, "name": d["name"]})
    return result
