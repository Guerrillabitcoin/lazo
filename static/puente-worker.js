/* Cifra y resume los trozos del puente fuera del hilo de la página, para que no se congele. */
importScripts("/seal.js");
const hashes = new Map();

function hasher(tid) {
  if (!hashes.has(tid)) hashes.set(tid, new Sha256());
  return hashes.get(tid);
}

self.onmessage = (event) => {
  const { op, tid, buf, key, seq } = event.data;
  try {
    if (op === "seal") {
      const plain = new Uint8Array(buf);
      hasher(tid).update(plain);
      const out = key ? sealBytes(plain, key) : plain;
      self.postMessage({ seq, buf: out.buffer }, [out.buffer]);
    } else if (op === "hash") {
      hasher(tid).update(new Uint8Array(buf));
      self.postMessage({ seq });
    } else if (op === "open") {
      const blob = new Uint8Array(buf);
      const plain = key ? openSeal(blob, key) : blob;
      hasher(tid).update(plain);
      self.postMessage({ seq, buf: plain.buffer }, [plain.buffer]);
    } else if (op === "digest") {
      const hex = toHex(hasher(tid).digest());
      hashes.delete(tid);
      self.postMessage({ seq, hex });
    } else if (op === "drop") {
      hashes.delete(tid);
      self.postMessage({ seq });
    }
  } catch (err) {
    self.postMessage({ seq, error: String((err && err.message) || err) });
  }
};
