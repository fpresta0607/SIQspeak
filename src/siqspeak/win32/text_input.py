import ctypes
import logging
import time

from siqspeak.win32.structs import (
    INPUT,
    INPUT_KEYBOARD,
    KEYEVENTF_KEYUP,
    KEYEVENTF_UNICODE,
    VK_CONTROL,
    VK_RETURN,
    VK_SHIFT,
)

log = logging.getLogger("siqspeak")


def _build_inputs(text: str) -> "ctypes.Array":
    """Build the SendInput array: one key down + up pair per character.

    Newlines are sent as a real Enter (``VK_RETURN``) keypress, not a Unicode
    ``\\n`` scan code — Windows does not interpret a Unicode line feed as a line
    break, so typing it verbatim collapses multi-line output (email drafts, the
    Code-mode brief) onto a single run-on line. Every other character is a
    Unicode event, so any glyph types without a per-key virtual-key mapping.
    """
    n = len(text) * 2
    inputs = (INPUT * n)()
    for i, char in enumerate(text):
        down = inputs[i * 2]
        up = inputs[i * 2 + 1]
        down.type = INPUT_KEYBOARD
        up.type = INPUT_KEYBOARD
        if char == "\n":
            down.ki.wVk = VK_RETURN
            down.ki.dwFlags = 0
            up.ki.wVk = VK_RETURN
            up.ki.dwFlags = KEYEVENTF_KEYUP
        else:
            code = ord(char)
            down.ki.wScan = code
            down.ki.dwFlags = KEYEVENTF_UNICODE
            up.ki.wScan = code
            up.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    return inputs


def type_text(text: str, release_modifiers: bool = True) -> None:
    """Type text into the focused window using keyboard events."""
    user32 = ctypes.windll.user32

    if release_modifiers:
        # Release Ctrl and Shift before injecting text so they don't
        # interfere with the typed characters.
        release = (INPUT * 2)()
        release[0].type = INPUT_KEYBOARD
        release[0].ki.wVk = VK_CONTROL
        release[0].ki.dwFlags = KEYEVENTF_KEYUP
        release[1].type = INPUT_KEYBOARD
        release[1].ki.wVk = VK_SHIFT
        release[1].ki.dwFlags = KEYEVENTF_KEYUP
        user32.SendInput(2, ctypes.pointer(release[0]), ctypes.sizeof(INPUT))
        time.sleep(0.05)

    if not text:
        return
    inputs = _build_inputs(text)
    user32.SendInput(len(inputs), ctypes.pointer(inputs[0]), ctypes.sizeof(INPUT))


def focus_window(hwnd: int) -> None:
    """Bring a window to the foreground reliably."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return
    # Alt key trick: grants foreground rights to the calling process
    user32.keybd_event(0x12, 0, 0, 0)         # Alt down
    user32.keybd_event(0x12, 0, 0x0002, 0)    # Alt up
    # AttachThreadInput for cross-thread focus
    our_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    attached = False
    if our_tid != fg_tid:
        user32.AttachThreadInput(our_tid, fg_tid, True)
        attached = True
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    if attached:
        user32.AttachThreadInput(our_tid, fg_tid, False)
