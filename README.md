# AccentAway

Chrome extension that replaces a video tab’s speech with **American** or **British** English. A local NVIDIA GPU backend runs [Seed-VC](https://github.com/Plachtaa/seed-vc) realtime (`seed-uvit-tat-xlsr-tiny`) and keeps **male / female** by classifying the speaker.

## What it does

1. Click the extension on a tab that is playing video.
2. Choose American or British, Start.
3. Chrome mutes the tab (tabCapture). Converted speech plays from the extension.
4. Stop restores normal tab audio.

Gender defaults to **Auto** (live classifier + hysteresis). Override with Male / Female if it is wrong.

## Requirements

- Google Chrome (Manifest V3)
- Python 3.10+
- For real accent conversion: **NVIDIA GPU + CUDA**, PyTorch CUDA build, and a clone of Seed-VC
- Without GPU / Seed-VC the backend still runs in **echo** mode (round-trip PCM) so capture and playback can be verified

## Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python download_refs.py
python server.py
```

Health check: [http://127.0.0.1:8765/health](http://127.0.0.1:8765/health)

### CUDA + Seed-VC

Install a CUDA PyTorch build from [pytorch.org](https://pytorch.org), then:

```bash
chmod +x backend/setup_seed_vc.sh
backend/setup_seed_vc.sh
# from the seed-vc clone, install its requirements (torch/torchaudio already present)
source backend/.venv/bin/activate
pip install -r third_party/seed-vc/requirements.txt
python backend/server.py
```

First Seed-VC start downloads DiT tiny + CAMPPlus + vocoder weights from Hugging Face.

To force echo mode (no GPU): `ACCENTAWAY_ECHO=1 python backend/server.py`

Optional neural gender model: `pip install speechbrain` (otherwise pitch / F0 is used).

Replace `backend/refs/{us_male,us_female,uk_male,uk_female}.wav` with 3–8 s native clips of the matching accent and gender for better conversion.

## Extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select the `extension/` folder
4. Play a video, click the AccentAway icon, pick American or British, **Start**

The popup shows backend status, mode (`echo` or `seed-vc`), device, detected gender, and latency.

## Limitations

- Seed-VC maps toward the **reference voice**. Accent and some timbre both move; it is not the original speaker with only the accent swapped.
- Lip-sync: video stays about **0.3–0.6 s** ahead of converted audio. Latency is shown in the popup; v1 does not delay video frames.
- Whole-tab audio is converted (ads, music, other players on the page). Music and SFX will sound wrong.
- Encrypted / DRM media (Netflix and similar) often yields silence.
- Gender is binary male/female from audio. Rapid speaker changes, children, and overlapping talk can lag or misfire until the lock updates.

## Layout

```
extension/     Chrome MV3 (tabCapture + offscreen PCM + popup)
backend/      FastAPI WebSocket on 127.0.0.1:8765
third_party/   Seed-VC clone (optional)
```
