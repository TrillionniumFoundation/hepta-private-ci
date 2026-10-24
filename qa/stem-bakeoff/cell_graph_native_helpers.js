/* Pure ECMAScript byte helpers: no Node, WebCrypto or browser codecs. */
const CellGraphBytes = (() => {
  function requireValue(ok, message) { if (!ok) throw new Error(message); }
  function utf8(value) {
    requireValue(typeof value === "string", "UTF8 input must be a string");
    const out = [];
    for (let i = 0; i < value.length; i++) {
      let c = value.charCodeAt(i);
      if (c >= 0xd800 && c <= 0xdbff) {
        const next = value.charCodeAt(++i);
        requireValue(next >= 0xdc00 && next <= 0xdfff, "unpaired high surrogate");
        c = 0x10000 + ((c - 0xd800) << 10) + next - 0xdc00;
      } else requireValue(c < 0xdc00 || c > 0xdfff, "unpaired low surrogate");
      if (c < 128) out.push(c);
      else if (c < 2048) out.push(192 | c >> 6, 128 | c & 63);
      else if (c < 65536) out.push(224 | c >> 12, 128 | c >> 6 & 63, 128 | c & 63);
      else out.push(240 | c >> 18, 128 | c >> 12 & 63, 128 | c >> 6 & 63, 128 | c & 63);
    }
    return out;
  }
  function bytes(value) {
    requireValue(Array.isArray(value) || value instanceof Uint8Array, "byte array required");
    for (const v of value) requireValue(Number.isInteger(v) && v >= 0 && v <= 255, "invalid byte");
    return value;
  }
  function text(value) {
    bytes(value); let out = "";
    for (let i = 0; i < value.length;) {
      const first = value[i++]; let cp, n, minimum;
      if (first < 128) { cp = first; n = 0; minimum = 0; }
      else if (first >= 194 && first <= 223) { cp = first & 31; n = 1; minimum = 128; }
      else if (first >= 224 && first <= 239) { cp = first & 15; n = 2; minimum = 2048; }
      else if (first >= 240 && first <= 244) { cp = first & 7; n = 3; minimum = 65536; }
      else throw new Error("invalid UTF8 leading byte");
      requireValue(i + n <= value.length, "truncated UTF8 sequence");
      for (let j = 0; j < n; j++) {
        const b = value[i++]; requireValue(b >= 128 && b <= 191, "invalid UTF8 continuation");
        cp = (cp << 6) | (b & 63);
      }
      requireValue(cp >= minimum && cp <= 0x10ffff && (cp < 0xd800 || cp > 0xdfff), "noncanonical UTF8");
      out += cp <= 0xffff ? String.fromCharCode(cp) : String.fromCharCode(0xd800 + ((cp - 0x10000) >> 10), 0xdc00 + ((cp - 0x10000) & 1023));
    }
    return out;
  }
  function hex(value) { return Array.from(bytes(value), b => b.toString(16).padStart(2, "0")).join(""); }
  function unhex(value) {
    requireValue(typeof value === "string" && /^(?:[0-9a-f]{2})*$/.test(value), "canonical lower-case bytes_hex required");
    const out = []; for (let i = 0; i < value.length; i += 2) out.push(parseInt(value.slice(i, i + 2), 16)); return out;
  }
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  function base64(value) {
    bytes(value); let out = "";
    for (let i = 0; i < value.length; i += 3) {
      const n = (value[i] << 16) | ((value[i + 1] || 0) << 8) | (value[i + 2] || 0);
      out += alphabet[n >>> 18] + alphabet[n >>> 12 & 63] + (i + 1 < value.length ? alphabet[n >>> 6 & 63] : "=") + (i + 2 < value.length ? alphabet[n & 63] : "=");
    }
    return out;
  }
  function unbase64(value) {
    requireValue(typeof value === "string" && /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value), "canonical base64 required");
    const out = [];
    for (let i = 0; i < value.length; i += 4) {
      const n = alphabet.indexOf(value[i]) << 18 | alphabet.indexOf(value[i + 1]) << 12 | (value[i + 2] === "=" ? 0 : alphabet.indexOf(value[i + 2])) << 6 | (value[i + 3] === "=" ? 0 : alphabet.indexOf(value[i + 3]));
      out.push(n >>> 16 & 255); if (value[i + 2] !== "=") out.push(n >>> 8 & 255); if (value[i + 3] !== "=") out.push(n & 255);
    }
    requireValue(base64(out) === value, "nonzero base64 pad bits"); return out;
  }
  const K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
  function sha256(value) {
    bytes(value); requireValue(value.length < 0x20000000, "bounded SHA256 input required");
    const data = Array.from(value); const bits = data.length * 8; data.push(128);
    while (data.length % 64 !== 56) data.push(0);
    data.push(0,0,0,0,(bits >>> 24) & 255,(bits >>> 16) & 255,(bits >>> 8) & 255,bits & 255);
    const H = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    const rotr = (x, n) => (x >>> n) | (x << (32 - n));
    for (let offset = 0; offset < data.length; offset += 64) {
      const W = new Array(64);
      for (let i = 0; i < 16; i++) { const p = offset + 4 * i; W[i] = (data[p] << 24) | (data[p + 1] << 16) | (data[p + 2] << 8) | data[p + 3]; }
      for (let i = 16; i < 64; i++) { const a = W[i-15], b = W[i-2]; W[i] = (W[i-16] + (rotr(a,7)^rotr(a,18)^(a>>>3)) + W[i-7] + (rotr(b,17)^rotr(b,19)^(b>>>10))) | 0; }
      let [a,b,c,d,e,f,g,h] = H;
      for (let i = 0; i < 64; i++) {
        const t1 = (h + (rotr(e,6)^rotr(e,11)^rotr(e,25)) + ((e&f)^(~e&g)) + K[i] + W[i]) | 0;
        const t2 = ((rotr(a,2)^rotr(a,13)^rotr(a,22)) + ((a&b)^(a&c)^(b&c))) | 0;
        h=g;g=f;f=e;e=(d+t1)|0;d=c;c=b;b=a;a=(t1+t2)|0;
      }
      [a,b,c,d,e,f,g,h].forEach((v,i) => { H[i] = (H[i] + v) | 0; });
    }
    return H.map(v => (v >>> 0).toString(16).padStart(8,"0")).join("");
  }
  // Unsafe integer lexemes become strings. The exact native JSON text is retained
  // separately; consumers never reserialize this view as the original receipt.
  function parseJSON(source) {
    requireValue(typeof source === "string", "JSON text required"); let i = 0;
    function ws() { while (i < source.length && /[\x20\t\n\r]/.test(source[i])) i++; }
    function string() {
      const start = i++; let escaped = false;
      while (i < source.length) {
        const c = source[i++];
        if (!escaped && c === '"') { const value = JSON.parse(source.slice(start,i)); utf8(value); return value; }
        if (!escaped && c === "\\") escaped = true; else escaped = false;
      }
      throw new Error("unterminated JSON string");
    }
    function value(depth) {
      requireValue(depth <= 100, "JSON nesting bound exceeded"); ws(); const c = source[i];
      if (c === '"') return string();
      if (c === "{") {
        i++; const out = Object.create(null); ws(); if (source[i] === "}") { i++; return out; }
        while (true) {
          ws(); requireValue(source[i] === '"', "JSON object key required"); const key = string();
          requireValue(!Object.prototype.hasOwnProperty.call(out,key), "duplicate JSON key"); ws(); requireValue(source[i++] === ":", "JSON colon required");
          out[key] = value(depth+1); ws(); const end = source[i++]; if (end === "}") return out; requireValue(end === ",", "JSON comma required");
        }
      }
      if (c === "[") {
        i++; const out = []; ws(); if (source[i] === "]") { i++; return out; }
        while (true) { out.push(value(depth+1)); ws(); const end = source[i++]; if (end === "]") return out; requireValue(end === ",", "JSON comma required"); }
      }
      for (const [token,result] of [["true",true],["false",false],["null",null]]) if (source.slice(i,i+token.length) === token) { i+=token.length; return result; }
      const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(source.slice(i));
      requireValue(Boolean(match), "invalid JSON value"); const raw = match[0]; i += raw.length; const n = Number(raw);
      requireValue(Number.isFinite(n), "nonfinite JSON number");
      return /^-?[0-9]+$/.test(raw) && !Number.isSafeInteger(n) ? raw : n;
    }
    const result = value(0); ws(); requireValue(i === source.length, "trailing JSON data"); return result;
  }
  const json = value => JSON.stringify(value);
  const hashText = value => sha256(utf8(value));
  return {requireValue, utf8, text, hex, unhex, base64, unbase64, sha256, hashText, parseJSON, json};
})();
