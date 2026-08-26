"""Local owner voice verification for Doggie.

Only compact speaker embeddings are stored. Raw enrollment recordings are
discarded immediately after their embeddings are calculated.
"""
from pathlib import Path
import time

import numpy as np


class OwnerVoice:
    SAMPLE_RATE = 16000
    ENROLLMENT_SECONDS = 4.0
    MIN_RMS = 0.012
    THRESHOLD = 0.62

    def __init__(self, root="/home/matt/.pidog_voice",
                 model="/home/matt/.local/share/doggie/models/speaker.onnx"):
        self.root = Path(root)
        self.profile_path = self.root / "owner_embeddings.npy"
        self.model_path = Path(model)
        self._extractor = None

    def enrolled(self):
        return self.profile_path.exists()

    def _extract(self, pcm, sample_rate):
        if not self.model_path.exists():
            raise RuntimeError("local speaker model is unavailable")
        import sherpa_onnx
        if self._extractor is None:
            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig()
            config.model = str(self.model_path)
            config.num_threads = 2
            config.provider = "cpu"
            self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        audio = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if len(audio) < int(sample_rate * 1.2):
            raise ValueError("not enough speech")
        if float(np.sqrt(np.mean(audio * audio))) < self.MIN_RMS:
            raise ValueError("audio is too quiet")
        stream = self._extractor.create_stream()
        stream.accept_waveform(sample_rate, audio)
        stream.input_finished()
        embedding = np.asarray(self._extractor.compute(stream), dtype=np.float32)
        return embedding / max(float(np.linalg.norm(embedding)), 1e-8)

    def enroll(self, say):
        """Collect three local samples. Returns ``(ok, message)``."""
        import sounddevice as sd
        samples = []
        prompts = (
            "Doggie is ready to listen.",
            "My voice is my key.",
            "Keep commands local and safe.",
        )
        say("I will learn your voice. Please speak each phrase after the beep.")
        for number, phrase in enumerate(prompts, 1):
            say(f"Sample {number}. Say: {phrase}")
            time.sleep(0.5)
            audio = sd.rec(int(self.ENROLLMENT_SECONDS * self.SAMPLE_RATE),
                           samplerate=self.SAMPLE_RATE, channels=1,
                           dtype="float32")
            sd.wait()
            try:
                samples.append(self._extract(audio[:, 0], self.SAMPLE_RATE))
            except (RuntimeError, ValueError) as exc:
                return False, f"Sample {number} failed: {exc}"
        self.root.mkdir(parents=True, exist_ok=True)
        np.save(self.profile_path, np.stack(samples))
        return True, "Your local voice profile is ready."

    def verify_pcm(self, pcm_bytes, sample_rate):
        """Return ``(matched, score, detail)`` without retaining audio."""
        if not self.enrolled():
            return True, 1.0, "voice profile not enrolled"
        try:
            pcm = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            candidate = self._extract(pcm, sample_rate)
            enrolled = np.load(self.profile_path)
            scores = enrolled @ candidate
            score = float(np.max(scores))
            return score >= self.THRESHOLD, score, "verified" if score >= self.THRESHOLD else "voice did not match"
        except Exception as exc:
            return False, 0.0, f"voice check unavailable: {exc}"
