// Independent TypeScript oracle for platform.types canonical digest V1.
// The source deliberately uses the JavaScript subset of TypeScript so CI can
// execute it with: node --input-type=module < verify_vectors.ts
import fs from "node:fs";
import crypto from "node:crypto";

const vectorPath = "codex-rs/hepta-types/CANONICAL_V1_CONFORMANCE.json";
const document = JSON.parse(fs.readFileSync(vectorPath, "utf8"));
const DOMAIN = Buffer.from("hepta.platform.types.canonical-digest.v1", "utf8");

function u16(value) {
  const output = Buffer.alloc(2);
  output.writeUInt16BE(value);
  return output;
}

function u32(value) {
  const output = Buffer.alloc(4);
  output.writeUInt32BE(value);
  return output;
}

function label(value) {
  const encoded = Buffer.from(value, "utf8");
  if (
    encoded.length === 0 ||
    encoded.length > 128 ||
    !/^[a-z0-9][a-z0-9._:-]*[a-z0-9]$|^[a-z0-9]$/.test(value)
  ) {
    throw new Error("invalid label");
  }
  return Buffer.concat([u16(encoded.length), encoded]);
}

function unsigned(value, bytes) {
  let current = BigInt(value);
  const output = Buffer.alloc(bytes);
  for (let index = bytes - 1; index >= 0; index -= 1) {
    output[index] = Number(current & 255n);
    current >>= 8n;
  }
  if (current !== 0n) throw new Error("unsigned overflow");
  return output;
}

function signed64(value) {
  const current = BigInt(value);
  const twos = current < 0n ? (1n << 64n) + current : current;
  return unsigned(twos, 8);
}

function encodeValue(value) {
  switch (value.type) {
    case "bool":
      return Buffer.from([0x01, value.value ? 1 : 0]);
    case "u64":
      return Buffer.concat([Buffer.from([0x02]), unsigned(value.value, 8)]);
    case "u128":
      return Buffer.concat([Buffer.from([0x03]), unsigned(value.value, 16)]);
    case "i64":
      return Buffer.concat([Buffer.from([0x04]), signed64(value.value)]);
    case "bytes": {
      const payload = Buffer.from(value.hex, "hex");
      return Buffer.concat([Buffer.from([0x05]), u32(payload.length), payload]);
    }
    case "text": {
      const payload = Buffer.from(value.value, "utf8");
      if (payload.includes(0)) throw new Error("NUL text");
      return Buffer.concat([Buffer.from([0x06]), u32(payload.length), payload]);
    }
    case "digest": {
      const payload = Buffer.from(value.hex, "hex");
      if (payload.length !== 32) throw new Error("digest length");
      return Buffer.concat([Buffer.from([0x07]), payload]);
    }
    case "stable_id": {
      const payload = Buffer.from(value.value, "utf8");
      return Buffer.concat([Buffer.from([0x08]), u16(payload.length), payload]);
    }
    case "array": {
      const items = value.items.map(encodeValue);
      return Buffer.concat([Buffer.from([0x09]), u32(items.length), ...items]);
    }
    case "map": {
      const entries = [...value.entries].sort((a, b) =>
        Buffer.from(a.key).compare(Buffer.from(b.key)),
      );
      if (new Set(entries.map((entry) => entry.key)).size !== entries.length) {
        throw new Error("duplicate map key");
      }
      return Buffer.concat([
        Buffer.from([0x0a]),
        u32(entries.length),
        ...entries.flatMap((entry) => [label(entry.key), encodeValue(entry.value)]),
      ]);
    }
    default:
      throw new Error(`unknown value type: ${value.type}`);
  }
}

function encode(vector) {
  const typeId = Buffer.from(vector.typeId, "utf8");
  const fields = [...vector.fields].sort((a, b) =>
    Buffer.from(a.name).compare(Buffer.from(b.name)),
  );
  if (new Set(fields.map((field) => field.name)).size !== fields.length) {
    throw new Error("duplicate field");
  }
  return Buffer.concat([
    Buffer.from("HPTC", "ascii"),
    u16(1),
    u16(DOMAIN.length),
    DOMAIN,
    u16(typeId.length),
    typeId,
    u32(vector.schemaVersion),
    u32(fields.length),
    ...fields.flatMap((field) => [label(field.name), encodeValue(field.value)]),
  ]);
}

if (Buffer.from(document.domain, "utf8").compare(DOMAIN) !== 0 || document.encodingVersion !== 1) {
  throw new Error("conformance header mismatch");
}

for (const vector of document.vectors) {
  const encoded = encode(vector);
  if (encoded.length !== vector.encodedLength) throw new Error(`${vector.id}: length mismatch`);
  if (encoded.toString("hex") !== vector.encodingHex) throw new Error(`${vector.id}: bytes mismatch`);
  if (crypto.createHash("sha256").update(encoded).digest("hex") !== vector.sha256) {
    throw new Error(`${vector.id}: digest mismatch`);
  }
}
console.log(`platform.types TypeScript canonical vectors: ${document.vectors.length} passed`);
