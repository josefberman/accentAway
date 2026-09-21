const SAMPLE_RATE = 16000;

let captureCtx = null;
let playCtx = null;
let workletNode = null;
let sourceNode = null;
let gainNode = null;
let captureStream = null;
let socket = null;
let nextPlayTime = 0;
let lastSendAt = 0;
let config = { accent: "us", genderOverride: "auto", volume: 1 };

function int16ToFloat32(buffer) {
  const i16 = new Int16Array(buffer);
  const f32 = new Float32Array(i16.length);
  for (let i = 0; i < i16.length; i++) {
    f32[i] = i16[i] / (i16[i] < 0 ? 0x8000 : 0x7fff);
  }
  return f32;
}

function playPcm(arrayBuffer) {
  if (!playCtx || !gainNode) {
    return;
  }
  const f32 = int16ToFloat32(arrayBuffer);
  if (!f32.length) {
    return;
  }
  const buf = playCtx.createBuffer(1, f32.length, SAMPLE_RATE);
  buf.copyToChannel(f32, 0);
  const src = playCtx.createBufferSource();
  src.buffer = buf;
  src.connect(gainNode);
  const now = playCtx.currentTime;
  if (nextPlayTime < now + 0.02) {
    nextPlayTime = now + 0.02;
  }
  src.start(nextPlayTime);
  nextPlayTime += buf.duration;
}

function sendConfig() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(
      JSON.stringify({
        type: "config",
        accent: config.accent,
        genderOverride: config.genderOverride,
      })
    );
  }
}

function reportStatus(patch) {
  chrome.runtime.sendMessage({ type: "status", ...patch }).catch(() => {});
}

async function startCapture(message) {
  await stopCapture();
  config = {
    accent: message.accent || "us",
    genderOverride: message.genderOverride || "auto",
    volume: typeof message.volume === "number" ? message.volume : 1,
  };

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: message.streamId,
      },
    },
    video: false,
  });
  captureStream = stream;

  captureCtx = new AudioContext({ sampleRate: 48000 });
  await captureCtx.audioWorklet.addModule("pcm-worklet.js");
  sourceNode = captureCtx.createMediaStreamSource(stream);
  workletNode = new AudioWorkletNode(captureCtx, "pcm-capture");
  sourceNode.connect(workletNode);
  // Do not connect to destination — tabCapture already mutes the tab.

  playCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
  gainNode = playCtx.createGain();
  gainNode.gain.value = config.volume;
  gainNode.connect(playCtx.destination);
  nextPlayTime = 0;

  const wsUrl = message.wsUrl || "ws://127.0.0.1:8765/convert";
  socket = new WebSocket(wsUrl);
  socket.binaryType = "arraybuffer";

  socket.addEventListener("open", () => {
    sendConfig();
    reportStatus({ error: "", backend: { connected: true } });
  });

  socket.addEventListener("message", (event) => {
    if (typeof event.data === "string") {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "gender") {
          reportStatus({ gender: msg.value });
        } else if (msg.type === "latency") {
          reportStatus({ latencyMs: msg.ms });
        } else if (msg.type === "status") {
          reportStatus({
            backend: {
              connected: true,
              mode: msg.mode,
              device: msg.device,
            },
            gender: msg.gender,
          });
        } else if (msg.type === "error") {
          reportStatus({ error: msg.message || "Backend error" });
        }
      } catch {
        /* ignore malformed JSON */
      }
      return;
    }
    if (lastSendAt) {
      reportStatus({ latencyMs: Date.now() - lastSendAt });
    }
    playPcm(event.data);
  });

  socket.addEventListener("error", () => {
    reportStatus({ error: "WebSocket error — is the backend running?" });
  });

  socket.addEventListener("close", () => {
    reportStatus({ backend: { connected: false } });
  });

  workletNode.port.onmessage = (event) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      lastSendAt = Date.now();
      socket.send(event.data);
    }
  };
}

async function stopCapture() {
  if (workletNode) {
    workletNode.port.onmessage = null;
    workletNode.disconnect();
    workletNode = null;
  }
  if (sourceNode) {
    sourceNode.disconnect();
    sourceNode = null;
  }
  if (captureStream) {
    for (const track of captureStream.getTracks()) {
      track.stop();
    }
    captureStream = null;
  }
  if (socket) {
    socket.close();
    socket = null;
  }
  if (captureCtx) {
    await captureCtx.close();
    captureCtx = null;
  }
  if (playCtx) {
    await playCtx.close();
    playCtx = null;
    gainNode = null;
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message.type === "offscreen-start") {
      try {
        await startCapture(message);
        sendResponse({ ok: true });
      } catch (err) {
        chrome.runtime
          .sendMessage({
            type: "offscreen-error",
            error: String(err.message || err),
          })
          .catch(() => {});
        sendResponse({ ok: false, error: String(err.message || err) });
      }
      return;
    }
    if (message.type === "offscreen-stop") {
      await stopCapture();
      sendResponse({ ok: true });
      return;
    }
    if (message.type === "offscreen-config") {
      if (message.accent) config.accent = message.accent;
      if (message.genderOverride) config.genderOverride = message.genderOverride;
      if (typeof message.volume === "number" && gainNode) {
        config.volume = message.volume;
        gainNode.gain.value = message.volume;
      }
      sendConfig();
      sendResponse({ ok: true });
    }
  })();
  return true;
});
