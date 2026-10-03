#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const vector = JSON.parse(readFileSync(join(here, "bound_vector.json"), "utf8"));
const domain = Buffer.from("hepta.cognitive.contract.bound-digest.v1\0", "utf8");

function canonical(value) {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonical).join(",")}]`;
  }
  const keys = Object.keys(value).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}

function component(buffer) {
  const length = Buffer.alloc(8);
  length.writeBigUInt64BE(BigInt(buffer.length));
  return Buffer.concat([length, buffer]);
}

const version = Buffer.alloc(4);
version.writeUInt32BE(vector.schemaVersion);
const payload = Buffer.from(canonical(vector.payload), "utf8");
const material = Buffer.concat([
  domain,
  component(Buffer.from(vector.schema, "utf8")),
  version,
  component(Buffer.from(vector.contract, "utf8")),
  component(Buffer.from(vector.canonicalizationAlgorithm, "utf8")),
  component(payload),
]);
const observed = createHash("sha256").update(material).digest("hex");
if (observed !== vector.expectedBoundDigest) {
  throw new Error(`bound cognitive digest mismatch: ${observed}`);
}
console.log(JSON.stringify({
  status: "PASS_COGNITIVE_TYPES_BOUND_VECTOR_NODE",
  digest: observed,
  canonicalPayloadBytes: payload.length,
}));
