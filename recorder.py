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


def record_audio(filename, mic_name=""):
    """Record until stop_recording() is called. Call begin_recording() first."""
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

    data = np.concatenate(recording, axis=0)
    with wave.open(filename, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)  # 16-bit
        f.setframerate(fs)
        f.writeframes(data.tobytes())
    return filename


def stop_recording():
    global is_recording
    is_recording = False
