const visor = document.querySelector("#visor");
const pinPanel = document.querySelector("#pin");
const app = document.querySelector("#app");
const dock = document.querySelector("#dock");
const sub = document.querySelector("#sub");

const views = {
  mouse: document.querySelector("#view-mouse"),
  keys: document.querySelector("#view-keys"),
  windows: document.querySelector("#view-windows"),
  youtube: document.querySelector("#view-youtube"),
  spotify: document.querySelector("#view-spotify"),
};

let tab = "mouse";
let winId = "";
let closeArmed = false;
let poll = 0;

function say(text) {
  visor.textContent = text || "Listo";
}

async function api(path, body, method = "POST") {
  const res = await fetch(path, {
    method,
    headers: method === "POST" ? { "Content-Type": "application/json" } : undefined,
    body: method === "POST" ? JSON.stringify(body || {}) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    showPin();
    throw new Error(data.error || "PIN");
  }
  if (!res.ok) throw new Error(data.error || "No se pudo");
  if (data.detail) say(data.detail);
  if (data.label) say(data.label);
  if (data.title) say(data.title);
  return data;
}

function showPin() {
  pinPanel.hidden = false;
  app.hidden = true;
  dock.hidden = true;
  window.clearInterval(poll);
}

function showApp() {
  pinPanel.hidden = true;
  app.hidden = false;
  dock.hidden = false;
  refreshStatus();
  poll = window.setInterval(refreshStatus, 4000);
}

async function refreshStatus() {
  try {
    const data = await api("/api/status", null, "GET");
    const names = { Windows: "Windows", Darwin: "Mac", Linux: "Linux" };
    sub.textContent = names[data.platform] || "Este PC";
    document.querySelectorAll("[data-cursor]").forEach((button) => {
      button.classList.toggle("on", button.dataset.cursor === data.cursor);
    });
    if (tab === "spotify" && data.spotify) {
      document.querySelector("#sp-title").textContent = data.spotify;
    }
  } catch (_err) {
    /* el visor ya muestra el fallo si hace falta */
  }
}

document.querySelector("#pin-go").addEventListener("click", login);

async function login() {
  const pin = document.querySelector("#pin-input").value.trim();
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      say(data.error || "PIN incorrecto");
      return;
    }
    say("Conectado a este PC");
    showApp();
  } catch (_err) {
    say("Sin respuesta del PC");
  }
}

const fromLink = new URLSearchParams(location.search).get("pin") || new URLSearchParams(location.hash.replace(/^#/, "")).get("pin") || "";
if (/^\d{6}$/.test(fromLink)) {
  document.querySelector("#pin-input").value = fromLink;
  history.replaceState(null, "", location.pathname);
  login();
}

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    tab = button.dataset.tab;
    document.querySelectorAll("[data-tab]").forEach((item) => {
      item.classList.toggle("on", item === button);
    });
    Object.entries(views).forEach(([name, view]) => {
      view.hidden = name !== tab;
    });
    if (tab === "windows") loadWindows();
    if (tab === "youtube") say("YouTube en el navegador del PC");
    if (tab === "spotify") refreshStatus();
  });
});

document.querySelectorAll("[data-cursor]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      const data = await api("/api/cursor", { mode: button.dataset.cursor });
      say(data.detail || data.label);
      document.querySelectorAll("[data-cursor]").forEach((item) => {
        item.classList.toggle("on", item === button);
      });
    } catch (err) {
      say(err.message);
    }
  });
});

const pad = document.querySelector("#pad");
const pointers = new Map();
let gesture = "tap";
let travel = 0;
let pending = { dx: 0, dy: 0 };
let frame = 0;

function flushMove() {
  frame = 0;
  const next = pending;
  pending = { dx: 0, dy: 0 };
  if (next.dx || next.dy) api("/api/move", next).catch((err) => say(err.message));
}

function queueMove(dx, dy) {
  pending.dx += dx;
  pending.dy += dy;
  if (!frame) frame = requestAnimationFrame(flushMove);
}

pad.addEventListener("pointerdown", (event) => {
  pad.setPointerCapture(event.pointerId);
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (pointers.size === 1) {
    gesture = "tap";
    travel = 0;
  } else {
    gesture = "scroll";
  }
});

pad.addEventListener("pointermove", (event) => {
  const prev = pointers.get(event.pointerId);
  if (!prev) return;
  const dx = event.clientX - prev.x;
  const dy = event.clientY - prev.y;
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (pointers.size >= 2 || gesture === "scroll") {
    gesture = "scroll";
    api("/api/scroll", { dy }).catch((err) => say(err.message));
    return;
  }
  travel += Math.hypot(dx, dy);
  if (travel > 7) gesture = "move";
  if (dx || dy) queueMove(dx, dy);
});

function endPointer(event) {
  pointers.delete(event.pointerId);
  if (pointers.size > 0) return;
  if (gesture === "tap") api("/api/click", { button: "left" }).catch((err) => say(err.message));
  gesture = "tap";
  travel = 0;
}

pad.addEventListener("pointerup", endPointer);
pad.addEventListener("pointercancel", endPointer);

const left = document.querySelector("#btn-left");
left.addEventListener("pointerdown", (event) => {
  event.currentTarget.setPointerCapture(event.pointerId);
  api("/api/down", { button: "left" }).catch((err) => say(err.message));
});
left.addEventListener("pointerup", () => {
  api("/api/up", { button: "left" }).catch((err) => say(err.message));
});
document.querySelector("#btn-right").addEventListener("click", () => {
  api("/api/click", { button: "right" }).catch((err) => say(err.message));
});

document.querySelector("#vol-down").addEventListener("click", () => {
  api("/api/volume", { delta: -1 }).catch((err) => say(err.message));
});
document.querySelector("#vol-up").addEventListener("click", () => {
  api("/api/volume", { delta: 1 }).catch((err) => say(err.message));
});
document.querySelector("#vol-mute").addEventListener("click", () => {
  api("/api/volume", { delta: 0 }).catch((err) => say(err.message));
});

const rows = [
  "1234567890",
  "qwertyuiop",
  "asdfghjklñ",
  "zxcvbnm,.-",
];
const shiftMap = {
  1: "!", 2: '"', 3: "·", 4: "$", 5: "%", 6: "&", 7: "/", 8: "(", 9: ")", 0: "=",
  ",": ";", ".": ":", "-": "_",
};
let shift = false;
const keys = document.querySelector("#keys");

function glyph(key) {
  if (!shift) return key;
  if (shiftMap[key]) return shiftMap[key];
  return key.toLocaleUpperCase("es");
}

function addKey(parent, label, onPress, className) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  if (className) button.className = className;
  button.addEventListener("click", onPress);
  parent.append(button);
  return button;
}

function sendKey(key) {
  api("/api/key", { key }).catch((err) => say(err.message));
  if (shift && key.length === 1) {
    shift = false;
    paintKeys();
  }
}

function paintKeys() {
  keys.replaceChildren();
  rows.forEach((row) => {
    const line = document.createElement("div");
    line.className = "keyrow";
    [...row].forEach((key) => {
      const shown = glyph(key);
      addKey(line, shown, () => sendKey(shown));
    });
    keys.append(line);
  });
  const special = document.createElement("div");
  special.className = "special";
  const mayus = addKey(special, "Aa", () => {
    shift = !shift;
    paintKeys();
  });
  if (shift) mayus.classList.add("primary");
  addKey(special, "espacio", () => sendKey(" "));
  addKey(special, "⌫", () => sendKey("Backspace"));
  addKey(special, "↵", () => sendKey("Enter"));
  keys.append(special);
  const arrows = document.createElement("div");
  arrows.className = "arrows";
  [["←", "ArrowLeft"], ["↑", "ArrowUp"], ["↓", "ArrowDown"], ["→", "ArrowRight"]].forEach(
    ([label, key]) => addKey(arrows, label, () => sendKey(key)),
  );
  keys.append(arrows);
}

paintKeys();

document.querySelector("#phrase").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.querySelector("#phrase-input");
  const text = input.value;
  if (!text) return;
  api("/api/text", { text })
    .then(() => {
      input.value = "";
      say("Texto enviado");
    })
    .catch((err) => say(err.message));
});

async function loadWindows() {
  const list = document.querySelector("#windows");
  const actions = document.querySelector("#win-actions");
  try {
    const data = await api("/api/windows", null, "GET");
    list.replaceChildren();
    winId = "";
    actions.hidden = true;
    data.windows.forEach((win) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = win.title;
      button.addEventListener("click", () => {
        winId = win.id;
        list.querySelectorAll("button").forEach((el) => el.classList.remove("picked"));
        button.classList.add("picked");
        actions.hidden = false;
        closeArmed = false;
        api("/api/window", { id: win.id, action: "focus" }).catch((err) => say(err.message));
      });
      item.append(button);
      list.append(item);
    });
    if (!data.windows.length) say("No veo ventanas");
  } catch (err) {
    say(err.message);
  }
}

document.querySelector("#win-refresh").addEventListener("click", loadWindows);

document.querySelectorAll("[data-win]").forEach((button) => {
  button.addEventListener("click", () => {
    if (!winId) return;
    const action = button.dataset.win;
    if (action === "close" && !closeArmed) {
      closeArmed = true;
      say("Toca Cerrar otra vez");
      window.setTimeout(() => {
        closeArmed = false;
      }, 2000);
      return;
    }
    closeArmed = false;
    api("/api/window", { id: winId, action }).catch((err) => say(err.message));
  });
});

document.querySelectorAll("[data-yt]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      const data = await api("/api/youtube", { action: button.dataset.yt });
      document.querySelector("#yt-title").textContent = data.title || "YouTube";
    } catch (err) {
      say(err.message);
    }
  });
});

document.querySelectorAll("[data-sp]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      const data = await api("/api/spotify", { action: button.dataset.sp });
      document.querySelector("#sp-title").textContent = data.title || "Spotify";
    } catch (err) {
      say(err.message);
    }
  });
});
