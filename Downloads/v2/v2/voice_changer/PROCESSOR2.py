from pydub import AudioSegment
import os
import tempfile

class VoiceProcessor:
    def __init__(self):
        self.effects = {
            "normal": self.apply_normal,
            "robot": self.apply_robot,
            "echo": self.apply_echo,
            "chipmunk": self.apply_chipmunk,
            "deep": self.apply_deep
        }

    def apply_effect(self, audio_path, effect_type="normal"):
        if not os.path.exists(audio_path):
            raise FileNotFoundError("Audio file not found.")

        if effect_type not in self.effects:
            raise ValueError("Unsupported effect type.")

        audio = AudioSegment.from_file(audio_path)
        processed = self.effects[effect_type](audio)

        # Save processed file to a temporary location
        temp_output = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        processed.export(temp_output.name, format="mp3")
        return temp_output.name

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

# Display the available effects for confirmation
vp = VoiceProcessor()
vp.effects.keys()
