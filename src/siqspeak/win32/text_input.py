import ctypes
import logging
import time

from siqspeak.win32.structs import (
    INPUT,
    INPUT_KEYBOARD,
    KEYEVENTF_KEYUP,
    KEYEVENTF_UNICODE,
    VK_CONTROL,
)

log = logging.getLogger("siqspeak")


def type_text(text: str, release_modifiers: bool = True) -> None:
    """Type text into the focused window using Unicode keyboard events."""
    user32 = ctypes.windll.user32

    if release_modifiers:
        # Release held modifiers from Ctrl+Win hotkey before injecting text.
        # 0x5B = VK_LWIN
        release = (INPUT * 2)()
        for i, vk in enumerate((VK_CONTROL, 0x5B)):
            release[i].type = INPUT_KEYBOARD
            release[i].ki.wVk = vk
            release[i].ki.dwFlags = KEYEVENTF_KEYUP
        user32.SendInput(2, ctypes.pointer(release[0]), ctypes.sizeof(INPUT))
        time.sleep(0.05)

    # Send each character as a Unicode key down + key up pair
    n = len(text) * 2
    inputs = (INPUT * n)()
    for i, char in enumerate(text):
        code = ord(char)
        inputs[i * 2].type = INPUT_KEYBOARD
        inputs[i * 2].ki.wVk = 0
        inputs[i * 2].ki.wScan = code
        inputs[i * 2].ki.dwFlags = KEYEVENTF_UNICODE
        inputs[i * 2 + 1].type = INPUT_KEYBOARD
        inputs[i * 2 + 1].ki.wVk = 0
        inputs[i * 2 + 1].ki.wScan = code
        inputs[i * 2 + 1].ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    user32.SendInput(n, ctypes.pointer(inputs[0]), ctypes.sizeof(INPUT))


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
