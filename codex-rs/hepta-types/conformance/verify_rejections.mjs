// Independent raw-byte rejection oracle for Platform Types canonical V1.
import fs from "node:fs";

const DOC = JSON.parse(
  fs.readFileSync("codex-rs/hepta-types/CANONICAL_V1_CONFORMANCE.json", "utf8"),
);
const DOMAIN = Buffer.from(DOC.domain, "utf8");
const MAX_BYTES = DOC.maxEncodedBytes;
const MAX_ITEMS = DOC.maxContainerItems;
const MAX_DEPTH = DOC.maxDepth;
const UTF8 = new TextDecoder("utf-8", { fatal: true });

class Reader {
  constructor(data) {
    this.data = data;
    this.offset = 0;
  }
  take(n) {
    const end = this.offset + n;
    if (end > this.data.length) throw new Error("truncated");
    const out = this.data.subarray(this.offset, end);
    this.offset = end;
    return out;
  }
  n(size) {
    let value = 0;
    for (const byte of this.take(size)) value = value * 256 + byte;
    return value;
  }
  l16() {
    return this.take(this.n(2));
  }
  l32() {
    return this.take(this.n(4));
  }
}

function ascii(raw, label) {
  for (const byte of raw) if (byte > 0x7f) throw new Error(label);
  return raw.toString("ascii");
}

function validModule(raw) {
  const value = ascii(raw, "module");
  const parts = value.split(".");
  if (
    parts.length === 0 ||
    parts.some((part) => !/^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$/.test(part))
  ) {
    throw new Error("module");
  }
}

function validLocal(raw) {
  const value = ascii(raw, "local");
  if (!/^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$/.test(value)) {
    throw new Error("local");
  }
}

function validNamespaced(raw) {
  const separator = raw.indexOf(0x3a);
  if (separator <= 0 || separator !== raw.lastIndexOf(0x3a)) {
    throw new Error("type id");
  }
  validModule(raw.subarray(0, separator));
  validLocal(raw.subarray(separator + 1));
}

function validStable(raw) {
  const value = ascii(raw, "stable id");
  if (!/^[A-Za-z0-9._:-]+$/.test(value)) throw new Error("stable id");
}

function validLabel(raw) {
  const value = ascii(raw, "label");
  if (
    raw.length === 0 ||
    raw.length > 128 ||
    !/^[a-z0-9](?:[a-z0-9._:-]*[a-z0-9])?$/.test(value)
  ) {
    throw new Error("label");
  }
}

function validateValue(r, depth = 0) {
  const tag = r.n(1);
  if (tag === 1) {
    const value = r.n(1);
    if (value !== 0 && value !== 1) throw new Error("invalid bool");
    return;
  }
  if (tag === 2) {
    r.take(8);
    return;
  }
  if (tag === 3) {
    r.take(16);
    return;
  }
  if (tag === 4) {
    r.take(8);
    return;
  }
  if (tag === 5) {
    r.l32();
    return;
  }
  if (tag === 6) {
    const raw = r.l32();
    let text;
    try {
      text = UTF8.decode(raw);
    } catch (_) {
      throw new Error("invalid text");
    }
    if (text.includes("\0")) throw new Error("NUL text");
    return;
  }
  if (tag === 7) {
    r.take(32);
    return;
  }
  if (tag === 8) {
    validStable(r.l16());
    return;
  }
  if (tag === 9 || tag === 10) {
    if (depth >= MAX_DEPTH) throw new Error("depth");
    const count = r.n(4);
    if (count > MAX_ITEMS) throw new Error("items");
    let previous = null;
    for (let i = 0; i < count; i += 1) {
      if (tag === 10) {
        const key = r.l16();
        validLabel(key);
        if (previous && Buffer.compare(key, previous) <= 0) {
          throw new Error("map order");
        }
        previous = key;
      }
      validateValue(r, depth + 1);
    }
    return;
  }
  throw new Error("invalid tag");
}

function validateRaw(raw) {
  if (raw.length > MAX_BYTES) throw new Error("size");
  const r = new Reader(raw);
  if (
    r.take(4).toString("ascii") !== "HPTC" ||
    r.n(2) !== DOC.encodingVersion
  ) {
    throw new Error("header");
  }
  if (!r.l16().equals(DOMAIN)) throw new Error("domain");
  validNamespaced(r.l16());
  if (r.n(4) === 0) throw new Error("schema");
  const count = r.n(4);
  if (count > MAX_ITEMS) throw new Error("fields");
  let previous = null;
  for (let i = 0; i < count; i += 1) {
    const name = r.l16();
    validLabel(name);
    if (previous && Buffer.compare(name, previous) <= 0) {
      throw new Error("field order");
    }
    previous = name;
    validateValue(r);
  }
  if (r.offset !== raw.length) throw new Error("trailing");
}

function u16(value) {
  const out = Buffer.alloc(2);
  out.writeUInt16BE(value);
  return out;
}

function u32(value) {
  const out = Buffer.alloc(4);
  out.writeUInt32BE(value);
  return out;
}

function framed16(value) {
  return Buffer.concat([u16(value.length), value]);
}

function header(schemaVersion, fieldCount) {
  return Buffer.concat([
    Buffer.from("HPTC", "ascii"),
    u16(DOC.encodingVersion),
    framed16(DOMAIN),
    framed16(Buffer.from("platform.types:negative", "ascii")),
    u32(schemaVersion),
    u32(fieldCount),
  ]);
}

function boolValue(value) {
  return Buffer.from([1, value]);
}

function u64Value(value) {
  const out = Buffer.alloc(9);
  out[0] = 2;
  out.writeBigUInt64BE(BigInt(value), 1);
  return out;
}

function rejectionBytes(c) {
  if (c.kind === "raw_reject") {
    return Buffer.from(c.encodingHex, "hex");
  }
  if (c.kind === "duplicate_field") {
    return Buffer.concat([
      header(c.schemaVersion, 2),
      framed16(Buffer.from("a", "ascii")),
      u64Value(1),
      framed16(Buffer.from("a", "ascii")),
      u64Value(2),
    ]);
  }
  if (c.kind === "duplicate_map_key") {
    const map = Buffer.concat([
      Buffer.from([10]),
      u32(2),
      framed16(Buffer.from("a", "ascii")),
      boolValue(0),
      framed16(Buffer.from("a", "ascii")),
      boolValue(1),
    ]);
    return Buffer.concat([
      header(c.schemaVersion, 1),
      framed16(Buffer.from("map", "ascii")),
      map,
    ]);
  }
  if (c.kind === "zero_schema_version") {
    return header(0, 0);
  }
  if (c.kind === "oversize_bytes") {
    const payload = Buffer.concat([
      Buffer.from([5]),
      u32(c.payloadBytes),
      Buffer.alloc(c.payloadBytes),
    ]);
    return Buffer.concat([
      header(c.schemaVersion, 1),
      framed16(Buffer.from("payload", "ascii")),
      payload,
    ]);
  }
  if (c.kind === "depth_overflow") {
    let value = boolValue(0);
    for (let i = 0; i < c.depth; i += 1) {
      value = Buffer.concat([Buffer.from([9]), u32(1), value]);
    }
    return Buffer.concat([
      header(c.schemaVersion, 1),
      framed16(Buffer.from("nested", "ascii")),
      value,
    ]);
  }
  throw new Error("unknown rejection kind: " + c.kind);
}

for (const c of DOC.rejections) {
  const raw = rejectionBytes(c);
  let rejected = false;
  try {
    validateRaw(raw);
  } catch (_) {
    rejected = true;
  }
  if (!rejected) {
    throw new Error(c.id + ": raw-byte rejection oracle accepted invalid bytes");
  }
}

console.log(
  "platform.types Node raw rejection vectors: " +
    DOC.rejections.length +
    " rejected",
);
