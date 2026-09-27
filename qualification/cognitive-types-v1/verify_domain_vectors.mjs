#!/usr/bin/env node
"use strict";

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const vectorPath = path.join(
  root,
  "qualification/cognitive-types-v1/golden-vectors-v2.json",
);
const vectors = JSON.parse(fs.readFileSync(vectorPath, "utf8"));
const DOMAIN = Buffer.from("hepta.cognitive.contract-domain.v1\0", "utf8");
const LEGACY_DOMAIN = Buffer.from(
  "hepta.cognitive.contract.canonical-json.v1\0",
  "utf8",
);
const INTENT_DOMAIN = Buffer.from(
  "hepta.cognitive.memory-write-intent.binding.v1\0",
  "utf8",
);
const rejectionCodes = Object.freeze({
  authorization_rejected: 0,
  snapshot_conflict: 1,
  writer_fence_mismatch: 2,
  candidate_rejected: 3,
  capacity_exceeded: 4,
  duplicate_intent_conflict: 5,
  indeterminate: 6,
});

function sorted(value) {
  if (Array.isArray(value)) {
    return value.map(sorted);
  }
  if (value !== null && typeof value === "object") {
    const output = {};
    for (const key of Object.keys(value).sort()) {
      output[key] = sorted(value[key]);
    }
    return output;
  }
  return value;
}

function canonical(value) {
  return Buffer.from(JSON.stringify(sorted(value)), "utf8");
}

function sha256(...parts) {
  const digest = crypto.createHash("sha256");
  for (const part of parts) {
    digest.update(part);
  }
  return digest.digest();
}

function u32(value) {
  const output = Buffer.alloc(4);
  output.writeUInt32BE(Number(value));
  return output;
}

function u64(value) {
  const output = Buffer.alloc(8);
  output.writeBigUInt64BE(BigInt(value));
  return output;
}

function text(value) {
  const bytes = Buffer.from(value, "utf8");
  return Buffer.concat([u64(bytes.length), bytes]);
}

function domainDigest(vector, payload) {
  return sha256(
    DOMAIN,
    Buffer.from(vector.schemaId, "utf8"),
    Buffer.from([0]),
    u32(vector.schemaVersion),
    Buffer.from([0]),
    Buffer.from(vector.contractId, "utf8"),
    Buffer.from([0]),
    Buffer.from(vector.canonicalizationId, "utf8"),
    Buffer.from([0]),
    Buffer.from(vector.unicodePolicyId, "utf8"),
    Buffer.from([0]),
    Buffer.from(vector.digestAlgorithmId, "utf8"),
    Buffer.from([0]),
    payload,
  );
}

function requireEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message}: ${actual} != ${expected}`);
  }
}

function verifyReceipt(vector) {
  const payload = vector.payload;
  const canonicalPayload = canonical(payload);
  requireEqual(
    canonicalPayload.toString("utf8"),
    vector.canonicalPayloadUtf8,
    "canonical receipt payload",
  );
  requireEqual(
    canonical({
      schema: vector.schemaId,
      schemaVersion: vector.schemaVersion,
      contract: vector.contractId,
      payload,
    }).toString("utf8"),
    vector.canonicalWireUtf8,
    "canonical receipt envelope",
  );

  const outcome = payload.outcome;
  if (outcome.state !== "rejected") {
    throw new Error("golden receipt must use tagged rejection");
  }
  const intentDigest = sha256(
    INTENT_DOMAIN,
    text(payload.intentId),
    Buffer.from(payload.candidateDigest, "hex"),
    Buffer.from(payload.expectedSnapshotDigest, "hex"),
    Buffer.from(payload.writerFenceDigest, "hex"),
    Buffer.from(payload.authorizationDigest, "hex"),
  );
  requireEqual(
    intentDigest.toString("hex"),
    payload.intentDigest,
    "intent binding digest",
  );

  const observed = outcome.observedSnapshotDigest;
  const binding = Buffer.concat([
    Buffer.from(vector.schemaId, "utf8"),
    Buffer.from([0]),
    u32(vector.schemaVersion),
    Buffer.from([0]),
    text(payload.intentId),
    intentDigest,
    Buffer.from(payload.candidateDigest, "hex"),
    Buffer.from(payload.authorizationDigest, "hex"),
    Buffer.from(payload.writerFenceDigest, "hex"),
    Buffer.from(payload.expectedSnapshotDigest, "hex"),
    u64(payload.expectedMemoryFrontier),
    text(payload.writerId),
    u64(payload.issuedAtUnixMs),
    Buffer.from([1, rejectionCodes[outcome.rejectionCode]]),
    Buffer.from([observed === undefined || observed === null ? 0 : 1]),
    observed === undefined || observed === null
      ? Buffer.alloc(0)
      : Buffer.from(observed, "hex"),
    Buffer.from([outcome.retryable ? 1 : 0]),
  ]);
  const receiptDigest = domainDigest(vector, binding).toString("hex");
  requireEqual(receiptDigest, payload.receiptDigest, "self-bound receipt digest");
  requireEqual(receiptDigest, vector.receiptDigestSha256, "receipt digest vector");

  const legacy = sha256(
    LEGACY_DOMAIN,
    Buffer.from(vector.contractId, "utf8"),
    Buffer.from([0]),
    canonicalPayload,
  ).toString("hex");
  requireEqual(legacy, vector.legacyCanonicalDigestSha256, "legacy digest");
  requireEqual(
    domainDigest(vector, canonicalPayload).toString("hex"),
    vector.domainBoundDigestSha256,
    "domain-bound digest",
  );
}

function verifyUnicode(entries) {
  const digests = new Set();
  const bytes = new Set();
  for (const entry of entries) {
    const encoded = Buffer.from(entry.text, "utf8");
    requireEqual(encoded.toString("hex"), entry.utf8Hex, `Unicode bytes ${entry.name}`);
    const digest = sha256(encoded).toString("hex");
    requireEqual(digest, entry.sha256, `Unicode digest ${entry.name}`);
    digests.add(digest);
    bytes.add(encoded.toString("hex"));
  }
  if (digests.size !== entries.length || bytes.size !== entries.length) {
    throw new Error("Unicode vectors were silently normalized");
  }
}

verifyReceipt(vectors.memoryWriteReceiptRejectedV1);
verifyUnicode(vectors.unicodePreservationV1);
console.log(
  JSON.stringify({
    status: "PASS_COGNITIVE_TYPES_V2_DOMAIN_VECTORS",
    vectorFile: path.relative(root, vectorPath),
    receiptDigest: vectors.memoryWriteReceiptRejectedV1.receiptDigestSha256,
    domainBoundDigest: vectors.memoryWriteReceiptRejectedV1.domainBoundDigestSha256,
  }),
);
