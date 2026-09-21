"""VAD-gated gender classification with hysteresis."""

from __future__ import annotations

from collections import deque

import numpy as np

MALE = "male"
FEMALE = "female"
UNKNOWN = "unknown"

SPEECH_RMS = 0.015
F0_SPLIT_HZ = 165.0


class GenderTracker:
    """Classify speaker gender from 16 kHz float PCM.

    Uses a pretrained SpeechBrain model when available, otherwise median F0.
    Only speech frames (energy VAD) vote. Several agreeing windows are required
    before switching a locked male/female label.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        window_seconds: float = 1.2,
        agree_needed: int = 3,
        history: int = 8,
    ) -> None:
        self.sample_rate = sample_rate
        self.window_samples = int(window_seconds * sample_rate)
        self.agree_needed = agree_needed
        self.buffer = np.zeros(0, dtype=np.float32)
        self.votes: deque[str] = deque(maxlen=history)
        self.locked: str | None = None
        self._neural = None
        self._init_neural()

    def _init_neural(self) -> None:
        try:
            from speechbrain.inference.classifiers import EncoderClassifier

            self._neural = EncoderClassifier.from_hparams(
                source="speechbrain/gender-recognition-wav2vec2-librispeech",
                savedir="pretrained_models/gender-recognition-wav2vec2-librispeech",
                run_opts={"device": "cpu"},
            )
        except Exception:
            self._neural = None

    def reset(self) -> None:
        self.buffer = np.zeros(0, dtype=np.float32)
        self.votes.clear()
        self.locked = None

    @property
    def gender(self) -> str:
        return self.locked or UNKNOWN

    def push(self, pcm: np.ndarray) -> str:
        if pcm.size == 0:
            return self.gender
        self.buffer = np.concatenate([self.buffer, np.asarray(pcm, dtype=np.float32)])
        while self.buffer.size >= self.window_samples:
            window = self.buffer[: self.window_samples]
            self.buffer = self.buffer[self.window_samples // 2 :]
            self._consider(window)
        return self.gender

    def _consider(self, window: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(np.square(window))))
        if rms < SPEECH_RMS:
            return
        label = self._classify(window)
        if label not in (MALE, FEMALE):
            return
        self.votes.append(label)
        if len(self.votes) < self.agree_needed:
            if self.locked is None:
                return
            return
        male = sum(1 for v in self.votes if v == MALE)
        female = sum(1 for v in self.votes if v == FEMALE)
        if male >= self.agree_needed and male > female:
            self.locked = MALE
        elif female >= self.agree_needed and female > male:
            self.locked = FEMALE
        elif self.locked is None:
            self.locked = MALE if male >= female else FEMALE

    def _classify(self, window: np.ndarray) -> str:
        neural = self._classify_neural(window)
        if neural:
            return neural
        return self._classify_pitch(window)

    def _classify_neural(self, window: np.ndarray) -> str | None:
        if self._neural is None:
            return None
        try:
            import torch

            wav = torch.from_numpy(window).float().unsqueeze(0)
            out = self._neural.classify_batch(wav, torch.tensor([1.0]))
            text = str(out[3][0]).lower()
            if "female" in text:
                return FEMALE
            if "male" in text:
                return MALE
        except Exception:
            return None
        return None

    def _classify_pitch(self, window: np.ndarray) -> str:
        try:
            import librosa

            f0 = librosa.yin(
                window,
                fmin=75,
                fmax=320,
                sr=self.sample_rate,
                frame_length=1024,
            )
            voiced = f0[np.isfinite(f0) & (f0 > 0)]
            if voiced.size < 4:
                return UNKNOWN
            median = float(np.median(voiced))
            if median < F0_SPLIT_HZ:
                return MALE
            return FEMALE
        except Exception:
            return UNKNOWN
