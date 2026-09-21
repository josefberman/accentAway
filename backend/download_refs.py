"""Create or download 3–8 s native US/UK reference clips for Seed-VC."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from urllib.request import urlopen

REFS_DIR = Path(__file__).resolve().parent / "refs"

# Short CC / public-domain-style speech samples used when network is available.
# Users can replace these with any 3–8 s native clip of the matching accent/gender.
REMOTE_REFS = {
    "us_male": "https://raw.githubusercontent.com/Plachtaa/seed-vc/main/examples/reference/trump_0.wav",
    "us_female": "https://raw.githubusercontent.com/coqui-ai/TTS/dev/tests/data/ljspeech/wavs/LJ001-0001.wav",
    "uk_male": "https://raw.githubusercontent.com/Plachtaa/seed-vc/main/examples/reference/s1p1.wav",
    "uk_female": "https://raw.githubusercontent.com/Plachtaa/seed-vc/main/examples/reference/s2p1.wav",
}

SAMPLE_RATE = 16000
DURATION = 4.0


def _write_wav(path: Path, samples: list[float], sr: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        frames = b"".join(
            struct.pack("<h", max(-32767, min(32767, int(s * 32767)))) for s in samples
        )
        wf.writeframes(frames)


def _formant_placeholder(kind: str) -> list[float]:
    """Speech-like harmonic placeholder so the repo runs without a download."""
    n = int(SAMPLE_RATE * DURATION)
    male = kind.endswith("male") and "female" not in kind
    f0 = 110.0 if male else 210.0
    formants = (700, 1200, 2500) if "us" in kind else (550, 900, 2300)
    out = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = 0.15 + 0.85 * abs(math.sin(2 * math.pi * 3.5 * t))
        s = 0.0
        for h in range(1, 8):
            s += (1.0 / h) * math.sin(2 * math.pi * f0 * h * t)
        for f in formants:
            s += 0.15 * math.sin(2 * math.pi * f * t)
        out.append(0.18 * env * s)
    return out


def _download(url: str, dest: Path) -> bool:
    try:
        with urlopen(url, timeout=30) as resp:
            dest.write_bytes(resp.read())
        print(f"downloaded {dest.name} <- {url}")
        return True
    except Exception as exc:
        print(f"skip {dest.name}: {exc}")
        return False


def main() -> None:
    REFS_DIR.mkdir(parents=True, exist_ok=True)
    for key, url in REMOTE_REFS.items():
        dest = REFS_DIR / f"{key}.wav"
        tmp = REFS_DIR / f"{key}.download"
        # Placeholders are ~128 KiB; keep only real downloaded clips.
        if dest.exists() and dest.stat().st_size > 200_000:
            print(f"keep {dest.name}")
            continue
        if _download(url, tmp):
            if tmp.suffix == ".flac" or url.endswith(".flac"):
                try:
                    import librosa
                    import soundfile as sf

                    wav, sr = librosa.load(str(tmp), sr=SAMPLE_RATE, duration=8)
                    sf.write(str(dest), wav, SAMPLE_RATE)
                    tmp.unlink(missing_ok=True)
                    continue
                except Exception as exc:
                    print(f"decode failed ({exc}), using placeholder")
                    tmp.unlink(missing_ok=True)
            else:
                tmp.rename(dest)
                continue
        _write_wav(dest, _formant_placeholder(key))
        print(f"placeholder {dest.name}")


if __name__ == "__main__":
    main()
