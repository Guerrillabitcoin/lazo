const visor = document.querySelector("#visor");
const pinPanel = document.querySelector("#pin");
const app = document.querySelector("#app");
const dock = document.querySelector("#dock");
const statusBar = document.querySelector("#status");
const linkLabel = document.querySelector("#link-label");

let wireKey = null;
let authKey = null;
let clockOffset = 0;
localStorage.removeItem("lazo-token");
const deviceId = localStorage.getItem("lazo-id") || (() => {
  const fresh = toHex(crypto.getRandomValues(new Uint8Array(16)));
  localStorage.setItem("lazo-id", fresh);
  return fresh;
})();

function setMasterKey(text) {
  const master = b64urlToBytes(text);
  wireKey = deriveKey(master, "lazo/seal/1");
  authKey = deriveKey(master, "lazo/auth/1");
}

function signHeaders(method, path, length) {
  if (!authKey) return {};
  const stamp = Math.round(Date.now() + clockOffset);
  const nonce = toHex(crypto.getRandomValues(new Uint8Array(16)));
  return {
    "X-Lazo-Id": deviceId,
    "X-Lazo-T": String(stamp),
    "X-Lazo-N": nonce,
    "X-Lazo-S": signRequest(authKey, method, path.split("?")[0], stamp, nonce, length),
  };
}

async function syncClock() {
  try {
    const before = Date.now();
    const data = await fetch("/api/time").then((res) => res.json());
    clockOffset = data.t - (before + Date.now()) / 2;
  } catch (_err) {}
}

function bodyLength(body) {
  if (!body) return 0;
  return typeof body === "string" ? new TextEncoder().encode(body).length : body.length ?? body.size ?? 0;
}

async function lzFetch(path, opts = {}) {
  const method = opts.method || "GET";
  const send = () => fetch(path, {
    ...opts,
    headers: { ...authHeaders(opts.headers), ...signHeaders(method, path, bodyLength(opts.body)) },
  });
  let res = await send();
  if (res.status === 401 && authKey) {
    await syncClock();
    res = await send();
  }
  return res;
}

const views = {
  mouse: document.querySelector("#view-mouse"),
  windows: document.querySelector("#view-windows"),
  youtube: document.querySelector("#view-youtube"),
  spotify: document.querySelector("#view-spotify"),
  bridge: document.querySelector("#view-bridge"),
  notes: document.querySelector("#view-notes"),
  system: document.querySelector("#view-system"),
  lab: document.querySelector("#view-lab"),
};

const TOOLS = [
  { id: "mouse", name: "Ratón" },
  { id: "bridge", name: "Puente Wi-Fi" },
  { id: "windows", name: "Ventanas" },
  { id: "youtube", name: "YouTube" },
  { id: "spotify", name: "Spotify" },
  { id: "notes", name: "Notas" },
  { id: "system", name: "Sistema" },
  { id: "lab", name: "Pruebas" },
];
const PINNED = ["mouse"];

let tab = "mouse";
let winId = "";
let poll = 0;
let clipsTimer = 0;
let caretTimer = 0;
let caretWas = false;

function say(text) {
  const clean = String(text || "Listo").replace(/\s+/g, " ").trim();
  visor.textContent = clean.length > 64 ? `${clean.slice(0, 63)}…` : clean;
}

function authHeaders(extra) {
  const headers = extra ? { ...extra } : {};
  headers["X-Lazo-Local"] = "1";
  if (wireKey) headers["X-Seal"] = "1";
  return headers;
}

async function readBody(res) {
  if (!wireKey || res.headers.get("content-type") === "application/json") {
    return res.json().catch(() => ({}));
  }
  const blob = new Uint8Array(await res.arrayBuffer());
  if (!blob.length) return {};
  try {
    return JSON.parse(openText(blob, wireKey) || "{}");
  } catch (_err) {
    return {};
  }
}

async function api(path, body, method = "POST") {
  const headers = method === "POST" ? { "Content-Type": "application/octet-stream" } : {};
  let payload;
  if (method === "POST") {
    const raw = JSON.stringify(body || {});
    payload = wireKey ? sealText(raw, wireKey) : raw;
    if (!wireKey) headers["Content-Type"] = "application/json";
  }
  const res = await lzFetch(path, { method, headers, body: payload });
  const data = await readBody(res);
  if (res.status === 401) {
    showPin();
    throw new Error(data.error || "PIN");
  }
  if (!res.ok) throw new Error(data.error || "No se pudo");
  if (data.detail) say(data.detail);
  else if (data.label) say(data.label);
  return data;
}

let missedPolls = 0;

function setLink(mode, text) {
  statusBar.dataset.link = mode;
  linkLabel.textContent = text || (mode === "on" ? (wireKey ? "Conectado · cifrado" : "Conectado") : "Sin conexión");
}

function showPin() {
  const input = document.querySelector("#pin-input");
  pinPanel.hidden = false;
  app.hidden = true;
  dock.hidden = true;
  setLink("off");
  window.clearInterval(poll);
  window.clearInterval(clipsTimer);
  window.clearInterval(caretTimer);
  fetch("/api/bye?i=" + deviceId, { method: "POST", headers: authHeaders() }).catch(() => {});
}

function showHome() {
  openCube("mouse");
}

function openCube(id) {
  tab = id;
  Object.entries(views).forEach(([name, view]) => {
    view.hidden = name !== id;
  });
  dock.querySelectorAll("button").forEach((button) => {
    button.classList.toggle("on", button.dataset.cube === id);
  });
  if (id === "windows") loadWindows();
  if (id === "system") loadSystem();
  if (id === "spotify") refreshStatus();
  if (id === "notes" || id === "bridge") syncClipboard();
}

function showApp() {
  pinPanel.hidden = true;
  app.hidden = false;
  dock.hidden = false;
  setLink("on");
  openCube("mouse");
  if (visor.textContent === "Conectando…") say("Listo");
  refreshStatus();
  poll = window.setInterval(refreshStatus, 4000);
  syncClipboard();
  clipsTimer = window.setInterval(syncClipboard, 2500);
  caretTimer = window.setInterval(watchCaret, 700);
  connectPointer();
  loadWindows();
  if (!localStorage.getItem("lazo-hint")) {
    localStorage.setItem("lazo-hint", "1");
    window.setTimeout(() => say("Mantén pulsada una pastilla y arrástrala para ordenar"), 900);
  }
}

async function refreshStatus() {
  try {
    const data = await api("/api/status", null, "GET");
    document.querySelectorAll("[data-cursor]").forEach((button) => {
      button.classList.toggle("on", button.dataset.cursor === data.cursor);
    });
    if (tab === "spotify" && data.spotify) {
      document.querySelector("#sp-title").textContent = data.spotify;
    }
    if (missedPolls >= 2) {
      setLink("on");
      say("LaZoo ha vuelto");
    }
    missedPolls = 0;
  } catch (_err) {
    if (pinPanel.hidden === false) return;
    missedPolls += 1;
    if (missedPolls === 2) {
      setLink("off", "LaZoo cerrado en el PC");
      say("LaZoo se ha cerrado en el PC");
    }
  }
}

function clipTime(at) {
  if (!at) return "";
  return new Date(at * 1000).toLocaleTimeString("es", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

async function copyToPhone(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      say("Nota copiada");
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
  say(ok ? "Nota copiada" : "Mantén pulsado el texto para copiarlo");
}

function renderClips(items) {
  const list = document.querySelector("#clips");
  if (!list) return;
  list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "hint";
    empty.textContent = "Sin notas";
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
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "copy";
    copy.textContent = "Copiar";
    copy.addEventListener("click", () => copyToPhone(item.text));
    row.className = "clip-row";
    row.append(button, copy);
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
    link.href = "#";
    link.addEventListener("click", async (event) => {
      event.preventDefault();
      try {
        const res = await lzFetch("/api/files/" + item.id);
        if (!res.ok) throw new Error("No se pudo bajar");
        const blob = new Uint8Array(await res.arrayBuffer());
        const plain = wireKey ? openSeal(blob, wireKey) : blob;
        const url = URL.createObjectURL(new Blob([plain]));
        const temp = document.createElement("a");
        temp.href = url;
        temp.download = item.name;
        temp.click();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
      } catch (err) {
        say(err.message);
      }
    });
    const kb = item.size < 1024 ? item.size + " B" : Math.max(1, Math.round(item.size / 1024)) + " KB";
    link.textContent = item.name + " · " + kb;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Quitar";
    remove.addEventListener("click", async () => {
      await lzFetch("/api/files/" + item.id, { method: "DELETE" });
      syncClipboard();
    });
    row.append(link, remove);
    list.append(row);
  }
}

async function syncClipboard() {
  try {
    const res = await lzFetch("/api/clipboard");
    if (res.status === 401) return;
    const data = await readBody(res);
    renderClips(data.items || []);
    const files = await lzFetch("/api/files");
    if (files.status === 401) return;
    const listed = await readBody(files);
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
    say("Nota guardada");
  } catch (err) {
    say(err.message);
  }
});

function formatSpeed(bytesPerSecond) {
  if (bytesPerSecond < 1024) return Math.max(0, Math.round(bytesPerSecond)) + " B/s";
  if (bytesPerSecond < 1024 * 1024) return (bytesPerSecond / 1024).toFixed(1) + " KB/s";
  return (bytesPerSecond / (1024 * 1024)).toFixed(1) + " MB/s";
}

function showXfer(loaded, total, pending) {
  const box = document.querySelector("#xfer");
  const bar = document.querySelector("#xfer-bar");
  const stat = document.querySelector("#xfer-stat");
  box.hidden = false;
  const ratio = total ? Math.min(1, loaded / total) : 0;
  bar.style.width = Math.round(ratio * 100) + "%";
  const seconds = (performance.now() - xferStarted) / 1000;
  const speed = seconds > 0.2 ? xferBytes / seconds : 0;
  stat.textContent = `${formatSpeed(speed)} · pendientes ${pending} · ${Math.round(ratio * 100)}%`;
}

function uploadTracked(url, body, headers, pending) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.responseType = "arraybuffer";
    const signed = { ...headers, ...signHeaders("POST", url, bodyLength(body)) };
    Object.entries(signed).forEach(([name, value]) => xhr.setRequestHeader(name, value));
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      xferBytes += Math.max(0, event.loaded - xferFileLoaded);
      xferFileLoaded = event.loaded;
      showXfer(event.loaded, event.total, pending);
    };
    xhr.onload = () => resolve(xhr);
    xhr.onerror = () => reject(new Error("Se cortó el envío"));
    xferFileLoaded = 0;
    xhr.send(body);
  });
}

async function sendBody(file) {
  const raw = new Uint8Array(await file.arrayBuffer());
  if (!wireKey) return { body: file, size: file.size, headers: {} };
  const sealed = sealBytes(raw, wireKey);
  return {
    body: sealed,
    size: raw.length,
    headers: { "X-Seal": "1", "X-Plain-Size": String(raw.length) },
  };
}
let xferStarted = 0;
let xferBytes = 0;
let xferFileLoaded = 0;

document.querySelector("#photo-input").addEventListener("change", (event) => sendPhotos(event.target));
document.querySelector("#photo-dir").addEventListener("change", (event) => sendPhotos(event.target));

const PHOTO_NAME = /\.(jpe?g|png|gif|webp|heic|heif|bmp|avif|mp4|mov|m4v|webm|3gp|mkv)$/i;

function isPhoto(file) {
  const type = file.type || "";
  return type.startsWith("image/") || type.startsWith("video/") || PHOTO_NAME.test(file.name);
}

async function sendPhotos(input) {
  const files = [...(input.files || [])].filter(isPhoto);
  input.value = "";
  const progress = document.querySelector("#photo-progress");
  if (!files.length) {
    progress.textContent = "No hay fotos ni vídeos";
    return;
  }
  xferStarted = performance.now();
  xferBytes = 0;
  let sent = 0;
  let skipped = 0;
  for (let index = 0; index < files.length; index += 1) {
    const file = files[index];
    const pending = files.length - index;
    progress.textContent = `${index + 1} de ${files.length} · ${file.name}`;
    try {
      const known = await api("/api/photos/check", { name: file.name, size: file.size });
      if (known.skip) {
        skipped += 1;
        continue;
      }
      const packed = await sendBody(file);
      const xhr = await uploadTracked("/api/photos", packed.body, authHeaders({
        "Content-Type": "application/octet-stream",
        "X-Filename": encodeURIComponent(file.name),
        ...packed.headers,
      }), pending - 1);
      const blob = new Uint8Array(xhr.response || []);
      let data = {};
      try {
        const text = blob[0] === 76 ? openText(blob, wireKey) : new TextDecoder().decode(blob);
        data = JSON.parse(text || "{}");
      } catch (_err) {
        data = {};
      }
      if (xhr.status === 401) {
        showPin();
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300) throw new Error(data.error || "No se pudo enviar");
      if (data.skipped) skipped += 1;
      else sent += 1;
    } catch (err) {
      progress.textContent = err.message;
      return;
    }
  }
  document.querySelector("#xfer").hidden = true;
  progress.textContent = `En el PC: ${sent} nuevas, ${skipped} ya estaban · pendientes 0`;
  say(progress.textContent);
}

document.querySelector("#file-input").addEventListener("change", async (event) => {
  const file = event.target.files && event.target.files[0];
  event.target.value = "";
  if (!file) return;
  xferStarted = performance.now();
  xferBytes = 0;
  try {
    const packed = await sendBody(file);
    const xhr = await uploadTracked("/api/files", packed.body, authHeaders({
      "Content-Type": "application/octet-stream",
      "X-Filename": encodeURIComponent(file.name),
      ...packed.headers,
    }), 0);
    const blob = new Uint8Array(xhr.response || []);
    let data = {};
    try {
      const text = blob[0] === 76 ? openText(blob, wireKey) : new TextDecoder().decode(blob);
      data = JSON.parse(text || "{}");
    } catch (_err) {
      data = {};
    }
    if (xhr.status === 401) {
      showPin();
      return;
    }
    if (xhr.status < 200 || xhr.status >= 300) throw new Error(data.error || "No se pudo enviar");
    document.querySelector("#xfer").hidden = true;
    say("Archivo en el puente del PC");
    syncClipboard();
  } catch (err) {
    say(err.message);
  }
});

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
      setLink("off");
      return;
    }
    setMasterKey(data.key);
    localStorage.setItem("lazo-key", data.key);
    await syncClock();
    say("Conectado y cifrado");
    showApp();
  } catch (_err) {
    say("Sin respuesta del PC");
    setLink("off");
  }
}

let order = loadOrder();

function loadOrder() {
  let saved = [];
  try {
    saved = JSON.parse(localStorage.getItem("lazo-order") || "[]");
  } catch (_err) {
    saved = [];
  }
  const known = TOOLS.map((tool) => tool.id);
  const RENAMED = { volume: "system" };
  if (!Array.isArray(saved)) saved = [];
  if (saved.some((id) => RENAMED[id])) {
    saved = saved.map((id) => RENAMED[id] || id).filter((id, i, all) => all.indexOf(id) === i);
    try {
      localStorage.setItem("lazo-order", JSON.stringify(saved));
    } catch (_err) {
      /* sin almacenamiento: vale el orden de esta visita */
    }
  }
  const rest = saved.filter((id) => known.includes(id) && !PINNED.includes(id));
  known.forEach((id) => {
    if (!PINNED.includes(id) && !rest.includes(id)) rest.push(id);
  });
  return [...PINNED, ...rest];
}

let reordering = false;
document.addEventListener(
  "touchmove",
  (ev) => {
    if (reordering && ev.cancelable) ev.preventDefault();
  },
  { passive: false },
);

function dragTool(button, pointerId, originX) {
  const scroller = button.parentElement;
  reordering = true;
  if (navigator.vibrate) navigator.vibrate(15);
  let lastX = originX;
  let dragged = false;
  button.classList.add("dragging");
  try {
    button.setPointerCapture(pointerId);
  } catch (_err) {
    reordering = false;
    button.classList.remove("dragging");
    return;
  }
  function move(ev) {
    if (ev.pointerId !== pointerId) return;
    ev.preventDefault();
    if (Math.abs(ev.clientX - originX) > 6) dragged = true;
    const right = ev.clientX >= lastX;
    lastX = ev.clientX;
    const edge = scroller.getBoundingClientRect();
    if (ev.clientX > edge.right - 28) scroller.scrollLeft += 16;
    if (ev.clientX < edge.left + 28) scroller.scrollLeft -= 16;
    const sibling = right ? button.nextElementSibling : button.previousElementSibling;
    if (!sibling) return;
    const box = sibling.getBoundingClientRect();
    if (right && ev.clientX > box.left + box.width * 0.5) scroller.insertBefore(sibling, button);
    else if (!right && ev.clientX < box.right - box.width * 0.5) scroller.insertBefore(button, sibling);
  }
  function stop(ev) {
    if (ev.pointerId !== pointerId) return;
    reordering = false;
    button.classList.remove("dragging");
    button.removeEventListener("pointermove", move);
    button.removeEventListener("pointerup", stop);
    button.removeEventListener("pointercancel", stop);
    if (!dragged) return;
    const fixed = dock.querySelector(".dock-fixed");
    order = [...fixed.querySelectorAll("button"), ...scroller.querySelectorAll("button")].map((item) => item.dataset.cube);
    localStorage.setItem("lazo-order", JSON.stringify(order));
    button.dataset.moved = "1";
  }
  button.addEventListener("pointermove", move);
  button.addEventListener("pointerup", stop);
  button.addEventListener("pointercancel", stop);
}

function armTool(event) {
  const button = event.currentTarget;
  const pointerId = event.pointerId;
  const startX = event.clientX;
  const startY = event.clientY;
  let timer = window.setTimeout(() => {
    timer = 0;
    dragTool(button, pointerId, startX);
  }, 350);
  function moved(ev) {
    if (!timer || ev.pointerId !== pointerId) return;
    if (Math.hypot(ev.clientX - startX, ev.clientY - startY) > 12) end();
  }
  function end(ev) {
    if (ev && ev.pointerId !== pointerId) return;
    if (timer) window.clearTimeout(timer);
    timer = 0;
    button.removeEventListener("pointermove", moved);
    button.removeEventListener("pointerup", end);
    button.removeEventListener("pointercancel", end);
  }
  button.addEventListener("pointermove", moved);
  button.addEventListener("pointerup", end);
  button.addEventListener("pointercancel", end);
}

function renderDock() {
  const fixed = document.createElement("div");
  const scroller = document.createElement("div");
  fixed.className = "dock-fixed";
  scroller.className = "dock-scroll";
  order.forEach((id) => {
    const tool = TOOLS.find((item) => item.id === id);
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.cube = id;
    button.classList.toggle("on", id === tab);
    const label = document.createElement("span");
    label.textContent = tool.name;
    button.append(label);
    button.addEventListener("click", () => {
      if (button.dataset.moved === "1") {
        button.dataset.moved = "";
        return;
      }
      openCube(id);
    });
    if (!PINNED.includes(id)) {
      button.addEventListener("pointerdown", armTool);
      button.addEventListener("contextmenu", (event) => event.preventDefault());
    }
    (PINNED.includes(id) ? fixed : scroller).append(button);
  });
  dock.replaceChildren(fixed, scroller);
}

window.addEventListener("pagehide", () => {
  if (navigator.sendBeacon) navigator.sendBeacon("/api/bye");
});

renderDock();

const hash = new URLSearchParams(location.hash.replace(/^#/, ""));
const fromQr = hash.get("k") || "";
const keyFromLink = fromQr || localStorage.getItem("lazo-key") || "";
if (fromQr) history.replaceState(null, "", location.pathname);
if (keyFromLink) {
  try {
    setMasterKey(keyFromLink);
    localStorage.setItem("lazo-key", keyFromLink);
  } catch (_err) {
    wireKey = null;
    authKey = null;
  }
}
if (authKey) {
  pinPanel.hidden = true;
  say("Conectando…");
  syncClock().then(() => lzFetch("/api/status")).then(async (res) => {
    const data = await readBody(res);
    if (res.status === 401 || !data.platform) {
      localStorage.removeItem("lazo-key");
      wireKey = null;
      authKey = null;
      say("Escanea el QR de nuevo");
      showPin();
      return;
    }
    showApp();
    say("Listo");
  }).catch(() => {
    say("Sin respuesta del PC");
    showPin();
  });
} else {
  say("Escanea el QR");
  showPin();
}

document.querySelector("#pin-go").addEventListener("click", login);

document.querySelectorAll("[data-cursor]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      const data = await api("/api/cursor", { mode: button.dataset.cursor });
      say(button.dataset.cursor === "large" ? "Cursor grande" : button.dataset.cursor === "huge" ? "Cursor enorme" : "Cursor normal");
      document.querySelectorAll("[data-cursor]").forEach((item) => {
        item.classList.toggle("on", item === button);
      });
    } catch (err) {
      say(err.message);
    }
  });
});

const pad = document.querySelector("#pad");
const trail = document.querySelector("#trail");
const trailCtx = trail.getContext("2d");
const crumbs = [];
let trailFrame = 0;

function fitTrail() {
  const box = pad.getBoundingClientRect();
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  trail.width = Math.max(1, Math.round(box.width * dpr));
  trail.height = Math.max(1, Math.round(box.height * dpr));
  trailCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function paintTrail() {
  const box = pad.getBoundingClientRect();
  trailCtx.clearRect(0, 0, box.width, box.height);
  for (const crumb of crumbs) {
    trailCtx.beginPath();
    trailCtx.fillStyle = `rgba(224,122,61,${crumb.a})`;
    trailCtx.arc(crumb.x, crumb.y, crumb.r, 0, Math.PI * 2);
    trailCtx.fill();
    crumb.a *= 0.86;
    crumb.r *= 0.96;
  }
  while (crumbs.length && crumbs[0].a < 0.04) crumbs.shift();
  if (crumbs.length) trailFrame = requestAnimationFrame(paintTrail);
  else trailFrame = 0;
}

function leaveCrumb(x, y) {
  crumbs.push({ x, y, r: 8, a: 0.55 });
  if (crumbs.length > 48) crumbs.shift();
  if (!trailFrame) trailFrame = requestAnimationFrame(paintTrail);
}

fitTrail();
window.addEventListener("resize", fitTrail);
const pointers = new Map();
let gesture = "tap";
let travel = 0;
let acc = { x: 0, y: 0 };
let moveFlight = false;
let lastSample = 0;
let pointerSocket = null;

let raw = { x: 0, y: 0 };
let aimFrame = 0;

let smoothSpeed = 0;

function gainFor(dx, dy) {
  const now = performance.now();
  const dt = Math.min(32, Math.max(8, lastSample ? now - lastSample : 16));
  lastSample = now;
  const speed = Math.hypot(dx, dy) / dt;
  smoothSpeed = smoothSpeed * 0.72 + speed * 0.28;
  const t = Math.min(1, Math.max(0, (smoothSpeed - 0.02) / 0.8));
  const curve = t * t * (3 - 2 * t);
  return 2.2 + 3.5 * curve;
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
  const query = new URLSearchParams(signHeaders("GET", "/ws", 0));
  const signed = query.has("X-Lazo-S")
    ? "?" + new URLSearchParams({ i: deviceId, t: query.get("X-Lazo-T"), n: query.get("X-Lazo-N"), s: query.get("X-Lazo-S") })
    : "";
  const url = `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws${signed}`;
  const sock = new WebSocket(url);
  pointerSocket = sock;
  sock.binaryType = "arraybuffer";
  sock.onopen = () => flushPointer();
  sock.onclose = () => {
    if (pointerSocket === sock) pointerSocket = null;
    window.setTimeout(refreshStatus, 600);
    window.setTimeout(refreshStatus, 2000);
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
    const frame = new Uint8Array(view.buffer);
    pointerSocket.send(wireKey ? sealBytes(frame, wireKey) : frame);
    return;
  }
  if (moveFlight) return;
  acc.x -= dx;
  acc.y -= dy;
  moveFlight = true;
  api("/api/move", { dx, dy })
    .catch(() => {})
    .finally(() => {
      moveFlight = false;
      flushPointer();
    });
}

let scrollAcc = 0;
let scrollFlight = false;
let scrollLive = false;

function flushScroll() {
  if (scrollFlight || !scrollLive) return;
  const dy = scrollAcc;
  scrollAcc = 0;
  if (!dy) return;
  scrollFlight = true;
  api("/api/scroll", { dy })
    .catch(() => {})
    .finally(() => {
      scrollFlight = false;
      if (scrollLive && scrollAcc) flushScroll();
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
    leaveCrumb(event.clientX - box.left, event.clientY - box.top);
  }
  if (pointers.size >= 2 || gesture === "scroll") {
    gesture = "scroll";
    scrollLive = true;
    const dy = event.clientY - prev.y;
    if (dy) {
      scrollAcc += dy;
      flushScroll();
    }
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
    scrollLive = true;
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
  scrollLive = false;
  scrollAcc = 0;
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

const nativeType = document.querySelector("#native-type");
let lastTyped = "";
const typeButton = document.querySelector("#btn-type");
typeButton.addEventListener("click", () => {
  const show = keys.hidden;
  keys.hidden = !show;
  typeButton.classList.toggle("on", show);
  if (show && !keys.childElementCount) paintKeys();
});
nativeType.addEventListener("blur", () => {
  caretWas = false;
});

async function watchCaret() {
  try {
    const res = await lzFetch("/api/caret");
    if (res.status === 401) return;
    const data = await readBody(res);
    const typing = !!data.typing;
    const write = document.querySelector("#caret-write");
    if (typing && !caretWas) {
      caretWas = true;
      lastTyped = "";
      nativeType.value = "";
      nativeType.focus();
      write.hidden = document.activeElement === nativeType;
    }
    if (!typing && caretWas) {
      caretWas = false;
      nativeType.blur();
      write.hidden = true;
    }
  } catch (_err) {}
}

document.querySelector("#caret-write").addEventListener("click", () => {
  lastTyped = "";
  nativeType.value = "";
  nativeType.focus();
  document.querySelector("#caret-write").hidden = true;
});
nativeType.addEventListener("input", () => {
  const value = nativeType.value;
  if (value.startsWith(lastTyped)) {
    const extra = value.slice(lastTyped.length);
    if (extra) api("/api/text", { text: extra }).catch((err) => say(err.message));
  } else if (lastTyped.startsWith(value)) {
    const removed = lastTyped.length - value.length;
    for (let i = 0; i < removed; i += 1) api("/api/key", { key: "Backspace" }).catch(() => {});
  } else if (value) {
    api("/api/text", { text: value }).catch((err) => say(err.message));
  }
  lastTyped = value;
});

document.querySelector("#vol-down").addEventListener("click", async () => {
  try {
    await api("/api/volume", { delta: -1 });
    say("Volumen bajado");
  } catch (err) {
    say(err.message);
  }
});
document.querySelector("#vol-up").addEventListener("click", async () => {
  try {
    await api("/api/volume", { delta: 1 });
    say("Volumen subido");
  } catch (err) {
    say(err.message);
  }
});
document.querySelector("#vol-mute").addEventListener("click", async () => {
  try {
    await api("/api/volume", { delta: 0 });
    say("Volumen muteado");
  } catch (err) {
    say(err.message);
  }
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

document.querySelector("#phrase") && document.querySelector("#phrase").addEventListener("submit", (event) => {
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

let screensInfo = null;

async function loadScreens() {
  const count = document.querySelector("#screen-count");
  try {
    screensInfo = await api("/api/screens", null, "GET");
  } catch (_err) {
    screensInfo = { count: 0, screens: [], can_move: false };
  }
  const n = screensInfo.count || 0;
  count.textContent = n ? `Pantallas: ${n}` : "Pantallas: ?";
  const box = document.querySelector("#screen-buttons");
  const note = document.querySelector("#screen-note");
  box.replaceChildren();
  if (screensInfo.can_move) {
    note.textContent = "Elige la pantalla de destino";
    screensInfo.screens.forEach((scr) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `Pantalla ${scr.n}${scr.primary ? " (principal)" : ""}`;
      button.addEventListener("click", () => {
        if (!winId) {
          say("Primero toca una ventana de la lista");
          return;
        }
        api("/api/screen", { id: winId, screen: scr.n }).then((data) => say(data.detail || `A la pantalla ${scr.n}`)).catch((err) => say(err.message));
      });
      box.append(button);
    });
  } else {
    note.textContent = n === 1 ? "Solo hay una pantalla conectada" : "Mover entre pantallas: no disponible en este sistema";
  }
  return screensInfo;
}

async function loadWindows() {
  const list = document.querySelector("#windows");
  loadScreens();
  try {
    const data = await api("/api/windows", null, "GET");
    list.replaceChildren();
    winId = "";
    data.windows.forEach((win) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "win-row";
      button.textContent = win.title;
      button.title = win.title;
      if (win.active) {
        button.classList.add("active");
        winId = win.id;
        button.classList.add("picked");
      }
      button.addEventListener("click", () => {
        winId = win.id;
        list.querySelectorAll("button").forEach((el) => el.classList.remove("picked"));
        button.classList.add("picked");
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

document.querySelector("#win-move-open").addEventListener("click", () => {
  const panel = document.querySelector("#win-move");
  panel.hidden = !panel.hidden;
});

document.querySelectorAll("[data-win]").forEach((button) => {
  button.addEventListener("click", () => {
    if (!winId) {
      say("Primero toca una ventana de la lista");
      return;
    }
    const action = button.dataset.win;
    const names = {
      focus: "Ventana al frente",
      toggle_max: "Maximizar / restaurar",
      snap_left: "Ventana a la izquierda",
      snap_right: "Ventana a la derecha",
      close: "Ventana cerrada",
    };
    api("/api/window", { id: winId, action })
      .then((data) => {
        say((data && data.detail) || names[action] || "Ventana");
        if (action === "close") window.setTimeout(loadWindows, 600);
      })
      .catch((err) => say(err.message));
  });
});

async function loadSystem() {
  let caps = screensInfo;
  try {
    caps = await api("/api/screens", null, "GET");
  } catch (_err) {
    return;
  }
  const bright = !!caps.brightness;
  document.querySelector("#bright-row").hidden = !bright;
  document.querySelector("#bright-na").hidden = bright;
  document.querySelector("#sys-project").hidden = !caps.project;
  document.querySelector("#sys-lock").hidden = !caps.lock;
  const na = document.querySelector("#sys-na");
  const missing = [];
  if (!caps.project) missing.push("Cambiar pantalla");
  if (!caps.lock) missing.push("Bloquear");
  na.hidden = !missing.length;
  na.textContent = `${missing.join(" y ")}: no disponible en este sistema`;
}

document.querySelectorAll("[data-sys]").forEach((button) => {
  button.addEventListener("click", () => {
    const action = button.dataset.sys;
    if (action === "lock" && !window.confirm("¿Bloquear el PC?")) return;
    api("/api/system", { action }).then((data) => say(data.detail || "Hecho")).catch((err) => say(err.message));
  });
});

document.querySelectorAll("[data-yt]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      const data = await api("/api/youtube", { action: button.dataset.yt });
      if (data.title) document.querySelector("#yt-title").textContent = data.title;
      if (typeof data.level === "number") setLevel("yt", data.level);
      if (button.dataset.yt === "play") {
        const started = button.textContent === "Play";
        flipPlay(button);
        say(started ? "YouTube en play" : "YouTube en pausa");
      } else if (button.dataset.yt === "mute") {
        button.classList.toggle("muted");
        say(button.classList.contains("muted") ? "YouTube silencio" : "YouTube con sonido");
      } else {
        const names = {
          prev: "YouTube anterior",
          next: "YouTube siguiente",
          back: "YouTube −10 s",
          forward: "YouTube +10 s",
          home: "YouTube inicio",
          full: "YouTube pantalla",
          theater: "YouTube cine",
          captions: "YouTube subtítulos",
        };
        say(names[button.dataset.yt] || "YouTube");
      }
    } catch (err) {
      say(err.message);
    }
  });
});

document.querySelectorAll("[data-sp]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      const data = await api("/api/spotify", { action: button.dataset.sp });
      if (data.title) document.querySelector("#sp-title").textContent = data.title;
      if (typeof data.level === "number") setLevel("sp", data.level);
      if (button.dataset.sp === "play") {
        const started = button.textContent === "Play";
        flipPlay(button);
        say(started ? "Spotify en play" : "Spotify en pausa");
      } else if (button.dataset.sp === "mute") {
        button.classList.toggle("muted");
        say(button.classList.contains("muted") ? "Spotify silencio" : "Spotify con sonido");
      } else {
        const names = { prev: "Spotify anterior", next: "Spotify siguiente" };
        say(names[button.dataset.sp] || "Spotify");
      }
    } catch (err) {
      say(err.message);
    }
  });
});

function flipPlay(button) {
  const pausing = button.textContent === "Play";
  button.textContent = pausing ? "Pausa" : "Play";
}

function setLevel(prefix, level) {
  document.querySelector(`#${prefix}-vol`).value = String(level);
  document.querySelector(`#${prefix}-level`).textContent = String(level);
}

document.querySelector("#yt-vol").addEventListener("change", async (event) => {
  try {
    const data = await api("/api/youtube", { action: "volume", level: Number(event.target.value) });
    if (typeof data.level === "number") setLevel("yt", data.level);
    say(`Volumen YouTube ${data.level ?? event.target.value}`);
  } catch (err) {
    say(err.message);
  }
});

const YT_SPEEDS = [1, 1.25, 1.5, 2];
const YT_SPEED_LABELS = ["1.0", "1.25", "1.50", "2"];

function showSpeed(rate) {
  const index = YT_SPEEDS.findIndex((item) => Math.abs(item - Number(rate)) < 0.001);
  const picked = index < 0 ? 0 : index;
  document.querySelector("#yt-speed").value = String(picked);
  document.querySelector("#yt-speed-label").textContent = YT_SPEED_LABELS[picked];
}

document.querySelector("#yt-speed").addEventListener("input", (event) => {
  document.querySelector("#yt-speed-label").textContent = YT_SPEED_LABELS[Number(event.target.value)] || "1.0";
});

document.querySelector("#yt-speed").addEventListener("change", async (event) => {
  const rate = YT_SPEEDS[Number(event.target.value)];
  try {
    const data = await api("/api/youtube", { action: "speed", rate });
    if (typeof data.rate === "number") showSpeed(data.rate);
    say(`Velocidad YouTube ${YT_SPEED_LABELS[Number(event.target.value)] || "1.0"}`);
  } catch (err) {
    say(err.message);
  }
});

document.querySelector("#sp-vol").addEventListener("change", async (event) => {
  try {
    const data = await api("/api/spotify", { action: "volume", level: Number(event.target.value) });
    if (typeof data.level === "number") setLevel("sp", data.level);
    if (data.title) document.querySelector("#sp-title").textContent = data.title;
    say(`Volumen Spotify ${data.level ?? event.target.value}`);
  } catch (err) {
    say(err.message);
  }
});

document.querySelector("#yt-search").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = document.querySelector("#yt-q").value.trim();
  if (!query) return;
  try {
    const data = await api("/api/youtube", { action: "search", query });
    const list = document.querySelector("#yt-results");
    list.replaceChildren();
    for (const item of data.results || []) {
      const row = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = item.title;
      button.addEventListener("click", () => {
        api("/api/youtube", { action: "open", video: item.id }).then(() => say(`YouTube «${item.title}»`)).catch((err) => say(err.message));
      });
      row.append(button);
      list.append(row);
    }
    say(`Búsqueda YouTube «${query}»`);
  } catch (err) {
    say(err.message);
  }
});

document.querySelector("#sp-search").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = document.querySelector("#sp-q").value.trim();
  if (!query) return;
  try {
    const data = await api("/api/spotify", { action: "search", query });
    if (data.title) document.querySelector("#sp-title").textContent = data.title;
    say(`Búsqueda Spotify «${query}»`);
  } catch (err) {
    say(err.message);
  }
});

let labTracks = [];

function renderLab(tracks) {
  labTracks = tracks || [];
  const list = document.querySelector("#lab-tracks");
  list.replaceChildren();
  if (!labTracks.length) return;
  labTracks.forEach((title, index) => {
    const row = document.createElement("li");
    row.className = "clip-row";
    const name = document.createElement("button");
    name.type = "button";
    name.className = "clip";
    name.textContent = title;
    const up = document.createElement("button");
    up.type = "button";
    up.className = "copy";
    up.textContent = "Subir";
    up.addEventListener("click", () => moveLab(index, -1));
    const down = document.createElement("button");
    down.type = "button";
    down.className = "copy";
    down.textContent = "Bajar";
    down.addEventListener("click", () => moveLab(index, 1));
    row.append(name, up, down);
    list.append(row);
  });
}

async function moveLab(index, dir) {
  try {
    const data = await api("/api/spotify", { action: "queue_move", index, dir });
    renderLab(data.tracks || []);
    say(data.detail || "Orden de prueba");
  } catch (err) {
    say(err.message);
  }
}

document.querySelector("#lab-like").addEventListener("click", async () => {
  try {
    await api("/api/spotify", { action: "like" });
    say("Spotify me gusta");
  } catch (err) {
    say(err.message);
  }
});

document.querySelector("#lab-queue").addEventListener("click", async () => {
  try {
    const data = await api("/api/spotify", { action: "queue" });
    renderLab(data.tracks || []);
    say(data.tracks && data.tracks.length ? "Próximas de Spotify" : "Spotify no publica las próximas");
  } catch (err) {
    say(err.message);
  }
});

document.querySelector("#lab-add").addEventListener("click", async () => {
  try {
    const data = await api("/api/spotify", { action: "queue_add" });
    renderLab(data.tracks || []);
    say(data.detail || "Sumada a la cola de prueba");
  } catch (err) {
    say(err.message);
  }
});

document.querySelector("#lab-lock").addEventListener("click", async () => {
  try {
    await api("/api/lab", { action: "lock" });
    say("Windows bloqueado");
  } catch (err) {
    say(err.message);
  }
});

document.querySelector("#lab-screen").addEventListener("click", async () => {
  try {
    await api("/api/lab", { action: "screen" });
    say("Pantalla apagada");
  } catch (err) {
    say(err.message);
  }
});

document.querySelector("#view-lab").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-lab]");
  if (!button) return;
  try {
    const data = await api("/api/lab", { action: button.dataset.lab });
    say(data.detail || "Prueba");
  } catch (err) {
    say(err.message);
  }
});

document.querySelector("#lab-open").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = document.querySelector("#lab-url").value.trim();
  if (!url) return;
  try {
    await api("/api/lab", { action: "open", url });
    say(`Abrir «${url}»`);
  } catch (err) {
    say(err.message);
  }
});
