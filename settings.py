"""App settings, stored in the .env file next to the app.

You can edit them in the app (tray icon → Settings) or directly in .env.
"""
import os
import sys

from dotenv import load_dotenv, set_key

# When running from source, settings live in .env next to the code.
# The packaged .exe keeps them in %APPDATA%\Maata\settings.env, because
# the folder the .exe runs from (e.g. Downloads) may not be writable.
if getattr(sys, "frozen", False):
    APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Maata")
    os.makedirs(APP_DIR, exist_ok=True)
    ENV_PATH = os.path.join(APP_DIR, "settings.env")
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    ENV_PATH = os.path.join(APP_DIR, ".env")
load_dotenv(ENV_PATH)

API_KEY = "OPENAI_API_KEY"

HOTKEY = "MAATA_HOTKEY"
MODEL = "MAATA_MODEL"
LANGUAGE = "MAATA_LANGUAGE"
MIC = "MAATA_MIC"
VOCABULARY = "MAATA_VOCABULARY"
AUTOPASTE = "MAATA_AUTOPASTE"
ON_TOP = "MAATA_ON_TOP"

DEFAULTS = {
    HOTKEY: "win+alt+space",
    MODEL: "gpt-4o-mini-transcribe",
    LANGUAGE: "",      # empty = detect automatically
    MIC: "",           # empty = system default microphone
    VOCABULARY: "",    # comma-separated names/terms to spell correctly
    AUTOPASTE: "false",
    ON_TOP: "true",    # keep the window above other windows
}

# (model id, description shown in Settings)
MODELS = [
    ("gpt-4o-mini-transcribe", "GPT-4o mini: accurate and cheap (recommended)"),
    ("gpt-4o-transcribe", "GPT-4o: most accurate"),
    ("whisper-1", "Whisper: original model"),
]

# (ISO code, name). Empty code = auto-detect.
LANGUAGES = [
    ("", "Detect automatically"),
    ("en", "English"),
    ("hi", "Hindi"),
    ("te", "Telugu"),
    ("ta", "Tamil"),
    ("kn", "Kannada"),
    ("ml", "Malayalam"),
    ("mr", "Marathi"),
    ("bn", "Bengali"),
    ("gu", "Gujarati"),
    ("ur", "Urdu"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("pt", "Portuguese"),
    ("ar", "Arabic"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
]


def get(key):
    return os.getenv(key, DEFAULTS.get(key, "")).strip()


def get_bool(key):
    return get(key).lower() in ("1", "true", "yes", "on")


def save(values):
    """Write settings to .env (keeping everything else in it) and apply them now."""
    if not os.path.exists(ENV_PATH):
        open(ENV_PATH, "a", encoding="utf-8").close()
    for key, value in values.items():
        value = str(value)
        set_key(ENV_PATH, key, value)
        os.environ[key] = value


def has_api_key():
    return bool(get(API_KEY))


def ensure_defaults():
    """Add any missing settings to .env so they're easy to find and edit."""
    missing = {k: v for k, v in DEFAULTS.items() if k not in os.environ}
    if missing:
        save(missing)
