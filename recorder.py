import glob
import os
import tempfile
import time
import wave

import numpy as np
import sounddevice as sd

# Recordings go to a folder in temp, which is always writable. Each recording
# is deleted once it's transcribed; one that fails is kept so it can be retried.
RECORDINGS_DIR = os.path.join(tempfile.gettempdir(), "Maata")


def new_recording_path():
    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    return os.path.join(RECORDINGS_DIR, time.strftime("recording-%Y%m%d-%H%M%S.wav"))


def unsent_recordings():
    """Saved recordings that were never transcribed, newest first."""
    files = glob.glob(os.path.join(RECORDINGS_DIR, "recording-*.wav"))
    return sorted(files, key=os.path.getmtime, reverse=True)


def delete_recording(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass

is_recording = False
current_level = 0.0  # loudness of the latest audio chunk, 0.0 to 1.0
fs = 16000  # Whisper works at 16 kHz; higher rates only make uploads bigger


# Windows lists each mic once per audio system. DirectSound gives full names
# (the default, MME, cuts them at 31 characters) and handles 16 kHz recording.
_PREFERRED_API = "Windows DirectSound"
_SKIP_NAMES = {"Primary Sound Capture Driver", "Microsoft Sound Mapper - Input"}


def _input_devices():
    """(index, name) for each real microphone, listed once."""
    try:
        apis = sd.query_hostapis()
        api = next((i for i, a in enumerate(apis) if a["name"] == _PREFERRED_API), None)
        if api is None:
            api = sd.query_devices(kind="input")["hostapi"]
        devices = []
        for index, device in enumerate(sd.query_devices()):
            if (device["max_input_channels"] > 0 and device["hostapi"] == api
                    and device["name"] not in _SKIP_NAMES):
                devices.append((index, device["name"]))
        return devices
    except Exception:
        return []


def list_microphones():
    """Names of available microphones."""
    return [name for _, name in _input_devices()]


def _find_device(name):
    for index, device_name in _input_devices():
        if device_name == name:
            return index
    return None  # not plugged in any more: use the system default


def begin_recording():
    """Mark recording as started. Call before record_audio, so a quick stop isn't missed."""
    global is_recording
    is_recording = True


def trim_silence(data, rate=fs):
    """Shorten long pauses, since OpenAI bills silence like speech.

    Keeps about a quarter second around speech so no words are clipped.
    Returns (audio, seconds removed). Leaves the audio alone if it can't
    tell speech from silence.
    """
    frame = int(rate * 0.03)
    count = len(data) // frame
    if count < 20:
        return data, 0.0
    frames = data[:count * frame].astype(np.float32).reshape(count, frame)
    db = 20 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) / 32768.0 + 1e-10)

    # Silence is the quiet background level; speech is clearly louder than it.
    floor = np.percentile(db, 10)
    threshold = min(floor + 10, -38)
    speech = db > threshold
    if speech.sum() * 0.03 < 0.5:
        return data, 0.0  # barely any speech found: don't risk cutting it

    pad = 8  # frames (about 0.25 s) kept either side of speech
    keep = np.convolve(speech, np.ones(2 * pad + 1), mode="same") > 0

    # Inside the recording, keep a short gap so words don't run together.
    gap = 6  # about 0.2 s
    first, last = np.argmax(keep), count - 1 - np.argmax(keep[::-1])
    i = first
    while i <= last:
        if not keep[i]:
            j = i
            while j <= last and not keep[j]:
                j += 1
            keep[i:min(i + gap, j)] = True
            i = j
        i += 1

    trimmed = frames[keep].astype(np.int16).reshape(-1)
    removed = (len(data) - len(trimmed)) / rate
    if removed < 1.0:
        return data, 0.0  # not worth changing
    return trimmed, removed


def record_audio(filename, mic_name="", trim=False):
    """Record until stop_recording() is called. Call begin_recording() first.

    Returns the seconds of silence that were cut out.
    """
    global current_level
    current_level = 0.0
    recording = []
    device = _find_device(mic_name) if mic_name else None

    def callback(indata, frames, time, status):
        global current_level
        if not is_recording:
            raise sd.CallbackStop()
        recording.append(indata.copy())
        rms = np.sqrt(np.mean(indata.astype(np.float32) ** 2)) / 32768.0
        current_level = float(min(rms, 1.0))

    with sd.InputStream(samplerate=fs, channels=1, dtype="int16", device=device, callback=callback):
        while is_recording:
            sd.sleep(100)

    current_level = 0.0
    if not recording:
        raise ValueError("No audio was captured. Try recording for a bit longer.")

    data = np.concatenate(recording, axis=0).reshape(-1)
    removed = 0.0
    if trim:
        data, removed = trim_silence(data)
    with wave.open(filename, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)  # 16-bit
        f.setframerate(fs)
        f.writeframes(data.astype(np.int16).tobytes())
    return removed


def stop_recording():
    global is_recording
    is_recording = False
