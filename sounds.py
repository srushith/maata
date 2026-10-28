"""Soft start/stop sounds, generated once and played without blocking."""
import os
import tempfile
import wave

import numpy as np

try:
    import winsound
except ImportError:  # not on Windows
    winsound = None

RATE = 44100
SOUND_DIR = os.path.join(tempfile.gettempdir(), "Maata", "sounds")

# name: list of (frequency in Hz, length in seconds)
TONES = {
    "start": [(660, 0.07), (880, 0.09)],   # rising: listening
    "stop": [(880, 0.07), (660, 0.09)],    # falling: got it
    "cancel": [(440, 0.12)],               # low: thrown away
}


def _note(freq, length, volume=0.22):
    t = np.arange(int(RATE * length)) / RATE
    wave_ = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(4 * np.pi * freq * t)
    # Quick fade in and a longer fade out, so it sounds soft rather than beepy.
    envelope = np.minimum(1.0, t / 0.008) * np.exp(-t / (length * 0.6))
    return wave_ * envelope * volume


def _path(name):
    path = os.path.join(SOUND_DIR, f"{name}.wav")
    if not os.path.exists(path):
        os.makedirs(SOUND_DIR, exist_ok=True)
        samples = np.concatenate([_note(f, s) for f, s in TONES[name]])
        with wave.open(path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(RATE)
            f.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


def play(name):
    if winsound is None:
        return
    try:
        winsound.PlaySound(_path(name), winsound.SND_FILENAME | winsound.SND_ASYNC
                           | winsound.SND_NODEFAULT)
    except Exception:
        pass  # a missing sound should never break dictation
