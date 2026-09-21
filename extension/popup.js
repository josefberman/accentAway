const healthUrl = "http://127.0.0.1:8765/health";

const $ = (id) => document.getElementById(id);

function setActive(group, value) {
  for (const btn of document.querySelectorAll(`[data-${group}]`)) {
    btn.classList.toggle("active", btn.dataset[group] === value);
  }
}

function render(state, health) {
  setActive("accent", state.accent || "us");
  setActive("gender", state.genderOverride || "auto");
  $("volume").value = String(state.volume ?? 1);

  const converting = Boolean(state.converting);
  $("toggle").textContent = converting ? "Stop" : "Start";
  $("toggle").classList.toggle("stop", converting);

  const connected = Boolean(health?.ok || state.backend?.connected);
  $("backend").textContent = connected ? "connected" : "offline";
  $("mode").textContent = health?.mode || state.backend?.mode || "—";
  $("device").textContent = health?.device || state.backend?.device || "—";

  const gender = state.gender || "unknown";
  $("gender").textContent = gender;
  $("latency").textContent =
    typeof state.latencyMs === "number" ? `${Math.round(state.latencyMs)} ms` : "—";

  const err = state.error;
  $("error").hidden = !err;
  $("error").textContent = err || "";
}

async function loadHealth() {
  try {
    const res = await fetch(healthUrl, { cache: "no-store" });
    if (!res.ok) {
      return null;
    }
    return await res.json();
  } catch {
    return null;
  }
}

async function refresh() {
  let state;
  try {
    state = await chrome.runtime.sendMessage({ type: "get-state" });
  } catch {
    state = { converting: false, error: "Extension worker unavailable" };
  }
  const health = await loadHealth();
  if (!health?.ok && !state.converting) {
    state.error = state.error || "Backend offline. Start backend/server.py.";
  }
  render(state, health);
}

for (const btn of document.querySelectorAll("[data-accent]")) {
  btn.addEventListener("click", async () => {
    await chrome.runtime.sendMessage({
      type: "update-config",
      accent: btn.dataset.accent,
    });
    refresh();
  });
}

for (const btn of document.querySelectorAll("[data-gender]")) {
  btn.addEventListener("click", async () => {
    await chrome.runtime.sendMessage({
      type: "update-config",
      genderOverride: btn.dataset.gender,
    });
    refresh();
  });
}

$("volume").addEventListener("input", async (event) => {
  await chrome.runtime.sendMessage({
    type: "update-config",
    volume: Number(event.target.value),
  });
});

$("toggle").addEventListener("click", async () => {
  const state = await chrome.runtime.sendMessage({ type: "get-state" });
  if (state.converting) {
    await chrome.runtime.sendMessage({ type: "stop" });
  } else {
    const health = await loadHealth();
    if (!health?.ok) {
      $("error").hidden = false;
      $("error").textContent = "Backend offline. Start backend/server.py.";
      return;
    }
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) {
      $("error").hidden = false;
      $("error").textContent = "No active tab to capture.";
      return;
    }
    const result = await chrome.runtime.sendMessage({
      type: "start",
      accent: state.accent,
      genderOverride: state.genderOverride,
      volume: state.volume,
      tabId: tab.id,
    });
    if (result && result.ok === false) {
      $("error").hidden = false;
      $("error").textContent = result.error || "Could not start capture";
    }
  }
  refresh();
});

refresh();
setInterval(refresh, 800);
