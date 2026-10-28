"""Global hotkey settings.

The default is Win+Alt+Space. It isn't used by Windows, Office or browsers.
(Ctrl+Alt+Space is taken by apps like Claude desktop; Ctrl+Shift+Space is
Word's non-breaking space; Alt+Space opens the window menu.) If it's taken,
the app falls back to Ctrl+Win+Alt+Space.

To use something else, add a line like this to your .env file:

    MAATA_HOTKEY=ctrl+alt+d

Modifiers: ctrl, alt, shift, win. Keys: a-z, 0-9, f1-f24, space.
"""
import os

DEFAULT_HOTKEYS = ["win+alt+space", "ctrl+win+alt+space"]

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000  # don't fire again while the keys are held down

_MODIFIERS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "windows": MOD_WIN,
}


def _key_code(name):
    if name == "space":
        return 0x20
    if len(name) == 1 and (name.isalpha() or name.isdigit()):
        return ord(name.upper())
    if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        return 0x70 + int(name[1:]) - 1  # VK_F1 = 0x70
    raise ValueError(f"Unknown key '{name}'")


def parse_hotkey(text):
    """Turn 'ctrl+alt+space' into (modifiers, key_code, 'Ctrl+Alt+Space')."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts:
        raise ValueError("Hotkey is empty")
    *mods, key = parts
    modifiers = MOD_NOREPEAT
    for m in mods:
        if m not in _MODIFIERS:
            raise ValueError(f"Unknown modifier '{m}'")
        modifiers |= _MODIFIERS[m]
    if modifiers == MOD_NOREPEAT and not (key.startswith("f") and key[1:].isdigit()):
        raise ValueError("Use at least one of ctrl/alt/shift/win (or an F-key)")
    label = "+".join(p.capitalize() if len(p) > 1 else p.upper() for p in parts)
    return modifiers, _key_code(key), label


def get_hotkey_candidates(text=None):
    """Hotkeys to try, in order, as (modifiers, key_code, label).

    Uses `text` if given, else MAATA_HOTKEY from .env, else the defaults.
    Also returns a warning if the value couldn't be understood.
    """
    if text is None:
        text = os.getenv("MAATA_HOTKEY", "")
    text = text.strip()
    defaults = [parse_hotkey(h) for h in DEFAULT_HOTKEYS]
    if not text:
        return defaults, None
    try:
        chosen = parse_hotkey(text)
    except ValueError as e:
        return defaults, f"Hotkey '{text}' ignored: {e}."
    if chosen[:2] == defaults[0][:2]:
        return defaults, None  # the default keeps its backup
    return [chosen], None
