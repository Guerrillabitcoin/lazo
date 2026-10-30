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
  dl: document.querySelector("#view-dl"),
  lab: document.querySelector("#view-lab"),
  about: document.querySelector("#view-about"),
};

const TOOLS = [
  { id: "mouse", name: "Ratón" },
  { id: "bridge", name: "Puente Wi-Fi" },
  { id: "windows", name: "Ventanas" },
  { id: "youtube", name: "YouTube" },
  { id: "spotify", name: "Spotify" },
  { id: "notes", name: "Notas" },
  { id: "system", name: "Sistema" },
  { id: "dl", name: "Descargatodo" },
  { id: "lab", name: "Pruebas" },
  { id: "about", name: "Sobre LaZoo" },
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
  const stop = new AbortController();
  const timer = window.setTimeout(() => stop.abort(), 25000);
  let res;
  try {
    res = await lzFetch(path, { method, headers, body: payload, signal: stop.signal });
  } catch (err) {
    if (err && err.name === "AbortError") throw new Error("El PC tarda demasiado en contestar");
    throw new Error("Sin conexión con el PC. ¿Sigue LaZoo abierto y en la misma Wi-Fi?");
  } finally {
    window.clearTimeout(timer);
  }
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
  if (id === "about") aboutOpen();
  mediaWatch(id === "youtube" || id === "spotify");
  if (id === "dl") dlOpen();
  else dlStop();
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
  if (document.hidden) return;
  try {
    const data = await api("/api/status", null, "GET");
    document.querySelectorAll("[data-cursor]").forEach((button) => {
      button.classList.toggle("on", button.dataset.cursor === data.cursor);
    });
    if (tab === "spotify" && data.spotify) setMediaTitle("sp", data.spotify);
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
  const d = new Date(at * 1000);
  const two = (n) => String(n).padStart(2, "0");
  return `${two(d.getDate())}/${two(d.getMonth() + 1)}/${two(d.getFullYear() % 100)} · ${two(d.getHours())}:${two(d.getMinutes())}`;
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

let clipsShown = "";

function renderClips(items) {
  const sig = JSON.stringify(items);
  if (sig === clipsShown) return;
  clipsShown = sig;
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
    copy.className = "copy copy-pill";
    copy.textContent = "Copiar";
    copy.addEventListener("click", () => copyToPhone(item.text));
    row.className = "clip-row";
    row.append(button, copy);
    list.append(row);
  }
}

let filesShown = "";

function renderFiles(items) {
  const list = document.querySelector("#files");
  if (!list) return;
  const sig = JSON.stringify(items);
  if (sig === filesShown && list.childElementCount) return;
  if (list.querySelector("[data-busy]")) return;
  filesShown = sig;
  list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "hint";
    empty.textContent = "Nada todavía. Desde el PC, abre el puente y suelta archivos.";
    list.append(empty);
  }
  for (const item of items) {
    const row = document.createElement("li");
    row.className = "file-row";
    const link = document.createElement("a");
    link.href = "#";
    link.addEventListener("click", async (event) => {
      event.preventDefault();
      if (link.dataset.busy) return;
      link.dataset.busy = "1";
      try {
        await receiveChunked("nube", item.id, item.name, (got, size) => {
          link.textContent = `${item.name} · ${Math.round((got / Math.max(1, size)) * 100)}%`;
        });
        say("Guardado en el móvil");
      } catch (err) {
        say(err.message);
      } finally {
        delete link.dataset.busy;
        link.textContent = item.name + " · " + formatSize(item.size);
      }
    });
    link.textContent = item.name + " · " + formatSize(item.size);
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
  if (document.hidden || (tab !== "notes" && tab !== "bridge")) return;
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
  if (bytesPerSecond < 1024 * 1024) return (bytesPerSecond / 1024).toFixed(1).replace(".", ",") + " KB/s";
  return (bytesPerSecond / (1024 * 1024)).toFixed(1).replace(".", ",") + " MB/s";
}

function formatSize(bytes) {
  if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2).replace(".", ",") + " GB";
  if (bytes >= 1048576) return (bytes / 1048576).toFixed(1).replace(".", ",") + " MB";
  if (bytes >= 1024) return Math.round(bytes / 1024) + " KB";
  return bytes + " B";
}

/* --- Puente por trozos ---------------------------------------------------
   Cada archivo va en trozos de 4 MB leídos con File.slice(): sellados (LZ2), firmados y con
   índice en la ruta. Si un trozo falla se reintenta; si el PC ya tenía trozos (corte, PC
   reiniciado), se sigue desde ahí. Al final el PC comprueba el SHA-256 de todo el archivo. */
const XFER_PARALLEL = 2;
const XFER_RETRIES = 8;
const xferJobs = [];
let xferSeq = 0;
let cryptoWorker = null;
let cryptoBroken = false;
const cryptoWaits = new Map();
const localHashes = new Map();

function cryptoCall(msg, transfer) {
  if (!cryptoWorker && !cryptoBroken) {
    try {
      cryptoWorker = new Worker("/puente-worker.js?v=0.41");
      cryptoWorker.onmessage = (event) => {
        const wait = cryptoWaits.get(event.data.seq);
        if (!wait) return;
        cryptoWaits.delete(event.data.seq);
        if (event.data.error) wait.reject(new Error(event.data.error));
        else wait.resolve(event.data);
      };
      cryptoWorker.onerror = () => {
        cryptoBroken = true;
        cryptoWorker = null;
        cryptoWaits.forEach((wait) => wait.reject(new Error("worker")));
        cryptoWaits.clear();
      };
    } catch (_err) {
      cryptoBroken = true;
    }
  }
  if (cryptoBroken || !cryptoWorker) return Promise.resolve(cryptoLocal(msg));
  xferSeq += 1;
  const seq = xferSeq;
  return new Promise((resolve, reject) => {
    cryptoWaits.set(seq, { resolve, reject });
    cryptoWorker.postMessage({ ...msg, seq }, transfer || []);
  });
}

function cryptoLocal(msg) {
  const { op, tid, buf, key } = msg;
  if (!localHashes.has(tid)) localHashes.set(tid, new Sha256());
  const hash = localHashes.get(tid);
  if (op === "seal") {
    const plain = new Uint8Array(buf);
    hash.update(plain);
    return { buf: (key ? sealBytes(plain, key) : plain).buffer };
  }
  if (op === "hash") {
    hash.update(new Uint8Array(buf));
    return {};
  }
  if (op === "open") {
    const plain = key ? openSeal(new Uint8Array(buf), key) : new Uint8Array(buf);
    hash.update(plain);
    return { buf: plain.buffer };
  }
  localHashes.delete(tid);
  return op === "digest" ? { hex: toHex(hash.digest()) } : {};
}

const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

function xferStop(job) {
  if (job.cancelled) throw new Error("Cancelado");
}

function postChunk(job, url, body) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    job.xhr = xhr;
    xhr.open("POST", url);
    xhr.responseType = "arraybuffer";
    xhr.timeout = 120000;
    const headers = { ...authHeaders({ "Content-Type": "application/octet-stream" }), ...signHeaders("POST", url, body.length) };
    Object.entries(headers).forEach(([name, value]) => xhr.setRequestHeader(name, value));
    xhr.upload.onprogress = (event) => {
      job.inFlight = event.loaded;
      paintXfers();
    };
    const fail = (text) => {
      const err = new Error(text);
      err.retry = true;
      reject(err);
    };
    xhr.onload = () => {
      job.xhr = null;
      job.inFlight = 0;
      const blob = new Uint8Array(xhr.response || []);
      let data = {};
      try {
        const text = blob[0] === 76 && wireKey ? openText(blob, wireKey) : new TextDecoder().decode(blob);
        data = JSON.parse(text || "{}");
      } catch (_err) {}
      if (xhr.status === 200) resolve(data);
      else if (xhr.status === 401) {
        const err = new Error(data.error || "Entra con el QR");
        err.auth = true;
        err.retry = true;
        reject(err);
      } else if (xhr.status >= 500 || xhr.status === 0) fail(data.error || "El PC no contestó");
      else reject(new Error(data.error || "No se pudo enviar"));
    };
    xhr.onerror = () => fail("Se cortó la red");
    xhr.ontimeout = () => fail("La red va muy lenta");
    xhr.onabort = () => reject(new Error("Cancelado"));
    xhr.send(body);
  });
}

async function withRetry(job, label, fn) {
  for (let attempt = 1; ; attempt += 1) {
    xferStop(job);
    try {
      return await fn();
    } catch (err) {
      xferStop(job);
      if (!err.retry || attempt >= XFER_RETRIES) throw err;
      if (err.auth) await syncClock();
      const wait = Math.min(15000, 800 * 2 ** (attempt - 1));
      job.state = `${err.message}. Reintento ${attempt} de ${XFER_RETRIES - 1}…`;
      paintXfers();
      await sleep(wait);
    }
  }
}

async function apiRetry(job, path, body) {
  return withRetry(job, path, async () => {
    try {
      return await api(path, body);
    } catch (err) {
      if (/Sin conexión|tarda demasiado/.test(err.message)) err.retry = true;
      throw err;
    }
  });
}

// Carpeta relativa de un archivo elegido con «Carpeta» (webkitdirectory): «Viaje/fotos/a.jpg» -> «Viaje/fotos».
// El PC la vuelve a sanear (sin «..», sin raíz).
function relDir(file) {
  const rel = String(file.webkitRelativePath || "");
  if (!rel.includes("/")) return "";
  return rel
    .split("/")
    .slice(0, -1)
    .filter((p) => p && p !== "." && p !== "..")
    .join("/");
}

async function sendFile(job) {
  const file = job.file;
  const start = await apiRetry(job, "/api/up/start", {
    name: file.name,
    dir: relDir(file),
    size: file.size,
    key: `${file.webkitRelativePath || file.name}|${file.size}|${file.lastModified || 0}`,
  });
  if (start.skip) {
    job.state = "Ya estaba en el PC";
    job.done = file.size;
    job.status = "skip";
    return;
  }
  job.upId = start.id;
  const have = new Set(start.have || []);
  if (have.size) job.state = `Retomo: ya había ${have.size} de ${start.total} trozos`;
  const tid = "up-" + start.id + "-" + job.n;
  try {
    // Mientras sube un trozo, el worker ya prepara (lee, resume y cifra) el siguiente.
    const prepare = async (index) => {
      const from = index * start.chunk;
      const buf = await file.slice(from, Math.min(file.size, from + start.chunk)).arrayBuffer();
      if (have.has(index)) {
        await cryptoCall({ op: "hash", tid, buf }, [buf]);
        return null;
      }
      return new Uint8Array((await cryptoCall({ op: "seal", tid, buf, key: wireKey }, [buf])).buf);
    };
    let next = start.total ? prepare(0) : null;
    for (let index = 0; index < start.total; index += 1) {
      xferStop(job);
      const sealed = await next;
      next = index + 1 < start.total ? prepare(index + 1) : null;
      if (next) next.catch(() => {});
      if (sealed) {
        await withRetry(job, "trozo", () => postChunk(job, `/api/up/${start.id}/${index}`, sealed));
        if (!job.state.startsWith("Retomo")) job.state = "";
      }
      job.done = Math.min(file.size, (index + 1) * start.chunk);
      job.inFlight = 0;
      paintXfers();
    }
    if (next) await next;
    const { hex } = await cryptoCall({ op: "digest", tid });
    job.state = "Comprobando…";
    paintXfers();
    const end = await apiRetry(job, `/api/up/${start.id}/done`, { sha256: hex });
    job.status = "ok";
    job.state = end.name && end.name !== file.name ? `En el PC como «${end.name}» ✓` : "En el PC ✓";
  } catch (err) {
    cryptoCall({ op: "drop", tid }).catch(() => {});
    throw err;
  }
}

async function xferWorker() {
  for (;;) {
    const job = xferJobs.find((item) => item.status === "wait");
    if (!job) return;
    job.status = "run";
    job.started = performance.now();
    paintXfers();
    try {
      await sendFile(job);
    } catch (err) {
      job.status = job.cancelled ? "cancel" : "error";
      job.state = job.cancelled ? "Cancelado" : err.message;
      if (job.upId && job.cancelled) api(`/api/up/${job.upId}/cancel`, {}).catch(() => {});
      if (err.auth) job.state = "El PC se reinició: vuelve a escanear el QR y elige el archivo otra vez; seguirá donde se quedó";
    }
    paintXfers();
  }
}

let xferRunners = 0;

function queueFiles(input) {
  const files = [...(input.files || [])];
  input.value = "";
  if (!files.length) return;
  xferJobs.splice(0, xferJobs.length, ...xferJobs.filter((job) => job.status === "wait" || job.status === "run"));
  for (const file of files) {
    xferJobs.push({ n: xferJobs.length + Math.random(), file, status: "wait", state: "", done: 0, inFlight: 0, cancelled: false });
  }
  xferStarted = xferStarted && xferJobs.some((job) => job.status === "run") ? xferStarted : performance.now();
  paintXfers(true);
  while (xferRunners < XFER_PARALLEL) {
    xferRunners += 1;
    xferWorker().finally(() => {
      xferRunners -= 1;
      paintXfers(true);
      if (!xferRunners) finishXfers();
    });
  }
}

function finishXfers() {
  const ok = xferJobs.filter((job) => job.status === "ok").length;
  const skip = xferJobs.filter((job) => job.status === "skip").length;
  const bad = xferJobs.filter((job) => job.status === "error").length;
  const text = `En el PC: ${ok} nuevos, ${skip} ya estaban${bad ? `, ${bad} con fallo` : ""}`;
  document.querySelector("#photo-progress").textContent = text;
  say(text);
  document.querySelector("#xfer-cancel").hidden = true;
}

function cancelJob(job) {
  job.cancelled = true;
  if (job.status === "wait") {
    job.status = "cancel";
    job.state = "Cancelado";
  }
  if (job.xhr) job.xhr.abort();
  paintXfers(true);
}

let xferStarted = 0;
let xferPaint = 0;
const xferRows = new WeakMap();

function paintXfers(force) {
  const now = performance.now();
  if (!force && now - xferPaint < 150) return;
  xferPaint = now;
  const box = document.querySelector("#xfer");
  const list = document.querySelector("#xfers");
  if (!xferJobs.length) {
    box.hidden = true;
    list.replaceChildren();
    return;
  }
  box.hidden = false;
  let total = 0;
  let done = 0;
  for (const job of xferJobs) {
    total += job.file.size;
    done += job.status === "ok" || job.status === "skip" ? job.file.size : Math.min(job.file.size, job.done + job.inFlight);
  }
  const ratio = total ? done / total : 1;
  document.querySelector("#xfer-bar").style.width = Math.round(ratio * 100) + "%";
  document.querySelector(".xfer-track").setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
  const running = xferJobs.filter((job) => job.status === "run" || job.status === "wait").length;
  const seconds = (now - xferStarted) / 1000;
  const speed = seconds > 0.5 ? done / seconds : 0;
  document.querySelector("#xfer-stat").textContent = `${formatSize(done)} de ${formatSize(total)} · ${Math.round(ratio * 100)}% · ${formatSpeed(speed)} · pendientes ${running}`;
  document.querySelector("#xfer-cancel").hidden = !running;
  const wanted = new Set();
  for (const job of xferJobs) {
    let row = xferRows.get(job);
    if (!row) {
      row = document.createElement("li");
      row.className = "xfer-row";
      const name = document.createElement("b");
      name.textContent = job.file.name || "archivo";
      const track = document.createElement("div");
      track.className = "xfer-track";
      const bar = document.createElement("div");
      bar.className = "xfer-fill";
      track.append(bar);
      const note = document.createElement("small");
      const stop = document.createElement("button");
      stop.type = "button";
      stop.className = "xfer-x";
      stop.textContent = "✕";
      stop.setAttribute("aria-label", "Cancelar " + (job.file.name || "archivo"));
      stop.addEventListener("click", () => cancelJob(job));
      row.append(name, stop, track, note);
      xferRows.set(job, row);
    }
    wanted.add(row);
    const part = job.status === "ok" || job.status === "skip" ? 1 : job.file.size ? Math.min(1, (job.done + job.inFlight) / job.file.size) : 0;
    row.querySelector(".xfer-fill").style.width = Math.round(part * 100) + "%";
    row.dataset.state = job.status;
    const label = { wait: "En cola", run: Math.round(part * 100) + "%", ok: "", skip: "", cancel: "", error: "" }[job.status];
    row.querySelector("small").textContent = [formatSize(job.file.size), label, job.state].filter(Boolean).join(" · ");
    row.querySelector(".xfer-x").hidden = !(job.status === "wait" || job.status === "run");
  }
  if (list.children.length !== wanted.size || [...list.children].some((row) => !wanted.has(row))) {
    list.replaceChildren(...xferJobs.map((job) => xferRows.get(job)));
  }
}

document.querySelector("#send-input").addEventListener("change", (event) => queueFiles(event.target));
document.querySelector("#send-media").addEventListener("change", (event) => queueFiles(event.target));
/* En el móvil elegir carpeta no funciona (Android/iOS no lo dejan): se oculta. */
(function () {
  const warn = document.querySelector("#send-dir-warn");
  if (!("webkitdirectory" in document.createElement("input"))) {
    warn.textContent = "Este navegador no permite elegir carpetas. Usa «Archivos» y marca varios.";
    warn.hidden = false;
  }
})();
document.querySelector("#send-dir").addEventListener("change", (event) => {
  const files = Array.from(event.target.files || []);
  const warn = document.querySelector("#send-dir-warn");
  if (files.length && !files.some((f) => relDir(f))) {
    warn.textContent = "Tu navegador no dejó elegir la carpeta; se envían como archivos sueltos.";
    warn.hidden = false;
  }
  queueFiles(event.target);
});
document.querySelector("#xfer-cancel").addEventListener("click", () => {
  xferJobs.forEach((job) => {
    if (job.status === "wait" || job.status === "run") cancelJob(job);
  });
});

/* PC -> móvil por trozos: el móvil pide cada trozo, lo abre y lo guarda como Blob. */
async function receiveChunked(kind, id, fallbackName, onProgress) {
  const info = await api(`/api/get/${kind}/${id}/info`, null, "GET");
  const tid = `down-${kind}-${id}-${Date.now()}`;
  const parts = [];
  const job = { cancelled: false, state: "" };
  for (let index = 0; index < info.total; index += 1) {
    const buf = await withRetry(job, "trozo", async () => {
      let res;
      try {
        res = await lzFetch(`/api/get/${kind}/${id}/${index}`);
      } catch (_err) {
        const err = new Error("Se cortó la red");
        err.retry = true;
        throw err;
      }
      if (!res.ok) {
        const data = await readBody(res);
        const err = new Error(data.error || "No se pudo recibir");
        err.retry = res.status >= 500 || res.status === 401;
        err.auth = res.status === 401;
        throw err;
      }
      return res.arrayBuffer();
    });
    const plain = (await cryptoCall({ op: "open", tid, buf, key: wireKey }, [buf])).buf;
    parts.push(new Blob([plain]));
    if (onProgress) onProgress(Math.min(info.size, (index + 1) * info.chunk), info.size);
  }
  const { hex } = await cryptoCall({ op: "digest", tid });
  if (info.sha256 && hex !== info.sha256) throw new Error("El archivo llegó dañado. Vuelve a intentarlo.");
  const url = URL.createObjectURL(new Blob(parts));
  const temp = document.createElement("a");
  temp.href = url;
  temp.download = info.name || fallbackName || "archivo";
  document.body.append(temp);
  temp.click();
  temp.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 600000);
  info.blobUrl = url;
  return info;
}

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
  try {
    if (!localStorage.getItem("lazo-order-dl") && saved.includes("dl") && saved.includes("lab")) {
      const without = saved.filter((id) => id !== "dl");
      without.splice(without.indexOf("lab"), 0, "dl");
      saved = without;
      localStorage.setItem("lazo-order", JSON.stringify(saved));
    }
    localStorage.setItem("lazo-order-dl", "1");
    if (!localStorage.getItem("lazo-order-about") && saved.includes("about")) {
      saved = [...saved.filter((id) => id !== "about"), "about"];
      localStorage.setItem("lazo-order", JSON.stringify(saved));
    }
    localStorage.setItem("lazo-order-about", "1");
  } catch (_err) {
    /* sin almacenamiento */
  }
  const rest = saved.filter((id) => known.includes(id) && !PINNED.includes(id));
  known.forEach((id) => {
    if (!PINNED.includes(id) && !rest.includes(id)) rest.push(id);
  });
  return [...PINNED, ...rest];
}

/* Reordenar el dock: un deslizamiento normal mueve la barra; solo tras mantener
   pulsada una pastilla (~0,4 s) se entra en «modo reordenar». */
const LONG_PRESS = 400;
let arrange = null;
let clickBlockUntil = 0;

function arrangeBanner(show) {
  const banner = document.querySelector("#dock-banner");
  if (!banner) return;
  if (show) {
    const top = dock.getBoundingClientRect().top;
    banner.style.bottom = `${Math.max(8, window.innerHeight - top + 8)}px`;
  }
  banner.hidden = !show;
}

function arrangeStart(button, x) {
  const scroller = button.parentElement;
  arrange = { button, scroller, x, lastX: x, moved: false, raf: 0 };
  if (navigator.vibrate) navigator.vibrate(18);
  button.classList.add("lifting");
  dock.classList.add("arranging");
  arrangeBanner(true);
  const tick = () => {
    if (!arrange) return;
    const edge = scroller.getBoundingClientRect();
    if (arrange.lastX > edge.right - 36) scroller.scrollLeft += 8;
    else if (arrange.lastX < edge.left + 36) scroller.scrollLeft -= 8;
    arrangeMove(arrange.lastX, true);
    arrange.raf = window.requestAnimationFrame(tick);
  };
  arrange.raf = window.requestAnimationFrame(tick);
}

function arrangeMove(x, fromTick) {
  if (!arrange) return;
  const { button, scroller } = arrange;
  if (!fromTick) {
    if (Math.abs(x - arrange.x) > 6) arrange.moved = true;
    arrange.lastX = x;
  }
  const next = button.nextElementSibling;
  const prev = button.previousElementSibling;
  if (next) {
    const box = next.getBoundingClientRect();
    if (x > box.left + box.width / 2) {
      scroller.insertBefore(next, button);
      arrange.moved = true;
      return;
    }
  }
  if (prev) {
    const box = prev.getBoundingClientRect();
    if (x < box.left + box.width / 2) {
      scroller.insertBefore(button, prev);
      arrange.moved = true;
    }
  }
}

function arrangeEnd() {
  if (!arrange) return;
  const { button, scroller, moved, raf } = arrange;
  window.cancelAnimationFrame(raf);
  arrange = null;
  button.classList.remove("lifting");
  dock.classList.remove("arranging");
  arrangeBanner(false);
  clickBlockUntil = Date.now() + 450; /* soltar no abre la pastilla */
  if (!moved) return;
  const fixed = dock.querySelector(".dock-fixed");
  order = [...fixed.querySelectorAll("button"), ...scroller.querySelectorAll("button")].map((item) => item.dataset.cube);
  try {
    localStorage.setItem("lazo-order", JSON.stringify(order));
  } catch (_err) {
    /* sin almacenamiento: vale el orden de esta visita */
  }
  say("Orden guardado");
}

function armTouch(button) {
  let timer = 0;
  let startX = 0;
  let startY = 0;
  button.addEventListener("touchstart", (ev) => {
    if (ev.touches.length !== 1) return;
    startX = ev.touches[0].clientX;
    startY = ev.touches[0].clientY;
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      timer = 0;
      arrangeStart(button, startX);
    }, LONG_PRESS);
  }, { passive: true });
  button.addEventListener("touchmove", (ev) => {
    const t = ev.touches[0];
    if (arrange && arrange.button === button) {
      if (ev.cancelable) ev.preventDefault(); /* en modo reordenar la barra no se desplaza */
      arrangeMove(t.clientX, false);
      return;
    }
    if (timer && Math.hypot(t.clientX - startX, t.clientY - startY) > 10) {
      window.clearTimeout(timer); /* era un deslizamiento: la barra se mueve sola */
      timer = 0;
    }
  }, { passive: false });
  const done = () => {
    window.clearTimeout(timer);
    timer = 0;
    if (arrange && arrange.button === button) arrangeEnd();
  };
  button.addEventListener("touchend", done);
  button.addEventListener("touchcancel", done);
}

function armMouse(button) {
  button.addEventListener("pointerdown", (ev) => {
    if (ev.pointerType === "touch" || ev.button !== 0) return;
    const pointerId = ev.pointerId;
    const x0 = ev.clientX;
    let timer = window.setTimeout(() => {
      timer = 0;
      try {
        button.setPointerCapture(pointerId);
      } catch (_err) {
        /* sin captura sigue valiendo */
      }
      arrangeStart(button, x0);
    }, LONG_PRESS);
    const move = (e) => {
      if (e.pointerId !== pointerId) return;
      if (arrange && arrange.button === button) arrangeMove(e.clientX, false);
      else if (timer && Math.abs(e.clientX - x0) > 10) {
        window.clearTimeout(timer);
        timer = 0;
      }
    };
    const up = (e) => {
      if (e.pointerId !== pointerId) return;
      window.clearTimeout(timer);
      if (arrange && arrange.button === button) arrangeEnd();
      button.removeEventListener("pointermove", move);
      button.removeEventListener("pointerup", up);
      button.removeEventListener("pointercancel", up);
    };
    button.addEventListener("pointermove", move);
    button.addEventListener("pointerup", up);
    button.addEventListener("pointercancel", up);
  });
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
    button.addEventListener("click", (event) => {
      if (Date.now() < clickBlockUntil) {
        event.preventDefault();
        return;
      }
      openCube(id);
    });
    if (!PINNED.includes(id)) {
      armTouch(button);
      armMouse(button);
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
  if (document.hidden || tab !== "mouse") return;
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

let winRows = [];
let winTabsFor = "";

function winFolded() {
  try {
    const v = JSON.parse(localStorage.getItem("lazo-win-folded") || "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch (_err) {
    return [];
  }
}

function winHue(name) {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.codePointAt(0)) % 360;
  return h;
}

let winIcons = {};

function winBadge(app, key) {
  const src = key && winIcons[key];
  if (src) {
    const img = document.createElement("img");
    img.className = "win-icon";
    img.alt = "";
    img.src = src;
    return img;
  }
  const badge = document.createElement("span");
  badge.className = "win-badge";
  badge.textContent = (app.match(/[\p{L}\p{N}]/u) || ["?"])[0].toUpperCase();
  badge.style.background = `hsl(${winHue(app)} 45% 32%)`;
  return badge;
}

/* Tocar una ventana: al frente y maximizada. Debajo salen sus acciones. */
function pickWindow(win, button) {
  winId = win.id;
  document.querySelectorAll("#windows .picked").forEach((el) => el.classList.remove("picked"));
  if (button) {
    button.classList.add("picked");
    const panel = document.querySelector("#win-panel");
    const li = button.closest("li");
    if (li) li.after(panel);
    panel.hidden = false;
    document.querySelector("#win-move").hidden = true;
  }
  showTabs(win);
  api("/api/window", { id: win.id, action: "open" })
    .then((data) => say((data && data.detail) || "Ventana maximizada"))
    .catch((err) => say(err.message));
}

function holdTitle(button, title) {
  let held = 0;
  button.addEventListener("pointerdown", () => {
    held = window.setTimeout(() => say(title), 550);
  });
  ["pointerup", "pointercancel", "pointerleave"].forEach((ev) => button.addEventListener(ev, () => window.clearTimeout(held)));
}

function renderWindows() {
  const list = document.querySelector("#windows");
  const panel = document.querySelector("#win-panel");
  const query = document.querySelector("#win-filter").value.trim().toLowerCase();
  const folded = new Set(winFolded());
  const groups = new Map();
  winRows.forEach((win) => {
    const app = win.app || "Otras";
    const hay = `${win.title} ${app}`.toLowerCase();
    if (query && !hay.includes(query)) return;
    if (!groups.has(app)) groups.set(app, []);
    groups.get(app).push(win);
  });
  panel.hidden = true;
  list.after(panel);
  list.replaceChildren();
  let pickedButton = null;
  [...groups.keys()].sort((x, y) => groups.get(y).length - groups.get(x).length || x.localeCompare(y)).forEach((app) => {
    const rows = groups.get(app);
    if (rows.length === 1) {
      /* Una sola ventana: un botón directo, sin desplegar. */
      const win = rows[0];
      const li = document.createElement("li");
      li.className = "win-group";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "win-group-head win-single";
      const text = document.createElement("span");
      text.className = "win-single-text";
      const name = document.createElement("span");
      name.className = "win-app";
      name.textContent = app;
      const sub = document.createElement("small");
      sub.className = "win-sub";
      sub.textContent = win.short && win.short !== app ? win.short : "";
      sub.dir = "auto";
      text.append(name, sub);
      button.append(winBadge(app, win.icon), text);
      button.title = win.title;
      if (win.active) button.classList.add("active");
      if (win.id === winId) {
        button.classList.add("picked");
        pickedButton = button;
      }
      holdTitle(button, win.title);
      button.addEventListener("click", () => pickWindow(win, button));
      li.append(button);
      list.append(li);
      return;
    }
    const head = document.createElement("li");
    head.className = "win-group";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "win-group-head";
    const name = document.createElement("span");
    name.className = "win-app";
    name.textContent = app;
    const count = document.createElement("span");
    count.className = "win-count";
    count.textContent = String(rows.length);
    const open = !folded.has(app) || !!query;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.append(winBadge(app, rows[0].icon), name, count);
    toggle.addEventListener("click", () => {
      const now = new Set(winFolded());
      if (now.has(app)) now.delete(app);
      else now.add(app);
      localStorage.setItem("lazo-win-folded", JSON.stringify([...now].slice(-60)));
      renderWindows();
    });
    head.append(toggle);
    list.append(head);
    if (!open) return;
    rows.forEach((win) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "win-row";
      button.textContent = win.short || win.title;
      button.dir = "auto";
      button.title = win.title;
      if (win.active) button.classList.add("active");
      if (win.id === winId) {
        button.classList.add("picked");
        pickedButton = button;
      }
      holdTitle(button, win.title);
      button.addEventListener("click", () => pickWindow(win, button));
      item.append(button);
      list.append(item);
    });
  });
  if (pickedButton) {
    pickedButton.closest("li").after(panel);
    panel.hidden = false;
  }
  if (!list.children.length) {
    const empty = document.createElement("li");
    empty.className = "win-empty";
    empty.textContent = query ? "Ninguna ventana coincide" : "No veo ventanas";
    list.append(empty);
  }
}

async function showTabs(win) {
  const box = document.querySelector("#win-tabs");
  const ul = document.querySelector("#win-tabs-list");
  if (!win || !win.tabs) {
    box.hidden = true;
    winTabsFor = "";
    return;
  }
  box.hidden = false;
  winTabsFor = win.id;
  document.querySelector("#win-tabs-app").textContent = win.app;
  ul.replaceChildren();
  try {
    const data = await api("/api/tabs", { id: win.id });
    if (winTabsFor !== win.id) return;
    const tabs = Array.isArray(data.tabs) ? data.tabs : [];
    tabs.forEach((tab) => {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.className = "win-row";
      b.textContent = tab.title;
      b.dir = "auto";
      b.title = tab.title;
      if (tab.active) b.classList.add("active");
      b.addEventListener("click", () => {
        api("/api/tab", { id: win.id, action: "go", index: tab.i })
          .then((res) => {
            say(res.detail || "Pestaña cambiada");
            ul.querySelectorAll(".win-row").forEach((el) => el.classList.remove("active"));
            b.classList.add("active");
          })
          .catch((err) => say(err.message));
      });
      li.append(b);
      ul.append(li);
    });
    ul.hidden = !tabs.length;
  } catch (_err) {
    ul.hidden = true;
  }
}

let winLoading = false;
async function loadWindows() {
  if (winLoading) return;
  winLoading = true;
  loadScreens();
  try {
    const data = await api("/api/windows", null, "GET");
    winRows = Array.isArray(data.windows) ? data.windows : [];
    if (data.icons && typeof data.icons === "object") {
      for (const [k, v] of Object.entries(data.icons)) if (/^data:image\/(png|svg\+xml);base64,/.test(v)) winIcons[k] = v;
    }
    if (data.icons_pending && !loadWindows.retried) {
      loadWindows.retried = true; /* los iconos llegan en segundo plano: una vuelta más */
      window.setTimeout(() => { if (tab === "windows") loadWindows(); }, 2500);
    } else if (!data.icons_pending) loadWindows.retried = false;
    if (!winRows.some((w) => w.id === winId)) {
      const front = winRows.find((w) => w.active);
      winId = front ? front.id : "";
    }
    renderWindows();
    const picked = winRows.find((w) => w.id === winId);
    showTabs(picked);
  } catch (err) {
    say(err.message);
  } finally {
    winLoading = false;
  }
}

document.querySelector("#win-filter").addEventListener("input", renderWindows);

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    if (!winTabsFor) return;
    const id = winTabsFor;
    api("/api/tab", { id, action: button.dataset.tab })
      .then((res) => {
        say(res.detail || "Pestaña cambiada");
        const win = winRows.find((w) => w.id === id);
        window.setTimeout(() => showTabs(win), 400);
      })
      .catch((err) => say(err.message));
  });
});

document.querySelector("#win-refresh").addEventListener("click", loadWindows);

document.querySelector("#win-move-open").addEventListener("click", () => {
  if (!winId) {
    say("Primero toca una ventana de la lista");
    return;
  }
  const n = (screensInfo && screensInfo.count) || 0;
  if (n === 2 && screensInfo.can_move) {
    /* Con dos pantallas, a la otra directamente. */
    api("/api/screen", { id: winId, screen: 0 }).then((data) => say(data.detail || "Pantalla cambiada")).catch((err) => say(err.message));
    return;
  }
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
  document.querySelector("#sys-lock").hidden = !caps.lock;
  const swap = document.querySelector("#sys-swap");
  const note = document.querySelector("#sys-swap-note");
  const pick = document.querySelector("#sys-swap-pick");
  const count = Number(caps.count || 0);
  pick.replaceChildren();
  pick.hidden = true;
  if (!caps.swap) {
    swap.disabled = true;
    note.textContent = "Intercambiar pantallas: no disponible en este sistema";
  } else if (count < 2) {
    swap.disabled = true;
    swap.textContent = "Solo hay una pantalla";
    note.textContent = "";
  } else {
    swap.disabled = false;
    swap.textContent = count === 2 ? "Intercambiar pantallas 1 ⇄ 2" : "Intercambiar pantallas…";
    note.textContent = "Las ventanas de una pantalla pasan a la otra, y al revés.";
    if (count > 2) {
      for (const [x, y] of [[1, 2], [1, 3], [2, 3]]) {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = `${x} ⇄ ${y}`;
        b.addEventListener("click", () => doSwap(x, y));
        pick.append(b);
      }
    }
  }
  swap.dataset.count = String(count);
}

function doSwap(a, b) {
  api("/api/system", { action: "swap_screens", a, b }).then((data) => say(data.detail || "Hecho")).catch((err) => say(err.message));
}

document.querySelector("#sys-swap").addEventListener("click", (event) => {
  const count = Number(event.currentTarget.dataset.count || 0);
  if (count > 2) {
    const pick = document.querySelector("#sys-swap-pick");
    pick.hidden = !pick.hidden;
    return;
  }
  doSwap(1, 2);
});

/* Diálogo propio (confirm() del navegador falla o se ve mal en algunos móviles). */
function askConfirm(title, text, yes) {
  return new Promise((resolve) => {
    const box = document.querySelector("#confirm");
    document.querySelector("#confirm-title").textContent = title;
    document.querySelector("#confirm-text").textContent = text;
    const ok = document.querySelector("#confirm-yes");
    const no = document.querySelector("#confirm-no");
    ok.textContent = yes;
    box.hidden = false;
    const done = (value) => {
      box.hidden = true;
      ok.onclick = null;
      no.onclick = null;
      box.onclick = null;
      resolve(value);
    };
    ok.onclick = () => done(true);
    no.onclick = () => done(false);
    box.onclick = (event) => { if (event.target === box) done(false); };
  });
}

document.querySelector("#sys-lock").addEventListener("click", async () => {
  const ok = await askConfirm("¿Bloquear el PC?", "Se bloqueará la sesión del PC; para volver tendrás que desbloquearlo allí.", "Bloquear");
  if (!ok) return;
  api("/api/system", { action: "lock" }).then((data) => say(data.detail || "Hecho")).catch((err) => say(err.message));
});

document.querySelectorAll("[data-sys]").forEach((button) => {
  button.addEventListener("click", () => {
    const action = button.dataset.sys;
    api("/api/system", { action }).then((data) => say(data.detail || "Hecho")).catch((err) => say(err.message));
  });
});

const ICON_PLAY = '<svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true"><path d="M7 4.5v15L20 12z" fill="currentColor"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true"><rect x="6" y="4.5" width="4.2" height="15" rx="1" fill="currentColor"/><rect x="13.8" y="4.5" width="4.2" height="15" rx="1" fill="currentColor"/></svg>';
const mediaState = { yt: { playing: null, hold: 0, busy: false }, sp: { playing: null, hold: 0, busy: false } };

/* Si suena, el botón enseña pausa; si está en pausa, enseña play. */
function setPlay(prefix, playing) {
  const button = document.querySelector(`#${prefix}-play`);
  mediaState[prefix].playing = playing;
  button.innerHTML = playing ? ICON_PAUSE : ICON_PLAY;
  button.setAttribute("aria-label", playing ? "Pausar" : "Reproducir");
  button.dataset.playing = playing ? "1" : "0";
}

function cleanMediaTitle(text) {
  return String(text || "")
    .replace(/\s*[-–—]\s*(Google Chrome|Mozilla Firefox|Microsoft\u200b?\s*Edge|Brave|Opera|Chromium|Vivaldi)\s*$/i, "")
    .replace(/\s*[-–—]\s*YouTube\s*$/i, "")
    .replace(/^\(\d+\)\s*/, "")
    .trim();
}

function setMediaTitle(prefix, text) {
  const el = document.querySelector(`#${prefix}-title`);
  const clean = prefix === "yt" ? cleanMediaTitle(text) : String(text || "");
  if (!clean || el.textContent === clean) return;
  el.textContent = clean;
  el.title = clean;
}

function applyMedia(prefix, data) {
  if (!data) return;
  if (data.title) setMediaTitle(prefix, data.title);
  if (typeof data.level === "number") setLevel(prefix, data.level);
  if (typeof data.playing === "boolean" && Date.now() > mediaState[prefix].hold) setPlay(prefix, data.playing);
}

/* Sondeo ligero mientras YouTube o Spotify están a la vista: título y play/pausa solos. */
let mediaTimer = 0;
async function mediaPoll() {
  if (document.hidden || app.hidden || (tab !== "youtube" && tab !== "spotify")) return;
  const prefix = tab === "youtube" ? "yt" : "sp";
  const st = mediaState[prefix];
  if (st.busy || Date.now() < st.hold) return;
  st.busy = true;
  try {
    const data = await api(prefix === "yt" ? "/api/youtube" : "/api/spotify", { action: "status" });
    if (tab === (prefix === "yt" ? "youtube" : "spotify")) {
      if (data.missing) setMediaTitle(prefix, "Abre YouTube en el PC");
      applyMedia(prefix, data);
    }
  } catch (_err) {
    /* sin ruido: el siguiente sondeo lo intenta otra vez */
  } finally {
    st.busy = false;
  }
}
function mediaWatch(on) {
  window.clearInterval(mediaTimer);
  mediaTimer = 0;
  if (on) {
    mediaPoll();
    mediaTimer = window.setInterval(mediaPoll, 2500);
  }
}

function mediaButtons(attr, prefix, path, label) {
  document.querySelectorAll(`[data-${attr}]`).forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.dataset[attr];
      const st = mediaState[prefix];
      let wanted = null;
      if (action === "play") {
        wanted = !st.playing;
        setPlay(prefix, wanted); /* al momento, sin esperar al PC */
        st.hold = Date.now() + 2500;
      }
      try {
        const data = await api(path, { action });
        if (action === "play") {
          st.hold = Date.now() + 1200;
          if (typeof data.playing === "boolean") {
            setPlay(prefix, data.playing);
          }
          delete data.playing;
        }
        applyMedia(prefix, data);
        if (action === "play") {
          say(st.playing ? `${label} en play` : `${label} en pausa`);
        } else if (action === "mute") {
          button.classList.toggle("muted");
          say(button.classList.contains("muted") ? `${label} silencio` : `${label} con sonido`);
        } else {
          const names = {
            prev: data.detail && data.detail !== label ? data.detail : `${label} anterior`,
            next: `${label} siguiente`,
            back: "YouTube −10 s",
            forward: "YouTube +10 s",
            home: "YouTube inicio",
            full: "YouTube pantalla",
            theater: "YouTube cine",
            captions: "YouTube subtítulos",
          };
          say(names[action] || label);
          if (action === "prev" || action === "next") window.setTimeout(mediaPoll, 1500);
        }
      } catch (err) {
        if (action === "play" && wanted !== null) setPlay(prefix, !wanted);
        st.hold = 0;
        say(err.message);
      }
    });
  });
}
mediaButtons("yt", "yt", "/api/youtube", "YouTube");
mediaButtons("sp", "sp", "/api/spotify", "Spotify");
setPlay("yt", false);
setPlay("sp", false);

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
  if (!(await askConfirm("¿Bloquear el PC?", "Se bloqueará la sesión del PC; para volver tendrás que desbloquearlo allí.", "Bloquear"))) return;
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

/* ---- Descargatodo: el móvil manda el enlace; el PC descarga con yt-dlp ---- */
var dlTimer = 0;
var dlInfo = null;
var dlUrl = "";
var dlSent = {};

function dlEl(id) {
  return document.querySelector(id);
}

function dlSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + " KB";
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + " GB";
}

function dlTime(sec) {
  if (!sec) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = String(sec % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function dlStop() {
  clearInterval(dlTimer);
  dlTimer = 0;
}

async function dlOpen() {
  dlStop();
  await dlTools();
  await dlPoll();
  dlTimer = setInterval(dlPoll, 1200);
}

async function dlTools() {
  try {
    const t = await api("/api/dl/tools", null, "GET");
    const box = dlEl("#dl-tools");
    const missing = !t.ytdlp || (!t.ffmpeg && t.ffmpeg_can_install) || (!t.deno && t.deno_can_install);
    box.hidden = !missing && !t.old && t.install.state !== "instalando";
    const parts = [];
    if (!t.ytdlp) parts.push("yt-dlp");
    if (!t.ffmpeg) parts.push("ffmpeg");
    if (!t.deno) parts.push("deno (YouTube lo necesita)");
    dlEl("#dl-tools-msg").textContent = parts.length
      ? `Falta ${parts.join(", ")}. Se descarga del sitio oficial y se comprueba su huella.`
      : t.old
        ? `Tu yt-dlp (${t.version}) es viejo y YouTube suele rechazarlo. Pulsa «Actualizar yt-dlp».`
        : "Herramientas listas.";
    dlEl("#dl-install").hidden = !missing;
    dlEl("#dl-install").textContent = t.ytdlp ? "Instalar lo que falta" : "Instalar herramientas (una vez)";
    dlEl("#dl-version").textContent =
      (t.ytdlp ? `yt-dlp ${t.version || ""}` : "yt-dlp no instalado") +
      (t.deno ? " · deno listo" : "") +
      (t.ffmpeg ? " · ffmpeg listo" : t.ffmpeg_hint ? " · " + t.ffmpeg_hint : " · sin ffmpeg (sin MP3 ni unir vídeo+audio)") +
      ` · Se guarda en ${t.folder}`;
    dlEl("#dl-update").hidden = !t.ytdlp;
    dlShowInstall(t.install);
    return t;
  } catch (err) {
    say(err.message);
    return null;
  }
}

function dlShowInstall(inst) {
  const bar = dlEl("#dl-install-bar");
  if (!inst || !inst.state) {
    bar.hidden = true;
    return;
  }
  if (inst.state === "instalando") {
    bar.hidden = false;
    const pct = inst.total ? Math.round((inst.done * 100) / inst.total) : 5;
    dlEl("#dl-install-fill").style.width = pct + "%";
    dlEl("#dl-tools-msg").textContent = `Instalando ${inst.what || ""}… ${dlSize(inst.done)}${inst.total ? " de " + dlSize(inst.total) : ""}`;
    dlEl("#dl-install").hidden = true;
  } else {
    bar.hidden = true;
    if (inst.state === "error") dlEl("#dl-tools-msg").textContent = "No se pudo instalar: " + inst.error;
  }
}

var dlWasInstalling = false;

async function dlPoll() {
  if (document.hidden) return;
  try {
    const data = await api("/api/dl/status", null, "GET");
    const inst = data.install || {};
    if (inst.state === "instalando") {
      dlWasInstalling = true;
      dlEl("#dl-tools").hidden = false;
      dlShowInstall(inst);
    } else if (dlWasInstalling) {
      dlWasInstalling = false;
      dlTools();
    }
    dlRenderJobs(data.jobs || []);
  } catch (_err) {}
}

// La lista se actualiza cada 1,2 s. Antes se borraba y se volvía a pintar entera, así que
// un toque en «Enviar al móvil» o «Cancelar» justo en ese momento se perdía. Ahora cada
// fila se conserva (por id) y solo cambian los textos.
var dlRows = {};
var dlBusy = {};

function dlRow(job) {
  let r = dlRows[job.id];
  if (r) return r;
  const row = document.createElement("li");
  row.className = "dl-job";
  const name = document.createElement("p");
  name.className = "dl-job-name";
  const stat = document.createElement("p");
  stat.className = "hint";
  const err = document.createElement("p");
  err.className = "dl-err";
  const track = document.createElement("div");
  track.className = "xfer-track";
  const fill = document.createElement("div");
  fill.className = "dl-fill";
  track.append(fill);
  const actions = document.createElement("div");
  actions.className = "dl-row";
  const send = document.createElement("button");
  send.type = "button";
  send.className = "primary";
  send.addEventListener("click", () => dlReceive(dlRows[job.id].job, send));
  const save = document.createElement("a");
  save.className = "dl-save";
  save.hidden = true;
  save.textContent = "Guardar archivo";
  const upd = document.createElement("button");
  upd.type = "button";
  upd.className = "primary";
  upd.textContent = "Actualizar yt-dlp";
  upd.addEventListener("click", dlUpdate);
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "dl-cancel";
  cancel.addEventListener("click", async () => {
    row.remove();
    delete dlRows[job.id];
    try {
      await api("/api/dl/cancel", { id: job.id });
      dlPoll();
    } catch (e) {
      say(e.message);
    }
  });
  actions.append(send, save, upd, cancel);
  row.append(name, stat, err, track, actions);
  r = { row, name, stat, err, track, fill, send, save, upd, cancel, job };
  dlRows[job.id] = r;
  return r;
}

function dlRenderJobs(jobs) {
  const list = dlEl("#dl-jobs");
  const shown = jobs.slice(0, 12);
  const keep = {};
  shown.forEach((job, i) => {
    const r = dlRow(job);
    r.job = job;
    keep[job.id] = true;
    r.name.textContent = job.name || job.title;
    let text = `${job.label} · ${job.state === "preparando" ? "preparando…" : job.state}`;
    if (job.state === "descargando") {
      text += job.pct ? ` ${job.pct}%` : job.got ? ` ${dlSize(job.got)}` : " (preparando…)";
      if (job.speed) text += ` · ${dlSize(job.speed)}/s`;
      if (job.eta) text += ` · quedan ${dlTime(job.eta)}`;
    }
    if (job.state === "hecha") text += ` · ${dlSize(job.size)} · guardado en el PC`;
    if (job.note && job.state !== "hecha" && job.state !== "error") text += ` · ${job.note}`;
    r.stat.textContent = text;
    r.err.textContent = job.error || "";
    r.err.hidden = !job.error;
    const active = ["en cola", "preparando", "descargando", "procesando"].includes(job.state);
    r.track.hidden = !active;
    r.fill.style.width = (job.state === "procesando" ? 100 : job.pct || 0) + "%";
    r.track.classList.toggle("busy", active && !job.pct && job.state !== "procesando");
    r.send.hidden = job.state !== "hecha";
    if (!dlBusy[job.id]) r.send.textContent = dlSent[job.id] ? "Enviar otra vez" : "Enviar al móvil";
    r.upd.hidden = !(job.state === "error" && job.update);
    r.cancel.textContent = active ? "Cancelar" : "Quitar";
    if (list.children[i] !== r.row) list.insertBefore(r.row, list.children[i] || null);
  });
  for (const id of Object.keys(dlRows)) {
    if (!keep[id] && !dlBusy[id]) {
      dlRows[id].row.remove();
      delete dlRows[id];
    }
  }
}

async function dlUpdate() {
  try {
    const res = await api("/api/dl/update", {});
    say(res.detail || "Actualizando…");
    dlEl("#dl-tools").hidden = false;
    dlWasInstalling = true;
    dlPoll();
  } catch (err) {
    say(err.message);
  }
}

async function dlReceive(job, button) {
  if (dlBusy[job.id]) return;
  dlBusy[job.id] = true;
  button.disabled = true;
  button.textContent = "Recibiendo…";
  try {
    const info = await receiveChunked("dl", job.id, job.name || "descarga", (got, size) => {
      button.textContent = `Recibiendo… ${Math.round((got / Math.max(1, size)) * 100)}%`;
    });
    dlSent[job.id] = true;
    button.textContent = "Enviado ✓";
    // Algunos móviles ignoran la descarga automática tras una espera larga: dejamos un
    // enlace real para tocarlo a mano.
    const r = dlRows[job.id];
    if (r && info && info.blobUrl) {
      r.save.href = info.blobUrl;
      r.save.download = info.name || job.name || "descarga";
      r.save.hidden = false;
      r.save.textContent = "¿No se guardó? Toca aquí";
    }
    say("Listo: mira las descargas del móvil");
  } catch (err) {
    button.textContent = "Enviar al móvil";
    say(err.message);
  } finally {
    button.disabled = false;
    delete dlBusy[job.id];
  }
}

function dlChoiceButton(id, label, detail, extra) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = extra || "";
  button.textContent = label;
  if (detail) {
    const small = document.createElement("small");
    small.textContent = " " + detail;
    button.append(small);
  }
  button.addEventListener("click", async () => {
    try {
      await api("/api/dl/start", { url: dlUrl, choice: id, title: dlInfo ? dlInfo.title : "", playlist: dlEl("#dl-playlist").checked });
      dlPoll();
    } catch (err) {
      say(err.message);
    }
  });
  return button;
}

function dlRenderInfo(info) {
  dlInfo = info;
  dlEl("#dl-card").hidden = false;
  dlEl("#dl-title").textContent = info.title;
  const meta = [];
  if (info.uploader) meta.push(info.uploader);
  if (info.duration) meta.push(dlTime(info.duration));
  if (info.playlist) meta.push(`${info.count} vídeos`);
  dlEl("#dl-meta").textContent = meta.join(" · ");
  const box = dlEl("#dl-choices");
  box.replaceChildren();
  info.choices.forEach((c, i) => {
    const off = c.ffmpeg && !info.ffmpeg;
    const button = dlChoiceButton(c.id, c.label, off ? "(necesita ffmpeg)" : c.detail, i === 0 ? "primary" : "");
    button.disabled = off;
    box.append(button);
  });
  const list = dlEl("#dl-formats");
  list.replaceChildren();
  list.hidden = true;
  dlEl("#dl-adv-open").hidden = !info.formats.length;
  info.formats
    .slice()
    .reverse()
    .forEach((f) => {
      const row = document.createElement("li");
      const id = f.kind === "solo vídeo" && info.ffmpeg ? f.id + "+bestaudio" : f.id;
      const label = `${f.id} · ${f.res || "-"} · ${f.ext} · ${f.kind}${f.size ? " · ~" + dlSize(f.size) : ""}`;
      row.append(dlChoiceButton(id.replace("+bestaudio", "+ba"), label, f.note, ""));
      list.append(row);
    });
}

dlEl("#dl-adv-open").addEventListener("click", () => {
  const list = dlEl("#dl-formats");
  list.hidden = !list.hidden;
});

dlEl("#dl-paste").addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (text) dlEl("#dl-url").value = text.trim();
  } catch (_err) {
    dlEl("#dl-url").focus();
    say("Mantén pulsado el campo y elige Pegar");
  }
});

dlEl("#dl-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = dlEl("#dl-url").value.trim();
  if (!/^https?:\/\//i.test(url)) {
    say("El enlace tiene que empezar por http:// o https://");
    return;
  }
  const find = dlEl("#dl-find");
  find.disabled = true;
  find.textContent = "Buscando…";
  dlEl("#dl-card").hidden = true;
  try {
    dlUrl = url;
    const info = await api("/api/dl/info", { url, playlist: dlEl("#dl-playlist").checked });
    dlRenderInfo(info);
    say(info.title);
  } catch (err) {
    say(err.message);
  } finally {
    find.disabled = false;
    find.textContent = "Buscar formatos";
  }
});

dlEl("#dl-install").addEventListener("click", async () => {
  try {
    await api("/api/dl/install", { what: "all" });
    dlWasInstalling = true;
    dlEl("#dl-install").hidden = true;
    dlEl("#dl-install-bar").hidden = false;
  } catch (err) {
    say(err.message);
  }
});

dlEl("#dl-update").addEventListener("click", async () => {
  try {
    await api("/api/dl/update", {});
    dlWasInstalling = true;
  } catch (err) {
    say(err.message);
  }
});

/* Sobre LaZoo */
function aboutSafeUrl(url) {
  return typeof url === "string" && /^https?:\/\/[^\s<>"'`\\]+$/i.test(url) ? url : "";
}

function aboutLink(url, text) {
  const a = document.createElement("a");
  a.href = url;
  a.textContent = text;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}

async function aboutOpen() {
  try {
    const data = await api("/api/about", null, "GET");
    document.querySelector("#about-version").textContent = data.version || "";
    document.querySelector("#about-license").textContent = data.license || "";
    const list = document.querySelector("#about-links");
    list.replaceChildren();
    let links = (data.links || []).filter((item) => aboutSafeUrl(item.url));
    if (!links.length) links = [{ label: "Código (GitHub)", url: "https://github.com/Guerrillabitcoin/lazo" }];
    links.forEach((item) => {
      const li = document.createElement("li");
      li.append(aboutLink(item.url, String(item.label || item.url)));
      list.append(li);
    });
    aboutDonations(data.donations || []);
  } catch (_err) {
    say("No se pudo leer Sobre LaZoo");
  }
}

function aboutDonations(items) {
  const box = document.querySelector("#about-donate");
  box.replaceChildren();
  if (!items.length) {
    const p = document.createElement("p");
    p.className = "about-soon";
    p.textContent = "Próximamente. LaZoo es de código abierto, sin premium, y se financia con donaciones en Bitcoin.";
    box.append(p);
    return;
  }
  const warn = document.createElement("p");
  warn.className = "dl-notice";
  warn.textContent = "Comprueba la dirección en el repo oficial antes de enviar.";
  box.append(warn);
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "about-pay";
    const title = document.createElement("p");
    title.className = "about-pay-title";
    title.textContent = String(item.label || "");
    const code = document.createElement("code");
    code.className = "about-addr";
    code.textContent = String(item.value || "");
    const copy = document.createElement("button");
    copy.type = "button";
    copy.textContent = "Copiar";
    copy.addEventListener("click", () => copyToPhone(String(item.value || "")));
    card.append(title);
    if (typeof item.qr === "string" && item.qr.startsWith("<svg")) {
      const qr = document.createElement("div");
      qr.className = "about-qr";
      const doc = new DOMParser().parseFromString(item.qr, "text/html");
      const svg = doc.body.firstElementChild;
      if (svg && svg.nodeName.toLowerCase() === "svg" && !svg.querySelector("script,foreignObject")) qr.append(document.importNode(svg, true));
      card.append(qr);
    }
    card.append(code, copy);
    if (item.kind === "onchain") {
      const note = document.createElement("p");
      note.className = "hint";
      note.textContent = "No reutilices esta dirección para otras cosas.";
      card.append(note);
    }
    box.append(card);
  });
}

document.querySelector("#about-check").addEventListener("click", async (ev) => {
  const button = ev.currentTarget;
  const out = document.querySelector("#about-update");
  button.disabled = true;
  out.replaceChildren(document.createTextNode("Comprobando…"));
  try {
    const res = await api("/api/about/check", {});
    out.replaceChildren(document.createTextNode(res.message || "No se pudo comprobar"));
    if (res.state === "nueva") {
      out.append(document.createTextNode(" · "), aboutLink("https://github.com/Guerrillabitcoin/lazo", "Ver en GitHub"));
    }
  } catch (_err) {
    out.replaceChildren(document.createTextNode("No se pudo comprobar"));
  } finally {
    button.disabled = false;
  }
});

/* Con la pestaña oculta no se consulta al PC (batería). Al volver, se pone al día. */
document.addEventListener("visibilitychange", () => {
  if (document.hidden || app.hidden) return;
  refreshStatus();
  syncClipboard();
  if (tab === "dl") dlPoll();
  if (tab === "youtube" || tab === "spotify") mediaPoll();
});

/* ---- Escanear el QR del PC ----
   Por HTTP en la Wi-Fi (sin certificado) Chrome y Safari NO dejan usar la cámara en
   directo (getUserMedia solo existe en HTTPS o localhost). Por eso «Escanear QR» abre
   la cámara NATIVA del móvil (input con capture) y la foto se lee aquí mismo, sin
   internet: primero con BarcodeDetector si el navegador lo tiene y si no con jsQR
   (Apache-2.0, incluido en /jsqr.js). Si hay cámara en directo (localhost/HTTPS), se usa. */
var qrLib = null;
var qrStream = null;
var qrTimer = 0;

function qrSay(text) {
  const el = document.querySelector("#qr-msg");
  if (el) el.textContent = text;
  say(text);
}

function qrLoadLib() {
  if (window.jsQR) return Promise.resolve(window.jsQR);
  if (qrLib) return qrLib;
  qrLib = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "/jsqr.js?v=0.41";
    s.onload = () => (window.jsQR ? resolve(window.jsQR) : reject(new Error("No se pudo cargar el lector de QR")));
    s.onerror = () => {
      qrLib = null;
      reject(new Error("No se pudo cargar el lector de QR"));
    };
    document.head.append(s);
  });
  return qrLib;
}

// ¿Es una dirección de la red de casa? Nunca saltamos a internet pública.
function qrPrivateHost(host) {
  const h = String(host || "").toLowerCase().replace(/^\[|\]$/g, "");
  if (h === "localhost" || h.endsWith(".local") || h.endsWith(".lan") || h.endsWith(".home.arpa")) return true;
  const m = h.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (m) {
    const [a, b] = [Number(m[1]), Number(m[2])];
    if ([m[1], m[2], m[3], m[4]].some((x) => Number(x) > 255)) return false;
    return a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 169 && b === 254) || (a === 100 && b >= 64 && b <= 127);
  }
  if (h.includes(":")) return h === "::1" || /^f[cd][0-9a-f]{2}:/.test(h) || /^fe[89ab][0-9a-f]:/.test(h);
  return false;
}

// Texto del QR -> entrar. Devuelve un mensaje de error o "" si va bien.
function qrUse(text) {
  let url;
  try {
    url = new URL(String(text || "").trim());
  } catch (_err) {
    return "Ese QR no es de LaZoo";
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return "Ese QR no es de LaZoo";
  const key = new URLSearchParams(url.hash.replace(/^#/, "")).get("k") || "";
  if (!key) return "Ese QR no trae la clave de LaZoo";
  if (!qrPrivateHost(url.hostname)) return "Ese QR apunta a internet, no a un PC de tu red. No lo abro.";
  if (url.host === location.host) {
    try {
      setMasterKey(key);
    } catch (_err) {
      return "La clave del QR no es válida";
    }
    localStorage.setItem("lazo-key", key);
    qrSay("QR leído. Conectando…");
    window.setTimeout(() => location.replace(location.pathname), 150);
    return "";
  }
  qrSay("QR leído. Abriendo LaZoo en " + url.host + "…");
  window.setTimeout(() => location.replace(url.origin + "/#k=" + encodeURIComponent(key)), 150);
  return "";
}

async function qrFromCanvas(canvas) {
  if ("BarcodeDetector" in window) {
    try {
      const det = new window.BarcodeDetector({ formats: ["qr_code"] });
      const codes = await det.detect(canvas);
      if (codes && codes.length) return codes[0].rawValue;
    } catch (_err) {}
  }
  const jsQR = await qrLoadLib();
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const found = jsQR(img.data, img.width, img.height, { inversionAttempts: "attemptBoth" });
  return found ? found.data : "";
}

async function qrLoadImage(file) {
  if (window.createImageBitmap) {
    try {
      return await createImageBitmap(file, { imageOrientation: "from-image" });
    } catch (_err) {}
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return img;
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
}

// Una foto del móvil pesa 12 MP: se prueba a varios tamaños (los QR pequeños en la foto
// necesitan resolución; los grandes se leen mejor reducidos).
async function qrFromFile(file) {
  if (!file) return;
  qrSay("Leyendo el QR de la foto…");
  let img;
  try {
    img = await qrLoadImage(file);
  } catch (_err) {
    qrSay("No pude abrir esa imagen");
    return;
  }
  const w = img.width || img.naturalWidth;
  const h = img.height || img.naturalHeight;
  for (const side of [1600, 1000, 640, 2400]) {
    const scale = Math.min(1, side / Math.max(w, h));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(w * scale));
    canvas.height = Math.max(1, Math.round(h * scale));
    canvas.getContext("2d", { willReadFrequently: true }).drawImage(img, 0, 0, canvas.width, canvas.height);
    let text = "";
    try {
      text = await qrFromCanvas(canvas);
    } catch (err) {
      qrSay(err.message);
      return;
    }
    if (text) {
      const bad = qrUse(text);
      if (bad) qrSay(bad);
      return;
    }
    if (scale === 1 && side !== 2400) continue;
  }
  qrSay("No encontré un QR en la foto. Acércate, que salga entero y sin reflejos.");
}

function qrStopLive() {
  window.clearInterval(qrTimer);
  qrTimer = 0;
  if (qrStream) qrStream.getTracks().forEach((t) => t.stop());
  qrStream = null;
  document.querySelector("#qr-live").hidden = true;
}

async function qrLive() {
  const video = document.querySelector("#qr-video");
  qrStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
  video.srcObject = qrStream;
  document.querySelector("#qr-live").hidden = false;
  await video.play();
  const canvas = document.createElement("canvas");
  let busy = false;
  qrTimer = window.setInterval(async () => {
    if (busy || !video.videoWidth) return;
    busy = true;
    try {
      const scale = Math.min(1, 800 / Math.max(video.videoWidth, video.videoHeight));
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      canvas.getContext("2d", { willReadFrequently: true }).drawImage(video, 0, 0, canvas.width, canvas.height);
      const text = await qrFromCanvas(canvas);
      if (text) {
        const bad = qrUse(text);
        if (!bad) qrStopLive();
        else qrSay(bad);
      }
    } catch (_err) {
    } finally {
      busy = false;
    }
  }, 300);
}

function qrStart() {
  // Cámara en directo solo donde el navegador la permite (HTTPS o localhost).
  if (window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    qrLoadLib().catch(() => {});
    qrLive().catch(() => {
      qrStopLive();
      document.querySelector("#qr-cam").click();
    });
    return;
  }
  // Por HTTP: cámara nativa del móvil. Tiene que ir dentro del mismo toque.
  document.querySelector("#qr-cam").click();
  qrLoadLib().catch(() => {});
}

document.querySelector("#qr-scan").addEventListener("click", qrStart);
document.querySelector("#qr-top").addEventListener("click", qrStart);
document.querySelector("#qr-stop").addEventListener("click", qrStopLive);
for (const sel of ["#qr-cam", "#qr-photo"]) {
  document.querySelector(sel).addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    qrFromFile(file);
  });
}
