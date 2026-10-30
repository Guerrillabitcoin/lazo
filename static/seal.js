/* Cifrado del puente: HMAC-SHA256 en modo flujo. La clave vive solo en el QR, no viaja. */
const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

/* SHA-256 por palabras, sin crear arrays por bloque: el puente cifra gigas con esto. */
const W64 = new Int32Array(64);

function compressWords(H, W) {
  for (let i = 16; i < 64; i += 1) {
    const x = W[i - 15];
    const y = W[i - 2];
    const s0 = ((x >>> 7) | (x << 25)) ^ ((x >>> 18) | (x << 14)) ^ (x >>> 3);
    const s1 = ((y >>> 17) | (y << 15)) ^ ((y >>> 19) | (y << 13)) ^ (y >>> 10);
    W[i] = (W[i - 16] + s0 + W[i - 7] + s1) | 0;
  }
  let a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
  for (let i = 0; i < 64; i += 1) {
    const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
    const t1 = (h + S1 + ((e & f) ^ (~e & g)) + K[i] + W[i]) | 0;
    const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
    const t2 = (S0 + ((a & b) ^ (a & c) ^ (b & c))) | 0;
    h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
  }
  H[0] = (H[0] + a) | 0; H[1] = (H[1] + b) | 0; H[2] = (H[2] + c) | 0; H[3] = (H[3] + d) | 0;
  H[4] = (H[4] + e) | 0; H[5] = (H[5] + f) | 0; H[6] = (H[6] + g) | 0; H[7] = (H[7] + h) | 0;
}

const SHA_IV = new Int32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);

function compressBytes(H, bytes, off) {
  for (let i = 0; i < 16; i += 1) {
    const p = off + i * 4;
    W64[i] = (bytes[p] << 24) | (bytes[p + 1] << 16) | (bytes[p + 2] << 8) | bytes[p + 3];
  }
  compressWords(H, W64);
}

/* SHA-256 incremental: update() con trozos de cualquier tamaño, digest() al final. */
class Sha256 {
  constructor(state, length) {
    this.H = state ? new Int32Array(state) : new Int32Array(SHA_IV);
    this.buf = new Uint8Array(64);
    this.fill = 0;
    this.length = length || 0;
  }

  update(data) {
    let pos = 0;
    const n = data.length;
    this.length += n;
    if (this.fill) {
      const take = Math.min(64 - this.fill, n);
      this.buf.set(data.subarray(0, take), this.fill);
      this.fill += take;
      pos = take;
      if (this.fill < 64) return this;
      compressBytes(this.H, this.buf, 0);
      this.fill = 0;
    }
    for (; pos + 64 <= n; pos += 64) compressBytes(this.H, data, pos);
    if (pos < n) {
      this.buf.set(data.subarray(pos), 0);
      this.fill = n - pos;
    }
    return this;
  }

  digest() {
    const bits = this.length * 8;
    const tail = new Uint8Array(this.fill < 56 ? 64 : 128);
    tail.set(this.buf.subarray(0, this.fill));
    tail[this.fill] = 0x80;
    const view = new DataView(tail.buffer);
    view.setUint32(tail.length - 4, bits >>> 0);
    view.setUint32(tail.length - 8, Math.floor(bits / 0x100000000));
    for (let off = 0; off < tail.length; off += 64) compressBytes(this.H, tail, off);
    const out = new Uint8Array(32);
    const o = new DataView(out.buffer);
    for (let i = 0; i < 8; i += 1) o.setUint32(i * 4, this.H[i] >>> 0);
    return out;
  }
}

function sha256(bytes) {
  return new Sha256().update(bytes).digest();
}

/* Estados HMAC precalculados por clave (ipad/opad): cada bloque del flujo cuesta 2 compresiones. */
const HMAC_PADS = new WeakMap();

function hmacPads(keyBytes) {
  let pads = HMAC_PADS.get(keyBytes);
  if (pads) return pads;
  let key = keyBytes;
  if (key.length > 64) key = sha256(key);
  const block = new Uint8Array(64);
  block.set(key);
  const ipad = new Uint8Array(64);
  const opad = new Uint8Array(64);
  for (let i = 0; i < 64; i += 1) {
    ipad[i] = block[i] ^ 0x36;
    opad[i] = block[i] ^ 0x5c;
  }
  const inner = new Int32Array(SHA_IV);
  compressBytes(inner, ipad, 0);
  const outer = new Int32Array(SHA_IV);
  compressBytes(outer, opad, 0);
  pads = { inner, outer };
  HMAC_PADS.set(keyBytes, pads);
  return pads;
}

class Hmac {
  constructor(keyBytes) {
    this.pads = hmacPads(keyBytes);
    this.inner = new Sha256(this.pads.inner, 64);
  }

  update(data) {
    this.inner.update(data);
    return this;
  }

  digest() {
    return new Sha256(this.pads.outer, 64).update(this.inner.digest()).digest();
  }
}

function hmacSha256(keyBytes, data) {
  return new Hmac(keyBytes).update(data).digest();
}

function concatBytes(parts) {
  const size = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(size);
  let at = 0;
  parts.forEach((part) => {
    out.set(part, at);
    at += part.length;
  });
  return out;
}

/* XOR con el flujo HMAC(key, nonce || contador) sin arrays intermedios. */
function xorStream(key, nonce, src, dst) {
  const { inner, outer } = hmacPads(key);
  const H = new Int32Array(8);
  const W = new Int32Array(64);
  const n0 = (nonce[0] << 24) | (nonce[1] << 16) | (nonce[2] << 8) | nonce[3];
  const n1 = (nonce[4] << 24) | (nonce[5] << 16) | (nonce[6] << 8) | nonce[7];
  const n2 = (nonce[8] << 24) | (nonce[9] << 16) | (nonce[10] << 8) | nonce[11];
  const length = src.length;
  for (let counter = 0, pos = 0; pos < length; counter += 1, pos += 32) {
    H.set(inner);
    W[0] = n0; W[1] = n1; W[2] = n2; W[3] = counter; W[4] = 0x80000000;
    for (let i = 5; i < 15; i += 1) W[i] = 0;
    W[15] = (64 + 16) * 8;
    compressWords(H, W);
    for (let i = 0; i < 8; i += 1) W[i] = H[i];
    W[8] = 0x80000000;
    for (let i = 9; i < 15; i += 1) W[i] = 0;
    W[15] = (64 + 32) * 8;
    H.set(outer);
    compressWords(H, W);
    const take = Math.min(32, length - pos);
    for (let i = 0; i < take; i += 1) {
      const word = H[i >> 2];
      dst[pos + i] = src[pos + i] ^ ((word >>> (24 - (i & 3) * 8)) & 255);
    }
  }
  return dst;
}

function keystream(key, nonce, length) {
  return xorStream(key, nonce, new Uint8Array(length), new Uint8Array(length));
}

function b64urlToBytes(text) {
  const pad = text.length % 4 === 0 ? "" : "=".repeat(4 - (text.length % 4));
  const bin = atob(text.replace(/-/g, "+").replace(/_/g, "/") + pad);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
}

const LZ2 = new Uint8Array([76, 90, 50]);

function sealBytes(data, key) {
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const out = new Uint8Array(15 + data.length + 16);
  out.set(LZ2, 0);
  out.set(nonce, 3);
  xorStream(key, nonce, data, out.subarray(15, 15 + data.length));
  const tag = new Hmac(key).update(out.subarray(0, 15 + data.length)).digest();
  out.set(tag.subarray(0, 16), 15 + data.length);
  return out;
}

function openSeal(blob, key) {
  if (blob.length < 31 || blob[0] !== 76 || blob[1] !== 90 || blob[2] !== 50) throw new Error("cifrado");
  const nonce = blob.subarray(3, 15);
  const tag = blob.subarray(blob.length - 16);
  const expect = new Hmac(key).update(blob.subarray(0, blob.length - 16)).digest();
  let diff = 0;
  for (let i = 0; i < 16; i += 1) diff |= tag[i] ^ expect[i];
  if (diff) throw new Error("cifrado");
  const ct = blob.subarray(15, blob.length - 16);
  return xorStream(key, nonce, ct, new Uint8Array(ct.length));
}

function sealText(text, key) {
  return sealBytes(new TextEncoder().encode(text), key);
}

function openText(blob, key) {
  return new TextDecoder().decode(openSeal(blob, key));
}

/* Claves y firma de peticiones. Mismo formato que protocol.py. */
function deriveKey(master, label) {
  return hmacSha256(master, new TextEncoder().encode(label));
}

function toHex(bytes) {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function signRequest(authKey, method, path, stamp, nonce, length) {
  const text = `${method}\n${path}\n${stamp}\n${nonce}\n${length}`;
  return toHex(hmacSha256(authKey, new TextEncoder().encode(text)));
}
