import os
import time

import pyperclip
import win32api
import win32con
import win32gui
import win32process

# Taskbar, tray and desktop: never useful places to paste into.
_SHELL_CLASSES = {
    "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
    "TopLevelWindowForOverflowXamlIsland", "Progman", "WorkerW",
}


def get_foreground_window():
    """Handle of the window the user is currently using (or None)."""
    try:
        return win32gui.GetForegroundWindow() or None
    except Exception:
        return None


def is_paste_target(hwnd):
    """True for a normal app window that isn't Maata itself or the taskbar."""
    try:
        if not hwnd or not win32gui.IsWindow(hwnd):
            return False
        if win32process.GetWindowThreadProcessId(hwnd)[1] == os.getpid():
            return False
        return win32gui.GetClassName(hwnd) not in _SHELL_CLASSES
    except Exception:
        return False


def _focus_window(hwnd):
    """Bring hwnd to the front. Returns True if it is now the active window."""
    try:
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        if not win32gui.IsWindow(hwnd):
            return False
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        # Windows only lets an app switch focus right after a key press,
        # so tap Alt first to be allowed to call SetForegroundWindow.
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.15)
    try:
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


def _press_ctrl_v():
    v_key = ord("V")
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    win32api.keybd_event(v_key, 0, 0, 0)
    time.sleep(0.02)
    win32api.keybd_event(v_key, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)


def paste_text(text, target_hwnd):
    """Paste text into target_hwnd, then put the user's clipboard back.

    Returns a short status message for the UI.
    """
    if not target_hwnd:
        return "No window to paste into. Click into an app first."

    if not _focus_window(target_hwnd):
        pyperclip.copy(text)
        return "Couldn't switch back to your window. Text is on the clipboard: press Ctrl+V."

    try:
        previous = pyperclip.paste()
    except Exception:
        previous = None

    pyperclip.copy(text)
    _press_ctrl_v()

    # Give the target app a moment to read the clipboard before restoring it.
    time.sleep(0.3)
    if previous:
        pyperclip.copy(previous)
    return "Pasted ✅"
