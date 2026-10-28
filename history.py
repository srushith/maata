"""The last few transcripts, kept only on this PC (in %APPDATA%, Maata folder, history.json)."""
import json
import os
import time

MAX_ITEMS = 10
HISTORY_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Maata")
HISTORY_PATH = os.path.join(HISTORY_DIR, "history.json")


def load():
    """Newest first: [{"time": "2026-10-29 14:05", "text": "..."}]"""
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            items = json.load(f)
        return [i for i in items if isinstance(i, dict) and i.get("text")][:MAX_ITEMS]
    except (OSError, ValueError):
        return []


def _write(items):
    os.makedirs(HISTORY_DIR, exist_ok=True)
    temp = HISTORY_PATH + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(temp, HISTORY_PATH)


def add(text):
    text = text.strip()
    if not text:
        return
    items = [{"time": time.strftime("%Y-%m-%d %H:%M"), "text": text}] + load()
    try:
        _write(items[:MAX_ITEMS])
    except OSError:
        pass


def clear():
    try:
        os.remove(HISTORY_PATH)
    except OSError:
        pass
