#!/usr/bin/env node
"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const vectorPath = path.join(
  root,
  "docs/lane-a-foundation/platform.types/CANONICAL_DIGEST_V1.json",
);
const prefix = Buffer.from("HEPTA-CANONICAL-DIGEST-V1\0", "utf8");

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

function u64(value) {
  const out = Buffer.alloc(8);
  out.writeBigUInt64BE(BigInt(value));
  return out;
}

function i64(value) {
  const out = Buffer.alloc(8);
  out.writeBigInt64BE(BigInt(value));
  return out;
}

function framed16(value) {
  if (value.length > 0xffff) {
    throw new Error("u16 length overflow");
  }
  return Buffer.concat([u16(value.length), value]);
}

function framed32(value) {
  if (value.length > 0xffffffff) {
    throw new Error("u32 length overflow");
  }
  return Buffer.concat([u32(value.length), value]);
}

function compareUtf8(left, right) {
  return Buffer.compare(Buffer.from(left, "utf8"), Buffer.from(right, "utf8"));
}

function encodeValue(value) {
  switch (value.type) {
    case "bytes":
      return Buffer.concat([Buffer.from([1]), framed32(Buffer.from(value.hex, "hex"))]);
    case "text":
      return Buffer.concat([
        Buffer.from([2]),
        framed32(Buffer.from(value.value, "utf8")),
      ]);
    case "u64":
      return Buffer.concat([Buffer.from([3]), u64(value.value)]);
    case "i64":
      return Buffer.concat([Buffer.from([4]), i64(value.value)]);
    case "bool":
      return Buffer.from([5, value.value ? 1 : 0]);
    case "digest": {
      const digest = Buffer.from(value.hex, "hex");
      if (digest.length !== 32) {
        throw new Error("digest must be 32 bytes");
      }
      return Buffer.concat([Buffer.from([6]), digest]);
    }
    case "array":
      return Buffer.concat([
        Buffer.from([7]),
        u32(value.items.length),
        ...value.items.map(encodeValue),
      ]);
    case "map": {
      const entries = [...value.entries].sort((a, b) => compareUtf8(a.key, b.key));
      const keys = entries.map((item) => item.key);
      if (new Set(keys).size !== keys.length) {
        throw new Error("duplicate map key");
      }
      return Buffer.concat([
        Buffer.from([8]),
        u32(entries.length),
        ...entries.flatMap((item) => [
          framed16(Buffer.from(item.key, "utf8")),
          encodeValue(item.value),
        ]),
      ]);
    }
    default:
      throw new Error(`unknown canonical value type: ${value.type}`);
  }
}

function encodeVector(vector) {
  const fields = [...vector.fields].sort((a, b) => compareUtf8(a.name, b.name));
  const names = fields.map((item) => item.name);
  if (new Set(names).size !== names.length) {
    throw new Error("duplicate field name");
  }
  if (vector.encodingSchemaVersion <= 0) {
    throw new Error("schema version must be nonzero");
  }
  return Buffer.concat([
    prefix,
    framed16(Buffer.from(vector.typeId, "utf8")),
    u32(vector.encodingSchemaVersion),
    u16(fields.length),
    ...fields.flatMap((item) => [
      framed16(Buffer.from(item.name, "utf8")),
      encodeValue(item.value),
    ]),
  ]);
}

const vector = JSON.parse(fs.readFileSync(vectorPath, "utf8"));
const encoded = encodeVector(vector);
const expected = Buffer.from(vector.encodedHex, "hex");
if (!encoded.equals(expected)) {
  throw new Error("platform.types vector bytes differ from frozen encodedHex");
}
if (encoded.length !== vector.encodedLength) {
  throw new Error("platform.types vector encodedLength mismatch");
}
const digest = crypto.createHash("sha256").update(encoded).digest("hex");
if (digest !== vector.sha256) {
  throw new Error("platform.types vector SHA-256 mismatch");
}
process.stdout.write(
  `platform.types canonical V1 node vector: ok (${encoded.length} bytes, ${digest})\n`,
);
