"""Colors and styles. Follows the Windows light/dark setting."""
import ctypes

try:
    import winreg
except ImportError:  # not on Windows
    winreg = None

LIGHT = {
    "bg": "#F4F5F7",
    "surface": "#FFFFFF",
    "surface_hover": "#EEF0F3",
    "border": "#E1E4E8",
    "text": "#1B1D21",
    "muted": "#6B7280",
    "accent": "#2563EB",
    "recording": "#E5484D",
    "processing": "#F59E0B",
    "success": "#16A34A",
    "error": "#DC2626",
}

DARK = {
    "bg": "#16181C",
    "surface": "#1F2227",
    "surface_hover": "#2A2E34",
    "border": "#30353C",
    "text": "#ECEEF1",
    "muted": "#9BA1AA",
    "accent": "#4C8DFF",
    "recording": "#F2555A",
    "processing": "#F5B041",
    "success": "#3FB950",
    "error": "#F87171",
}


def is_dark_mode():
    if winreg is None:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except OSError:
        return False


COLORS = DARK if is_dark_mode() else LIGHT
IS_DARK = COLORS is DARK


def apply_title_bar(widget):
    """Match the window's title bar to dark mode (Windows 10 20H1+ / 11)."""
    if not IS_DARK:
        return
    try:
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(widget.winId()), 20, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def stylesheet():
    c = COLORS
    return f"""
    * {{
        font-family: "Segoe UI Variable Text", "Segoe UI";
        color: {c['text']};
    }}
    QWidget#root, QDialog {{ background: {c['bg']}; }}

    QLabel#title {{ font-size: 15px; font-weight: 600; }}
    QLabel#status {{ font-size: 18px; font-weight: 600; }}
    QLabel#hint {{ font-size: 12px; color: {c['muted']}; }}
    QLabel#hint[error="true"] {{ color: {c['error']}; }}
    QLabel#count, QLabel#formHint {{ font-size: 11px; color: {c['muted']}; }}
    QLabel#formError {{ color: {c['error']}; }}

    QFrame#card {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QFrame#divider {{ background: {c['border']}; max-height: 1px; border: none; }}

    QPlainTextEdit {{
        background: transparent;
        border: none;
        padding: 6px 4px;
        font-size: 14px;
        selection-background-color: {c['accent']};
        selection-color: white;
    }}

    QToolButton#icon {{
        background: transparent;
        border: none;
        border-radius: 8px;
        padding: 4px;
        font-size: 16px;
        color: {c['muted']};
    }}
    QToolButton#icon:hover {{ background: {c['surface_hover']}; color: {c['text']}; }}
    QToolButton#icon:checked {{ color: {c['accent']}; }}

    QPushButton#ghost {{
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 12px;
        color: {c['accent']};
    }}
    QPushButton#ghost:hover {{ background: {c['surface_hover']}; }}
    QPushButton#ghost:disabled {{ color: {c['muted']}; }}

    QCheckBox {{ font-size: 13px; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border: 1px solid {c['border']};
        border-radius: 4px;
        background: {c['surface']};
    }}
    QCheckBox::indicator:checked {{
        background: {c['accent']};
        border-color: {c['accent']};
    }}

    QLineEdit, QComboBox {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 6px 8px;
        font-size: 13px;
    }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        selection-background-color: {c['accent']};
        selection-color: white;
    }}

    QDialogButtonBox QPushButton {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 6px 16px;
        min-width: 70px;
    }}
    QDialogButtonBox QPushButton:hover {{ background: {c['surface_hover']}; }}
    QDialogButtonBox QPushButton:default {{
        background: {c['accent']};
        border-color: {c['accent']};
        color: white;
    }}

    QMenu {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        padding: 4px;
    }}
    QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {c['surface_hover']}; }}
    QMenu::item:disabled {{ color: {c['muted']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}
    QToolTip {{
        background: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['border']};
        padding: 4px;
    }}
    """
