(function () {
  const ID = "accentaway-overlay";

  function ensure() {
    let el = document.getElementById(ID);
    if (el) {
      return el;
    }
    el = document.createElement("div");
    el.id = ID;
    el.style.cssText = [
      "position:fixed",
      "top:12px",
      "right:12px",
      "z-index:2147483647",
      "font:12px/1.4 ui-sans-serif,system-ui,sans-serif",
      "background:#0f172a",
      "color:#ecfdf5",
      "padding:6px 10px",
      "border-radius:999px",
      "box-shadow:0 4px 16px rgba(0,0,0,.35)",
      "pointer-events:none",
      "display:none",
    ].join(";");
    document.documentElement.appendChild(el);
    return el;
  }

  function render(msg) {
    const el = ensure();
    if (!msg.converting) {
      el.style.display = "none";
      return;
    }
    const accent = (msg.accent || "us").toUpperCase();
    const gender = msg.gender && msg.gender !== "unknown" ? msg.gender : "…";
    el.textContent = `AccentAway · ${accent} · ${gender}`;
    el.style.display = "block";
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "accentaway-overlay") {
      render(msg);
    }
  });

  chrome.storage.local.get(["converting", "accent", "gender"], (state) => {
    render(state);
  });
})();
