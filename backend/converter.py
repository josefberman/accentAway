"""Realtime voice conversion: Seed-VC tiny when available, otherwise PCM echo."""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

SAMPLE_RATE = 16000
REF_KEYS = ("us_male", "us_female", "uk_male", "uk_female")


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def seed_vc_root() -> Path:
    env = os.environ.get("SEED_VC_ROOT")
    if env:
        return Path(env)
    return _project_root().parent / "third_party" / "seed-vc"


@dataclass
class BackendInfo:
    mode: str
    device: str
    cuda: bool
    refs: list[str]


class EchoConverter:
    """Pass-through converter used to prove capture/playback without GPU models."""

    sample_rate = SAMPLE_RATE
    mode = "echo"
    device = "cpu"

    def __init__(self) -> None:
        self._key = "us_male"

    def set_reference(self, accent: str, gender: str) -> str:
        gender = gender if gender in ("male", "female") else "male"
        accent = accent if accent in ("us", "uk") else "us"
        self._key = f"{accent}_{gender}"
        return self._key

    def convert_block(self, pcm: np.ndarray) -> np.ndarray:
        return np.asarray(pcm, dtype=np.float32)


class SeedVCConverter:
    """Wrap Plachtaa/seed-vc realtime tiny (DiT_uvit_tat_xlsr)."""

    sample_rate = SAMPLE_RATE
    mode = "seed-vc"

    def __init__(self, refs_dir: Path) -> None:
        self.refs_dir = refs_dir
        self._lock = threading.Lock()
        self._key = "us_male"
        self._prompt_cache: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        root = seed_vc_root()
        if not root.is_dir():
            raise FileNotFoundError(
                f"Seed-VC repo not found at {root}. Clone "
                "https://github.com/Plachtaa/seed-vc into third_party/seed-vc "
                "or set SEED_VC_ROOT."
            )

        self._cwd = os.getcwd()
        os.chdir(root)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        import torch
        from hf_utils import load_custom_model_from_hf
        from modules.commons import str2bool  # noqa: F401

        if torch.cuda.is_available():
            self.device = torch.device("cuda")
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            self.device = torch.device("mps")
        else:
            self.device = torch.device("cpu")

        import importlib.util

        gui_path = root / "real-time-gui.py"
        spec = importlib.util.spec_from_file_location("seed_vc_realtime_gui", gui_path)
        if spec is None or spec.loader is None:
            raise ImportError("Cannot load seed-vc real-time-gui.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.device = self.device

        args = type("Args", (), {})()
        args.checkpoint_path = None
        args.config_path = None
        args.fp16 = self.device.type == "cuda"

        self._torch = torch
        self._mod = mod
        self.model_set = mod.load_models(args)
        self.model_sr = int(self.model_set[-1]["sampling_rate"])
        os.chdir(self._cwd)

        self._init_stream_buffers()
        self._load_references()

    def _init_stream_buffers(self) -> None:
        torch = self._torch
        # Match seed-vc realtime GUI defaults for ~0.3–0.6 s delay on GPU.
        self.block_time = 0.25
        self.crossfade_time = 0.04
        self.extra_time_ce = 2.5
        self.extra_time = 0.5
        self.extra_time_right = 0.02
        self.diffusion_steps = 4
        self.inference_cfg_rate = 0.7
        self.max_prompt_length = 3.0

        sr = self.model_sr
        zc = sr // 50
        self.zc = zc
        self.block_frame = int(np.round(self.block_time * sr / zc)) * zc
        self.block_frame_16k = 320 * self.block_frame // zc
        self.crossfade_frame = int(np.round(self.crossfade_time * sr / zc)) * zc
        self.sola_buffer_frame = min(self.crossfade_frame, 4 * zc)
        self.sola_search_frame = zc
        self.extra_frame = int(np.round(self.extra_time_ce * sr / zc)) * zc
        self.extra_frame_right = int(np.round(self.extra_time_right * sr / zc)) * zc

        dev = self.device
        self.input_wav = torch.zeros(
            self.extra_frame
            + self.crossfade_frame
            + self.sola_search_frame
            + self.block_frame
            + self.extra_frame_right,
            device=dev,
            dtype=torch.float32,
        )
        self.input_wav_res = torch.zeros(
            320 * self.input_wav.shape[0] // zc,
            device=dev,
            dtype=torch.float32,
        )
        self.sola_buffer = torch.zeros(
            self.sola_buffer_frame, device=dev, dtype=torch.float32
        )
        self.fade_in_window = (
            torch.sin(
                0.5
                * np.pi
                * torch.linspace(0.0, 1.0, steps=self.sola_buffer_frame, device=dev)
            )
            ** 2
        )
        self.fade_out_window = 1 - self.fade_in_window
        self.skip_head = self.extra_frame // zc
        self.skip_tail = self.extra_frame_right // zc
        self.return_length = (
            self.block_frame + self.sola_buffer_frame + self.sola_search_frame
        ) // zc
        self._pending_16k = np.zeros(0, dtype=np.float32)

        import torchaudio.transforms as tat

        self.resampler_16k_to_model = None
        if self.model_sr != SAMPLE_RATE:
            self.resampler_16k_to_model = tat.Resample(
                orig_freq=SAMPLE_RATE, new_freq=self.model_sr, dtype=torch.float32
            ).to(dev)
        self.resampler_model_to_16k = None
        if self.model_sr != SAMPLE_RATE:
            self.resampler_model_to_16k = tat.Resample(
                orig_freq=self.model_sr, new_freq=SAMPLE_RATE, dtype=torch.float32
            ).to(dev)

    def _load_references(self) -> None:
        import librosa

        self.reference_wavs: dict[str, np.ndarray] = {}
        for key in REF_KEYS:
            path = self.refs_dir / f"{key}.wav"
            if not path.is_file():
                raise FileNotFoundError(f"Missing reference clip: {path}")
            wav, _ = librosa.load(str(path), sr=self.model_sr)
            self.reference_wavs[key] = wav.astype(np.float32)
        self.set_reference("us", "male")

    def set_reference(self, accent: str, gender: str) -> str:
        gender = gender if gender in ("male", "female") else "male"
        accent = accent if accent in ("us", "uk") else "us"
        key = f"{accent}_{gender}"
        self._key = key
        return key

    def convert_block(self, pcm_16k: np.ndarray) -> np.ndarray | None:
        """Accept 16 kHz float PCM. Return a converted 16 kHz block or None if buffering."""
        pcm_16k = np.asarray(pcm_16k, dtype=np.float32)
        with self._lock:
            self._pending_16k = np.concatenate([self._pending_16k, pcm_16k])
            need = self.block_frame_16k
            if self._pending_16k.size < need:
                return None
            block = self._pending_16k[:need]
            self._pending_16k = self._pending_16k[need:]
            return self._infer_block(block)

    def _infer_block(self, block_16k: np.ndarray) -> np.ndarray:
        torch = self._torch
        F = torch.nn.functional
        mod = self._mod

        indata = block_16k
        if self.resampler_16k_to_model is not None:
            t = torch.from_numpy(block_16k).to(self.device)
            indata = self.resampler_16k_to_model(t).detach().cpu().numpy()

        self.input_wav[: -self.block_frame] = self.input_wav[self.block_frame :].clone()
        n = min(indata.shape[0], self.block_frame)
        self.input_wav[-n:] = torch.from_numpy(indata[:n]).to(self.device)

        self.input_wav_res[: -self.block_frame_16k] = self.input_wav_res[
            self.block_frame_16k :
        ].clone()
        tail = self.input_wav[-n - 2 * self.zc :].detach().cpu().numpy()
        import librosa

        resampled = librosa.resample(tail, orig_sr=self.model_sr, target_sr=16000)
        chunk = resampled[320:]
        self.input_wav_res[-chunk.shape[0] :] = torch.from_numpy(chunk).to(self.device)

        infer_wav = mod.custom_infer(
            self.model_set,
            self.reference_wavs[self._key],
            self._key,
            self.input_wav_res,
            self.block_frame_16k,
            self.skip_head,
            self.skip_tail,
            self.return_length,
            int(self.diffusion_steps),
            self.inference_cfg_rate,
            self.max_prompt_length,
            self.extra_time_ce - self.extra_time,
        )

        conv_input = infer_wav[None, None, : self.sola_buffer_frame + self.sola_search_frame]
        cor_nom = F.conv1d(conv_input, self.sola_buffer[None, None, :])
        cor_den = torch.sqrt(
            F.conv1d(
                conv_input**2,
                torch.ones(1, 1, self.sola_buffer_frame, device=self.device),
            )
            + 1e-8
        )
        tensor = cor_nom[0, 0] / cor_den[0, 0]
        sola_offset = int(torch.argmax(tensor, dim=0).item()) if tensor.numel() > 1 else 0
        infer_wav = infer_wav[sola_offset:]
        infer_wav[: self.sola_buffer_frame] *= self.fade_in_window
        infer_wav[: self.sola_buffer_frame] += self.sola_buffer * self.fade_out_window
        self.sola_buffer[:] = infer_wav[
            self.block_frame : self.block_frame + self.sola_buffer_frame
        ]
        out = infer_wav[: self.block_frame]
        if self.resampler_model_to_16k is not None:
            out = self.resampler_model_to_16k(out)
        return out.detach().cpu().numpy().astype(np.float32)


def load_converter(refs_dir: Path | None = None) -> tuple[Any, BackendInfo]:
    refs_dir = refs_dir or (_project_root() / "refs")
    cuda = False
    device = "cpu"
    try:
        import torch

        cuda = torch.cuda.is_available()
        if cuda:
            device = "cuda"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device = "mps"
    except Exception:
        pass

    force_echo = os.environ.get("ACCENTAWAY_ECHO", "").lower() in ("1", "true", "yes")
    if not force_echo and cuda:
        try:
            conv = SeedVCConverter(refs_dir)
            return conv, BackendInfo(
                mode=conv.mode,
                device=str(conv.device),
                cuda=cuda,
                refs=list(REF_KEYS),
            )
        except Exception as exc:
            print(f"[accentaway] Seed-VC unavailable ({exc}); using echo converter")
    elif not force_echo and not cuda:
        print("[accentaway] No CUDA GPU; using echo converter (clone Seed-VC + CUDA for conversion)")

    conv = EchoConverter()
    return conv, BackendInfo(mode="echo", device=device, cuda=cuda, refs=list(REF_KEYS))
