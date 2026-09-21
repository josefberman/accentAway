const DEFAULTS = {
  accent: "us",
  genderOverride: "auto",
  volume: 1,
  wsUrl: "ws://127.0.0.1:8765/convert",
  healthUrl: "http://127.0.0.1:8765/health",
};

let converting = false;
let capturedTabId = null;

async function getState() {
  const stored = await chrome.storage.local.get([
    "accent",
    "genderOverride",
    "volume",
    "wsUrl",
    "converting",
    "gender",
    "latencyMs",
    "backend",
    "error",
  ]);
  converting = converting || (await hasOffscreen());
  return { ...DEFAULTS, ...stored, converting };
}

async function setState(patch) {
  await chrome.storage.local.set(patch);
  if (capturedTabId != null) {
    try {
      await chrome.tabs.sendMessage(capturedTabId, {
        type: "accentaway-overlay",
        ...patch,
        converting,
      });
    } catch {
      /* tab has no content script */
    }
  }
}

async function hasOffscreen() {
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
  });
  return contexts.length > 0;
}

async function ensureOffscreen() {
  if (await hasOffscreen()) {
    return;
  }
  await chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["USER_MEDIA", "AUDIO_PLAYBACK"],
    justification: "Capture tab audio and play converted speech",
  });
}

async function closeOffscreen() {
  if (await hasOffscreen()) {
    await chrome.offscreen.closeDocument();
  }
}

async function startConversion(tabId, options = {}) {
  if (converting) {
    await stopConversion();
  }
  const state = await getState();
  const accent = options.accent || state.accent;
  const genderOverride = options.genderOverride || state.genderOverride;
  const volume = options.volume ?? state.volume;

  await ensureOffscreen();
  const streamId = options.streamId;
  if (!streamId) {
    throw new Error("Missing tab capture stream id");
  }

  converting = true;
  capturedTabId = tabId;
  await setState({
    converting: true,
    error: "",
    gender: "unknown",
    latencyMs: null,
    accent,
    genderOverride,
    volume,
  });

  await chrome.runtime.sendMessage({
    type: "offscreen-start",
    streamId,
    wsUrl: state.wsUrl,
    accent,
    genderOverride,
    volume,
  });
}

async function stopConversion() {
  converting = false;
  const tabId = capturedTabId;
  capturedTabId = null;
  try {
    await chrome.runtime.sendMessage({ type: "offscreen-stop" });
  } catch {
    /* offscreen already gone */
  }
  await closeOffscreen();
  await setState({ converting: false, gender: "unknown", latencyMs: null, error: "" });
  if (tabId != null) {
    try {
      await chrome.tabs.sendMessage(tabId, {
        type: "accentaway-overlay",
        converting: false,
      });
    } catch {
      /* ignore */
    }
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    switch (message.type) {
      case "get-state": {
        sendResponse(await getState());
        return;
      }
      case "start": {
        const tabId = message.tabId;
        if (!tabId) {
          throw new Error("No tab id");
        }
        const streamId = await chrome.tabCapture.getMediaStreamId({
          targetTabId: tabId,
        });
        await startConversion(tabId, { ...message, streamId });
        sendResponse({ ok: true });
        return;
      }
      case "stop": {
        await stopConversion();
        sendResponse({ ok: true });
        return;
      }
      case "update-config": {
        const patch = {};
        if (message.accent) patch.accent = message.accent;
        if (message.genderOverride) patch.genderOverride = message.genderOverride;
        if (typeof message.volume === "number") patch.volume = message.volume;
        await setState(patch);
        if (converting) {
          await chrome.runtime.sendMessage({
            type: "offscreen-config",
            ...patch,
          });
        }
        sendResponse({ ok: true });
        return;
      }
      case "status": {
        await setState({
          gender: message.gender ?? undefined,
          latencyMs: message.latencyMs ?? undefined,
          backend: message.backend ?? undefined,
          error: message.error ?? "",
        });
        sendResponse({ ok: true });
        return;
      }
      case "offscreen-error": {
        converting = false;
        await setState({ converting: false, error: message.error || "Capture failed" });
        await closeOffscreen();
        sendResponse({ ok: true });
        return;
      }
      default:
        sendResponse({ ok: false });
    }
  })().catch(async (err) => {
    converting = false;
    await setState({ converting: false, error: String(err.message || err) });
    sendResponse({ ok: false, error: String(err.message || err) });
  });
  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === capturedTabId) {
    stopConversion();
  }
});

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.storage.local.set({
    accent: "us",
    genderOverride: "auto",
    volume: 1,
  });
});
