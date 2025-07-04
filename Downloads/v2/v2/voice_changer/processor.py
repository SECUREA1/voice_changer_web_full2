# voice_changer/processor.py
import numpy as np
import sounddevice as sd
import threading
from pydub import AudioSegment
import io

class Parameters:
    def __init__(self):
        self.is_recording = False
        self.recorded_data = []
        self.effect = "normal"  # Default effect
        self.stream_event = threading.Event()

params = Parameters()
data_lock = threading.Lock()

class VoiceProcessor:
    def __init__(self):
        self.effects = {
            "normal": self.apply_normal,
            "robot": self.apply_robot,
            "echo": self.apply_echo,
            "chipmunk": self.apply_chipmunk,
            "deep": self.apply_deep
        }

    def apply_effect(self, audio_array, samplerate, effect_name):
        audio_segment = AudioSegment(
            audio_array.tobytes(),
            frame_rate=samplerate,
            sample_width=audio_array.dtype.itemsize,
            channels=1
        )
        processed = self.effects.get(effect_name, self.apply_normal)(audio_segment)
        samples = np.array(processed.get_array_of_samples()).astype(np.float32) / 32768.0
        return samples

    def apply_normal(self, audio):
        return audio

    def apply_robot(self, audio):
        return audio.low_pass_filter(400).overlay(audio.high_pass_filter(3000))

    def apply_echo(self, audio):
        delay = 250
        echo = audio - 10
        for i in range(1, 4):
            echo = echo.overlay(audio - 10 * i, delay * i)
        return audio.overlay(echo)

    def apply_chipmunk(self, audio):
        return audio._spawn(audio.raw_data, overrides={
            "frame_rate": int(audio.frame_rate * 1.5)
        }).set_frame_rate(audio.frame_rate)

    def apply_deep(self, audio):
        return audio._spawn(audio.raw_data, overrides={
            "frame_rate": int(audio.frame_rate * 0.75)
        }).set_frame_rate(audio.frame_rate)

# Instance used by stream
voice_processor = VoiceProcessor()

def update_effects(effects_dict):
    with data_lock:
        if "effect" in effects_dict:
            effect = effects_dict["effect"]
            if effect in voice_processor.effects:
                params.effect = effect

# Live audio callback
def audio_callback(indata, outdata, frames, time_info, status):
    if status:
        print("Stream Status:", status)
    audio_data = indata[:, 0].copy()

    # Apply effect
    with data_lock:
        effect_name = params.effect
    processed = voice_processor.apply_effect(audio_data, 44100, effect_name)

    # Record if enabled
    if params.is_recording:
        with data_lock:
            params.recorded_data.append(processed.copy())

    outdata[:, 0] = np.clip(processed, -1.0, 1.0)

def start_audio_stream(stop_event):
    with sd.Stream(channels=1, samplerate=44100, blocksize=1024, callback=audio_callback):
        while not stop_event.is_set():
            sd.sleep(100)
