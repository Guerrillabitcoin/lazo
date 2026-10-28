/* Cifrado del puente: HMAC-SHA256 en modo flujo. La clave vive solo en el QR, no viaja. */
const SHA = new Uint32Array(64);
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

function rotr(n, x) {
  return (x >>> n) | (x << (32 - n));
}

function sha256(bytes) {
  const bitLen = bytes.length * 8;
  const withOne = bytes.length + 1;
  const zeros = (64 - ((withOne + 8) % 64)) % 64;
  const buf = new Uint8Array(withOne + zeros + 8);
  buf.set(bytes);
  buf[bytes.length] = 0x80;
  const view = new DataView(buf.buffer);
  view.setUint32(buf.length - 4, bitLen >>> 0);
  view.setUint32(buf.length - 8, Math.floor(bitLen / 0x100000000));
  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;
  for (let off = 0; off < buf.length; off += 64) {
    for (let i = 0; i < 16; i += 1) SHA[i] = view.getUint32(off + i * 4);
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotr(7, SHA[i - 15]) ^ rotr(18, SHA[i - 15]) ^ (SHA[i - 15] >>> 3);
      const s1 = rotr(17, SHA[i - 2]) ^ rotr(19, SHA[i - 2]) ^ (SHA[i - 2] >>> 10);
      SHA[i] = (SHA[i - 16] + s0 + SHA[i - 7] + s1) >>> 0;
    }
    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;
    for (let i = 0; i < 64; i += 1) {
      const S1 = rotr(6, e) ^ rotr(11, e) ^ rotr(25, e);
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K[i] + SHA[i]) >>> 0;
      const S0 = rotr(2, a) ^ rotr(13, a) ^ rotr(22, a);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + t1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) >>> 0;
    }
    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
    h5 = (h5 + f) >>> 0;
    h6 = (h6 + g) >>> 0;
    h7 = (h7 + h) >>> 0;
  }
  const out = new Uint8Array(32);
  const o = new DataView(out.buffer);
  [h0, h1, h2, h3, h4, h5, h6, h7].forEach((word, i) => o.setUint32(i * 4, word));
  return out;
}

function hmacSha256(keyBytes, data) {
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
  const inner = new Uint8Array(64 + data.length);
  inner.set(ipad);
  inner.set(data, 64);
  const outer = new Uint8Array(64 + 32);
  outer.set(opad);
  outer.set(sha256(inner), 64);
  return sha256(outer);
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

function keystream(key, nonce, length) {
  const out = new Uint8Array(length);
  let filled = 0;
  let counter = 0;
  while (filled < length) {
    const block = new Uint8Array(16);
    block.set(nonce);
    block[12] = (counter >>> 24) & 255;
    block[13] = (counter >>> 16) & 255;
    block[14] = (counter >>> 8) & 255;
    block[15] = counter & 255;
    const chunk = hmacSha256(key, block);
    const take = Math.min(32, length - filled);
    out.set(chunk.subarray(0, take), filled);
    filled += take;
    counter += 1;
  }
  return out;
}

function b64urlToBytes(text) {
  const pad = text.length % 4 === 0 ? "" : "=".repeat(4 - (text.length % 4));
  const bin = atob(text.replace(/-/g, "+").replace(/_/g, "/") + pad);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
}

function sealBytes(data, key) {
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const stream = keystream(key, nonce, data.length);
  const ct = new Uint8Array(data.length);
  for (let i = 0; i < data.length; i += 1) ct[i] = data[i] ^ stream[i];
  const tag = hmacSha256(key, concatBytes([new Uint8Array([76, 90, 50]), nonce, ct])).subarray(0, 16);
  return concatBytes([new Uint8Array([76, 90, 50]), nonce, ct, tag]);
}

function openSeal(blob, key) {
  if (blob.length < 31 || blob[0] !== 76 || blob[1] !== 90 || blob[2] !== 50) throw new Error("cifrado");
  const nonce = blob.subarray(3, 15);
  const tag = blob.subarray(blob.length - 16);
  const ct = blob.subarray(15, blob.length - 16);
  const expect = hmacSha256(key, concatBytes([new Uint8Array([76, 90, 50]), nonce, ct])).subarray(0, 16);
  for (let i = 0; i < 16; i += 1) if (tag[i] !== expect[i]) throw new Error("cifrado");
  const stream = keystream(key, nonce, ct.length);
  const plain = new Uint8Array(ct.length);
  for (let i = 0; i < ct.length; i += 1) plain[i] = ct[i] ^ stream[i];
  return plain;
}

function sealText(text, key) {
  return sealBytes(new TextEncoder().encode(text), key);
}

function openText(blob, key) {
  return new TextDecoder().decode(openSeal(blob, key));
}
