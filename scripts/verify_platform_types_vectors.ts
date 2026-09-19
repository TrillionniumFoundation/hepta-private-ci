#!/usr/bin/env -S node --experimental-strip-types --no-warnings
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

type CanonicalFieldType =
  | "bytes"
  | "text"
  | "u64"
  | "i64"
  | "bool"
  | "digest32"
  | "stable_id";

interface VectorField {
  name: string;
  type: CanonicalFieldType;
  value: string | boolean;
}

interface CanonicalVector {
  name: string;
  domain: string;
  fields: VectorField[];
  canonicalHex: string;
  sha256: string;
}

interface VectorDocument {
  schema: string;
  schemaVersion: number;
  vectors: CanonicalVector[];
}

const PREFIX = Buffer.from("HEPTA-CANONICAL-DIGEST-V1\0", "utf8");
const MAX_COLLECTION = 256 * 1024;
const TOKEN = /^[a-z0-9._-]+$/;
const TYPE_TAGS: ReadonlyMap<CanonicalFieldType, number> = new Map([
  ["bytes", 1],
  ["text", 2],
  ["u64", 3],
  ["i64", 4],
  ["bool", 5],
  ["digest32", 6],
  ["stable_id", 7],
]);

function u16(value: number): Buffer {
  const buffer = Buffer.alloc(2);
  buffer.writeUInt16BE(value);
  return buffer;
}

function u32(value: number): Buffer {
  const buffer = Buffer.alloc(4);
  buffer.writeUInt32BE(value);
  return buffer;
}

function stringValue(field: VectorField): string {
  if (typeof field.value !== "string") {
    throw new Error(field.name + ": expected string value for " + field.type);
  }
  return field.value;
}

function valueBytes(field: VectorField): Buffer {
  switch (field.type) {
    case "bytes":
      return Buffer.from(stringValue(field), "hex");
    case "text":
    case "stable_id":
      return Buffer.from(stringValue(field), "utf8");
    case "u64": {
      const buffer = Buffer.alloc(8);
      buffer.writeBigUInt64BE(BigInt(stringValue(field)));
      return buffer;
    }
    case "i64": {
      const buffer = Buffer.alloc(8);
      buffer.writeBigInt64BE(BigInt(stringValue(field)));
      return buffer;
    }
    case "bool":
      if (typeof field.value !== "boolean") {
        throw new Error(field.name + ": bool vector must use JSON boolean");
      }
      return Buffer.from([field.value ? 1 : 0]);
    case "digest32": {
      const buffer = Buffer.from(stringValue(field), "hex");
      if (buffer.length !== 32) {
        throw new Error(field.name + ": digest32 vector must be 32 bytes");
      }
      return buffer;
    }
  }
}

function encode(vector: CanonicalVector): Buffer {
  const domain = Buffer.from(vector.domain, "ascii");
  if (!vector.domain || domain.length > 128 || !TOKEN.test(vector.domain)) {
    throw new Error("invalid domain: " + vector.domain);
  }
  if (vector.fields.length > 1024) {
    throw new Error("too many fields");
  }

  const names = vector.fields.map((field) => field.name);
  const sorted = [...names].sort();
  if (
    names.some((name, index) => name !== sorted[index]) ||
    new Set(names).size !== names.length
  ) {
    throw new Error("field names must be strictly sorted and unique");
  }

  const parts: Buffer[] = [
    PREFIX,
    u16(domain.length),
    domain,
    u16(vector.fields.length),
  ];
  for (const field of vector.fields) {
    const name = Buffer.from(field.name, "ascii");
    if (!field.name || name.length > 128 || !TOKEN.test(field.name)) {
      throw new Error("invalid field name: " + field.name);
    }
    const payload = valueBytes(field);
    const tag = TYPE_TAGS.get(field.type);
    if (tag === undefined) {
      throw new Error("unknown type tag: " + field.type);
    }
    parts.push(
      u16(name.length),
      name,
      Buffer.from([tag]),
      u32(payload.length),
      payload,
    );
  }

  const output = Buffer.concat(parts);
  if (output.length > MAX_COLLECTION) {
    throw new Error("canonical collection exceeds 256 KiB");
  }
  return output;
}

const here = dirname(fileURLToPath(import.meta.url));
const vectorPath = resolve(
  here,
  "../codex-rs/hepta-types/testdata/canonical_digest_v1_vectors.json",
);
const document = JSON.parse(
  readFileSync(vectorPath, "utf8"),
) as VectorDocument;

if (
  document.schema !== "hepta.platform-types.canonical-digest-v1.vectors" ||
  document.schemaVersion !== 1
) {
  throw new Error("unexpected vector schema");
}
if (!document.vectors.length) {
  throw new Error("vector corpus must not be empty");
}

for (const vector of document.vectors) {
  const encoded = encode(vector);
  if (encoded.toString("hex") !== vector.canonicalHex) {
    throw new Error(vector.name + ": canonical bytes");
  }
  const digest = createHash("sha256").update(encoded).digest("hex");
  if (digest !== vector.sha256) {
    throw new Error(vector.name + ": sha256");
  }
}

console.log(
  "verified " +
    document.vectors.length +
    " platform.types canonical vectors in TypeScript",
);
