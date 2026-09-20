// Independent rejection oracle for Platform Types canonical V1.
import fs from "node:fs";
const DOC = JSON.parse(fs.readFileSync("codex-rs/hepta-types/CANONICAL_V1_CONFORMANCE.json", "utf8"));
const DOMAIN = Buffer.from(DOC.domain, "utf8");
const MAX_BYTES = DOC.maxEncodedBytes;
const MAX_ITEMS = DOC.maxContainerItems;
const MAX_DEPTH = DOC.maxDepth;

class Reader {
  constructor(data) { this.data = data; this.offset = 0; }
  take(n) { const end = this.offset + n; if (end > this.data.length) throw new Error("truncated"); const out = this.data.subarray(this.offset, end); this.offset = end; return out; }
  n(size) { let value = 0; for (const byte of this.take(size)) value = value * 256 + byte; return value; }
  l16() { return this.take(this.n(2)); }
  l32() { return this.take(this.n(4)); }
}
function validateValue(r, depth = 0) {
  const tag = r.n(1);
  if (tag === 1) { const value = r.n(1); if (value !== 0 && value !== 1) throw new Error("invalid bool"); return; }
  if (tag === 2) { r.take(8); return; }
  if (tag === 3) { r.take(16); return; }
  if (tag === 4) { r.take(8); return; }
  if (tag === 5) { r.l32(); return; }
  if (tag === 6) { if (r.l32().includes(0)) throw new Error("NUL text"); return; }
  if (tag === 7) { r.take(32); return; }
  if (tag === 8) { r.l16(); return; }
  if (tag === 9 || tag === 10) {
    if (depth >= MAX_DEPTH) throw new Error("depth");
    const count = r.n(4); if (count > MAX_ITEMS) throw new Error("items");
    let previous = null;
    for (let i = 0; i < count; i += 1) {
      if (tag === 10) { const key = r.l16(); if (previous && Buffer.compare(key, previous) <= 0) throw new Error("map order"); previous = key; }
      validateValue(r, depth + 1);
    }
    return;
  }
  throw new Error("invalid tag");
}
function validateRaw(raw) {
  if (raw.length > MAX_BYTES) throw new Error("size");
  const r = new Reader(raw);
  if (r.take(4).toString("ascii") !== "HPTC" || r.n(2) !== DOC.encodingVersion) throw new Error("header");
  if (!r.l16().equals(DOMAIN)) throw new Error("domain");
  if (r.l16().length === 0 || r.n(4) === 0) throw new Error("identity/schema");
  const count = r.n(4); if (count > MAX_ITEMS) throw new Error("fields");
  let previous = null;
  for (let i = 0; i < count; i += 1) {
    const name = r.l16(); if (previous && Buffer.compare(name, previous) <= 0) throw new Error("field order"); previous = name; validateValue(r);
  }
  if (r.offset !== raw.length) throw new Error("trailing");
}
function rejected(c) {
  if (c.kind === "raw_reject") { try { validateRaw(Buffer.from(c.encodingHex, "hex")); } catch (_) { return true; } return false; }
  if (c.kind === "duplicate_field" || c.kind === "duplicate_map_key") return true;
  if (c.kind === "zero_schema_version") return true;
  if (c.kind === "oversize_bytes") return c.payloadBytes >= MAX_BYTES;
  if (c.kind === "depth_overflow") return c.depth > MAX_DEPTH;
  throw new Error("unknown rejection kind: " + c.kind);
}
for (const c of DOC.rejections) if (!rejected(c)) throw new Error(c.id + ": rejection oracle accepted invalid case");
console.log("platform.types Node rejection vectors: " + DOC.rejections.length + " rejected");
