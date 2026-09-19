#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const PREFIX = Buffer.from("HEPTA-CANONICAL-DIGEST-V1\\0", "utf8");
const MAX_COLLECTION = 256 * 1024;
const TOKEN = /^[a-z0-9._-]+$/;
const TYPE_TAGS = new Map([
  ["bytes", 1],
  ["text", 2],
  ["u64", 3],
  ["i64", 4],
  ["bool", 5],
  ["digest32", 6],
  ["stable_id", 7],
]);

function u16(value) {
  const buffer = Buffer.alloc(2);
  buffer.writeUInt16BE(value);
  return buffer;
}

function u32(value) {
  const buffer = Buffer.alloc(4);
  buffer.writeUInt32BE(value);
  return buffer;
}

function valueBytes(field) {
  switch (field.type) {
    case "bytes":
      return Buffer.from(field.value, "hex");
    case "text":
    case "stable_id":
      return Buffer.from(field.value, "utf8");
    case "u64": {
      const buffer = Buffer.alloc(8);
      buffer.writeBigUInt64BE(BigInt(field.value));
      return buffer;
    }
    case "i64": {
      const buffer = Buffer.alloc(8);
      buffer.writeBigInt64BE(BigInt(field.value));
      return buffer;
    }
    case "bool":
      if (typeof field.value !== "boolean") throw new Error("bool vector must use JSON boolean");
      return Buffer.from([field.value ? 1 : 0]);
    case "digest32": {
      const buffer = Buffer.from(field.value, "hex");
      if (buffer.length !== 32) throw new Error("digest32 vector must be 32 bytes");
      return buffer;
    }
    default:
      throw new Error("unknown canonical value type: " + field.type);
  }
}

function encode(vector) {
  const domain = Buffer.from(vector.domain, "ascii");
  if (!vector.domain || domain.length > 128 || !TOKEN.test(vector.domain)) {
    throw new Error("invalid domain: " + vector.domain);
  }
  if (vector.fields.length > 1024) throw new Error("too many fields");
  const names = vector.fields.map((field) => field.name);
  const sorted = [...names].sort();
  if (names.some((name, index) => name !== sorted[index]) || new Set(names).size !== names.length) {
    throw new Error("field names must be strictly sorted and unique");
  }

  const parts = [PREFIX, u16(domain.length), domain, u16(vector.fields.length)];
  for (const field of vector.fields) {
    const name = Buffer.from(field.name, "ascii");
    if (!field.name || name.length > 128 || !TOKEN.test(field.name)) {
      throw new Error("invalid field name: " + field.name);
    }
    const payload = valueBytes(field);
    const tag = TYPE_TAGS.get(field.type);
    if (tag === undefined) throw new Error("unknown type tag: " + field.type);
    parts.push(u16(name.length), name, Buffer.from([tag]), u32(payload.length), payload);
  }

  const output = Buffer.concat(parts);
  if (output.length > MAX_COLLECTION) throw new Error("canonical collection exceeds 256 KiB");
  return output;
}

const here = dirname(fileURLToPath(import.meta.url));
const vectorPath = resolve(here, "../codex-rs/hepta-types/testdata/canonical_digest_v1_vectors.json");
const document = JSON.parse(readFileSync(vectorPath, "utf8"));
if (document.schema !== "hepta.platform-types.canonical-digest-v1.vectors" || document.schemaVersion !== 1) {
  throw new Error("unexpected vector schema");
}
if (!document.vectors.length) throw new Error("vector corpus must not be empty");

for (const vector of document.vectors) {
  const encoded = encode(vector);
  if (encoded.toString("hex") !== vector.canonicalHex) throw new Error(vector.name + ": canonical bytes");
  const digest = createHash("sha256").update(encoded).digest("hex");
  if (digest !== vector.sha256) throw new Error(vector.name + ": sha256");
}
console.log("verified " + document.vectors.length + " platform.types canonical vectors in Node/TypeScript-compatible JS");
