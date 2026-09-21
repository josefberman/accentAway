"""Local FastAPI WebSocket server for AccentAway."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from converter import SAMPLE_RATE, load_converter
from gender import FEMALE, MALE, UNKNOWN, GenderTracker

HOST = "127.0.0.1"
PORT = 8765
INT16_SCALE = 32767.0

app = FastAPI(title="AccentAway")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CONVERTER, INFO = load_converter()
START_TIME = time.time()


def pcm_bytes_to_float(data: bytes) -> np.ndarray:
    i16 = np.frombuffer(data, dtype="<i2")
    return (i16.astype(np.float32) / INT16_SCALE).copy()


def float_to_pcm_bytes(pcm: np.ndarray) -> bytes:
    clipped = np.clip(pcm, -1.0, 1.0)
    i16 = (clipped * INT16_SCALE).astype("<i2")
    return i16.tobytes()


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "mode": INFO.mode,
        "device": INFO.device,
        "cuda": INFO.cuda,
        "refs": INFO.refs,
        "sample_rate": SAMPLE_RATE,
        "uptime_s": round(time.time() - START_TIME, 1),
    }


@app.websocket("/convert")
async def convert_socket(ws: WebSocket) -> None:
    await ws.accept()
    accent = "us"
    gender_override = "auto"
    tracker = GenderTracker(sample_rate=SAMPLE_RATE)
    last_gender = UNKNOWN
    CONVERTER.set_reference(accent, "male")
    await ws.send_text(
        json.dumps(
            {
                "type": "status",
                "mode": INFO.mode,
                "device": INFO.device,
                "gender": UNKNOWN,
            }
        )
    )
    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
            text = message.get("text")
            data = message.get("bytes")
            if text:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    await ws.send_text(
                        json.dumps({"type": "error", "message": "Invalid JSON"})
                    )
                    continue
                if payload.get("type") == "config":
                    accent = payload.get("accent", accent)
                    if accent not in ("us", "uk"):
                        accent = "us"
                    gender_override = payload.get("genderOverride", gender_override)
                    if gender_override not in ("auto", MALE, FEMALE):
                        gender_override = "auto"
                    effective = (
                        gender_override if gender_override != "auto" else tracker.gender
                    )
                    if effective == UNKNOWN:
                        effective = MALE
                    CONVERTER.set_reference(accent, effective)
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "gender",
                                "value": tracker.gender
                                if gender_override == "auto"
                                else gender_override,
                            }
                        )
                    )
                continue
            if not data:
                continue

            t0 = time.perf_counter()
            pcm = pcm_bytes_to_float(data)
            detected = tracker.push(pcm)
            if gender_override == "auto":
                effective = detected if detected != UNKNOWN else MALE
            else:
                effective = gender_override
            CONVERTER.set_reference(accent, effective)
            if detected != last_gender:
                last_gender = detected
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "gender",
                            "value": detected
                            if gender_override == "auto"
                            else gender_override,
                        }
                    )
                )

            out = CONVERTER.convert_block(pcm)
            if out is None:
                continue
            await ws.send_bytes(float_to_pcm_bytes(out))
            ms = int((time.perf_counter() - t0) * 1000)
            await ws.send_text(json.dumps({"type": "latency", "ms": ms}))
    except WebSocketDisconnect:
        return


def main() -> None:
    refs = Path(__file__).resolve().parent / "refs"
    missing = [p.name for p in [refs / f"{k}.wav" for k in (
        "us_male",
        "us_female",
        "uk_male",
        "uk_female",
    )] if not p.is_file()]
    if missing:
        print(f"[accentaway] Missing refs: {missing}. Run python download_refs.py")
    print(f"[accentaway] mode={INFO.mode} device={INFO.device} cuda={INFO.cuda}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
