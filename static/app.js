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
  clips: document.querySelector("#view-clips"),
};

let tab = "mouse";
let winId = "";
let closeArmed = false;
let poll = 0;
let clipsTimer = 0;

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
  window.clearInterval(clipsTimer);
}

function showApp() {
  pinPanel.hidden = true;
  app.hidden = false;
  dock.hidden = false;
  refreshStatus();
  poll = window.setInterval(refreshStatus, 4000);
  syncClipboard();
  clipsTimer = window.setInterval(syncClipboard, 2500);
  connectPointer();
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

function clipTime(at) {
  if (!at) return "";
  return new Date(at * 1000).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
}

async function copyToPhone(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      say("Copiado al móvil");
      return;
    }
  } catch (_err) {
    /* la Wi-Fi es http y el móvil no deja el portapapeles seguro */
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.focus();
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  say(ok ? "Copiado al móvil" : "Mantén pulsado el texto para copiarlo");
}

function renderClips(items) {
  const list = document.querySelector("#clips");
  if (!list) return;
  list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "hint";
    empty.textContent = "Todavía no hay nada. Copia un texto en el PC.";
    list.append(empty);
    return;
  }
  for (const item of items) {
    const row = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "clip";
    const title = document.createElement("b");
    title.textContent = item.text;
    const when = document.createElement("small");
    when.textContent = clipTime(item.at);
    button.append(title, when);
    button.addEventListener("click", () => copyToPhone(item.text));
    row.append(button);
    list.append(row);
  }
}

function renderFiles(items) {
  const list = document.querySelector("#files");
  if (!list) return;
  list.replaceChildren();
  for (const item of items) {
    const row = document.createElement("li");
    row.className = "file-row";
    const link = document.createElement("a");
    link.href = "/api/files/" + item.id;
    link.download = item.name;
    const kb = item.size < 1024 ? item.size + " B" : Math.max(1, Math.round(item.size / 1024)) + " KB";
    link.textContent = item.name + " · " + kb;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Quitar";
    remove.addEventListener("click", async () => {
      await fetch("/api/files/" + item.id, { method: "DELETE" });
      syncClipboard();
    });
    row.append(link, remove);
    list.append(row);
  }
}

async function syncClipboard() {
  try {
    const res = await fetch("/api/clipboard");
    if (res.status === 401) return;
    const data = await res.json().catch(() => ({}));
    renderClips(data.items || []);
    const files = await fetch("/api/files");
    if (files.status === 401) return;
    const listed = await files.json().catch(() => ({}));
    renderFiles(listed.files || []);
  } catch (_err) {}
}

document.querySelector("#clip-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.querySelector("#clip-input");
  const text = input.value;
  if (!text.trim()) return;
  try {
    await api("/api/clipboard", { text });
    input.value = "";
    syncClipboard();
    say("Guardado en la mesa del PC");
  } catch (err) {
    say(err.message);
  }
});

document.querySelector("#file-input").addEventListener("change", async (event) => {
  const file = event.target.files && event.target.files[0];
  event.target.value = "";
  if (!file) return;
  try {
    const res = await fetch("/api/files", {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Filename": encodeURIComponent(file.name),
      },
      body: file,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "No se pudo enviar");
    say("Archivo en la mesa del PC");
    syncClipboard();
  } catch (err) {
    say(err.message);
  }
});

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
    if (tab === "clips") syncClipboard();
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
let acc = { x: 0, y: 0 };
let moveFlight = false;
let lastSample = 0;
let pointerSocket = null;

let raw = { x: 0, y: 0 };
let aimFrame = 0;

function gainFor(dx, dy) {
  const now = performance.now();
  const dt = Math.min(40, Math.max(8, lastSample ? now - lastSample : 16));
  lastSample = now;
  const speed = Math.hypot(dx, dy) / dt;
  const t = Math.min(1, Math.max(0, (speed - 0.05) / 1.15));
  const curve = t * t * (3 - 2 * t);
  return 1.2 + 2.8 * curve;
}

function queueMove(dx, dy) {
  raw.x += dx;
  raw.y += dy;
  if (!aimFrame) aimFrame = requestAnimationFrame(applyAim);
}

function applyAim() {
  aimFrame = 0;
  const dx = raw.x;
  const dy = raw.y;
  raw = { x: 0, y: 0 };
  if (!dx && !dy) return;
  const gain = gainFor(dx, dy);
  acc.x += dx * gain;
  acc.y += dy * gain;
  flushPointer();
}

function connectPointer() {
  if (pointerSocket && (pointerSocket.readyState === 0 || pointerSocket.readyState === 1)) return;
  const url = `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws`;
  const sock = new WebSocket(url);
  pointerSocket = sock;
  sock.binaryType = "arraybuffer";
  sock.onopen = () => flushPointer();
  sock.onclose = () => {
    if (pointerSocket === sock) pointerSocket = null;
  };
}

function flushPointer() {
  const dx = Math.trunc(acc.x);
  const dy = Math.trunc(acc.y);
  if (!dx && !dy) return;
  if (pointerSocket && pointerSocket.readyState === 1) {
    acc.x -= dx;
    acc.y -= dy;
    const view = new DataView(new ArrayBuffer(8));
    view.setInt32(0, dx, true);
    view.setInt32(4, dy, true);
    pointerSocket.send(view.buffer);
    return;
  }
  if (moveFlight) return;
  acc.x -= dx;
  acc.y -= dy;
  moveFlight = true;
  fetch("/api/move", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dx, dy }),
  })
    .then((res) => {
      if (res.status === 401) showPin();
      return res.text();
    })
    .catch(() => {})
    .finally(() => {
      moveFlight = false;
      flushPointer();
    });
}

function onPadMove(event) {
  event.preventDefault();
  const prev = pointers.get(event.pointerId);
  if (!prev) return;
  const samples = typeof event.getCoalescedEvents === "function" ? event.getCoalescedEvents() : [event];
  let x = prev.x;
  let y = prev.y;
  for (const sample of samples) {
    const dx = sample.clientX - x;
    const dy = sample.clientY - y;
    x = sample.clientX;
    y = sample.clientY;
    if (pointers.size >= 2 || gesture === "scroll") continue;
    travel += Math.hypot(dx, dy);
    if (travel > 6) gesture = "move";
    if (dx || dy) queueMove(dx, dy);
  }
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  const finger = document.querySelector("#finger");
  if (finger && pointers.size === 1) {
    const box = pad.getBoundingClientRect();
    finger.hidden = false;
    finger.style.left = `${event.clientX - box.left}px`;
    finger.style.top = `${event.clientY - box.top}px`;
  }
  if (pointers.size >= 2 || gesture === "scroll") {
    gesture = "scroll";
    const dy = event.clientY - prev.y;
    if (dy) api("/api/scroll", { dy }).catch((err) => say(err.message));
  }
}

pad.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  connectPointer();
  pad.setPointerCapture(event.pointerId);
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (pointers.size === 1) {
    gesture = "tap";
    travel = 0;
    lastSample = 0;
    window.clearInterval(poll);
  } else {
    gesture = "scroll";
  }
});

if ("onpointerrawupdate" in window) {
  pad.addEventListener("pointerrawupdate", onPadMove);
} else {
  pad.addEventListener("pointermove", onPadMove);
}

function endPointer(event) {
  pointers.delete(event.pointerId);
  if (pointers.size > 0) return;
  if (gesture === "tap") api("/api/click", { button: "left" }).catch((err) => say(err.message));
  gesture = "tap";
  travel = 0;
  const finger = document.querySelector("#finger");
  if (finger) finger.hidden = true;
  poll = window.setInterval(refreshStatus, 4000);
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
