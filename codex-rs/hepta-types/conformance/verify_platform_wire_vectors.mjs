#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
// The shared parser rejects each decoded duplicate key within its object.
import {MAX_RAW_BYTES, parseStrictJson, assertUnsignedIntegerTokens} from "./platform_types_strict_json.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const VECTORS = JSON.parse(
  fs.readFileSync(path.join(ROOT, "codex-rs/hepta-types/PLATFORM_TYPES_WIRE_CONFORMANCE_V1.json"), "utf8"),
);
const DOMAIN = Buffer.from("hepta.platform.types.canonical-digest.v1");
const STABLE_ID = /^[A-Za-z0-9._:-]+$/;
const DIGEST = /^[0-9a-f]{64}$/;
const U64 = /^(0|[1-9][0-9]*)$/;
const U64_MAX = (1n << 64n) - 1n;
const MAX_HPTC_ITEMS = 4096;
const PROMPT_KEYS = [
  "kind", "compilation_id", "provider_request_digest", "delivered",
  "rejected_reason", "observed_token_positions", "truncation_observed", "legacy_v1_digest",
];
const TOPOLOGY_KEYS = [
  "kind", "proposal_digest", "candidate_id", "candidate_digest",
  "baseline_generation", "candidate_generation", "selected_topology_digest",
  "evaluation_digest", "rollback_predecessor_digest", "changed", "deltas",
];
const DELTA_KEYS = [
  "module_id", "operation", "related_module_ids", "predecessor_digest",
  "candidate_digest", "evidence_digest",
];
const OPERATIONS = new Set(["add", "replace", "retire", "rewire", "split", "merge"]);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}
function u16(value) {
  const output = Buffer.alloc(2); output.writeUInt16BE(value); return output;
}
function u32(value) {
  const output = Buffer.alloc(4); output.writeUInt32BE(value); return output;
}
function u64(value) {
  const output = Buffer.alloc(8); output.writeBigUInt64BE(BigInt(value)); return output;
}
function label(value) {
  const raw = Buffer.from(value); return Buffer.concat([u16(raw.length), raw]);
}
function strictKeys(value, expected, name) {
  assert(value !== null && typeof value === "object" && !Array.isArray(value), `${name}: object`);
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  assert(JSON.stringify(actual) === JSON.stringify(wanted), `${name}: fields`);
  return value;
}
function stableId(value, name) {
  assert(typeof value === "string" && Buffer.byteLength(value) >= 1 && Buffer.byteLength(value) <= 128, `${name}: stable id`);
  assert(STABLE_ID.test(value), `${name}: stable id`);
  return value;
}
function digest(value, name, nonzero = false) {
  assert(typeof value === "string" && DIGEST.test(value), `${name}: digest`);
  if (nonzero) assert(value !== "0".repeat(64), `${name}: zero digest`);
  return value;
}
function canonicalU64(value, name, positive = false) {
  assert(typeof value === "string" && value.length <= 20 && U64.test(value), `${name}: canonical_integer`);
  const result = BigInt(value);
  assert(result <= U64_MAX && (!positive || result !== 0n), `${name}: canonical_integer`);
  return result;
}
function encodeValue(kind, value) {
  if (kind === "bool") return Buffer.from([1, value ? 1 : 0]);
  if (kind === "u64") return Buffer.concat([Buffer.from([2]), u64(value)]);
  if (kind === "text") {
    const raw = Buffer.from(value); return Buffer.concat([Buffer.from([6]), u32(raw.length), raw]);
  }
  if (kind === "digest") return Buffer.concat([Buffer.from([7]), Buffer.from(value, "hex")]);
  if (kind === "stable_id") {
    const raw = Buffer.from(value); return Buffer.concat([Buffer.from([8]), u16(raw.length), raw]);
  }
  if (kind === "array") {
    assert(value.length <= MAX_HPTC_ITEMS, "HPTC: too many items");
    return Buffer.concat([
      Buffer.from([9]), u32(value.length), ...value.map(([itemKind, item]) => encodeValue(itemKind, item)),
    ]);
  }
  throw new Error(`unsupported canonical value: ${kind}`);
}
function hptc(typeId, schemaVersion, fields) {
  const typeRaw = Buffer.from(typeId);
  const entries = Object.entries(fields).sort(([left], [right]) => Buffer.from(left).compare(Buffer.from(right)));
  assert(entries.length <= MAX_HPTC_ITEMS, "HPTC: too many fields");
  const encoded = Buffer.concat([
    Buffer.from("HPTC"), u16(1), u16(DOMAIN.length), DOMAIN,
    u16(typeRaw.length), typeRaw, u32(schemaVersion), u32(entries.length),
    ...entries.map(([name, value]) => Buffer.concat([label(name), encodeValue(...value)])),
  ]);
  assert(encoded.length <= 262144, "HPTC: too large");
  return crypto.createHash("sha256").update(encoded).digest("hex");
}
function promptDigest(input) {
  const value = strictKeys(input, PROMPT_KEYS, "prompt");
  assert(value.kind === "prompt_delivery_observation_v2", "prompt: kind");
  const compilation = stableId(value.compilation_id, "compilation_id");
  const provider = digest(value.provider_request_digest, "provider_request_digest", true);
  assert(typeof value.delivered === "boolean" && typeof value.truncation_observed === "boolean", "prompt: bool");
  let reason = value.rejected_reason;
  if (reason !== null) {
    reason = stableId(reason, "rejected_reason");
    assert(Buffer.byteLength(reason) <= 64, "rejected_reason: bound");
  }
  assert(value.delivered !== (reason !== null), "prompt: disposition");
  let positions = value.observed_token_positions;
  if (positions !== null) {
    assert(Array.isArray(positions) && positions.length >= 1 && positions.length <= MAX_HPTC_ITEMS, "prompt: positions");
    for (const item of positions) assert(Number.isInteger(item) && item >= 0 && item <= 0xFFFF_FFFF, "prompt: positions");
    for (let index = 1; index < positions.length; index += 1) assert(positions[index - 1] < positions[index], "prompt: positions order");
  }
  let legacy = value.legacy_v1_digest;
  if (legacy !== null) legacy = digest(legacy, "legacy_v1_digest", true);
  return hptc("platform.types:prompt-delivery-observation-v2", 2, {
    compilation_id: ["stable_id", compilation],
    delivered: ["bool", value.delivered],
    legacy_v1_digest: ["array", legacy === null ? [] : [["digest", legacy]]],
    observed_token_positions: ["array", positions === null ? [] : positions.map((item) => ["u64", BigInt(item)])],
    provider_request_digest: ["digest", provider],
    rejected_reason: ["array", reason === null ? [] : [["stable_id", reason]]],
    truncation_observed: ["bool", value.truncation_observed],
  });
}
function deltaProjection(input) {
  const value = strictKeys(input, DELTA_KEYS, "topology delta");
  const moduleId = stableId(value.module_id, "module_id");
  assert(OPERATIONS.has(value.operation), "operation");
  assert(Array.isArray(value.related_module_ids) && value.related_module_ids.length <= 256, "related_module_ids");
  const related = value.related_module_ids.map((item) => stableId(item, "related_module_ids"));
  assert(JSON.stringify(related) === JSON.stringify([...new Set(related)].sort()), "related_module_ids: order");
  assert(!related.includes(moduleId), "related_module_ids: self");
  const predecessor = digest(value.predecessor_digest, "predecessor_digest");
  const candidate = digest(value.candidate_digest, "candidate_digest");
  const evidence = digest(value.evidence_digest, "evidence_digest", true);
  const zero = "0".repeat(64);
  let shape;
  if (value.operation === "add") shape = related.length === 0 && predecessor === zero && candidate !== zero;
  else if (value.operation === "retire") shape = related.length === 0 && predecessor !== zero && candidate === zero;
  else if (["replace", "rewire"].includes(value.operation)) shape = related.length === 0 && predecessor !== zero && candidate !== zero && predecessor !== candidate;
  else shape = related.length > 0 && predecessor !== zero && candidate !== zero && predecessor !== candidate;
  assert(shape, "delta shape");
  return [hptc("platform.types:runtime-topology-delta-v1", 1, {
    candidate_digest: ["digest", candidate], evidence_digest: ["digest", evidence],
    module_id: ["stable_id", moduleId], operation: ["text", value.operation],
    predecessor_digest: ["digest", predecessor],
    related_module_ids: ["array", related.map((item) => ["stable_id", item])],
  }), { moduleId, operation: value.operation, related }];
}
function topologyDigest(input) {
  const value = strictKeys(input, TOPOLOGY_KEYS, "topology");
  assert(value.kind === "runtime_topology_candidate_v1", "topology: kind");
  const proposal = digest(value.proposal_digest, "proposal_digest", true);
  const candidateId = stableId(value.candidate_id, "candidate_id");
  const stored = digest(value.candidate_digest, "candidate_digest", true);
  const baseline = canonicalU64(value.baseline_generation, "baseline_generation", true);
  const generation = canonicalU64(value.candidate_generation, "candidate_generation", true);
  assert(generation === baseline + 1n, "generation successor");
  const selected = digest(value.selected_topology_digest, "selected_topology_digest", true);
  const evaluation = digest(value.evaluation_digest, "evaluation_digest", true);
  const rollback = digest(value.rollback_predecessor_digest, "rollback_predecessor_digest", true);
  assert(rollback === selected, "rollback predecessor");
  assert(typeof value.changed === "boolean" && Array.isArray(value.deltas) && value.deltas.length <= 256, "candidate shape");
  assert(value.changed !== (value.deltas.length === 0), "candidate shape");
  const projected = value.deltas.map(deltaProjection);
  const moduleIds = projected.map((item) => item[1].moduleId);
  assert(JSON.stringify(moduleIds) === JSON.stringify([...new Set(moduleIds)].sort()), "delta order");
  const byModule = new Map(projected.map((item) => [item[1].moduleId, item[1]]));
  for (const [, item] of projected) {
    if (item.operation === "split") for (const related of item.related) assert(byModule.get(related)?.operation === "add", "split participant");
    if (item.operation === "merge") for (const related of item.related) assert(byModule.get(related)?.operation === "retire", "merge participant");
  }
  const computed = hptc("platform.types:runtime-topology-candidate-v1", 1, {
    baseline_generation: ["u64", baseline], candidate_generation: ["u64", generation],
    candidate_id: ["stable_id", candidateId], changed: ["bool", value.changed],
    deltas: ["array", projected.map((item) => ["digest", item[0]])],
    evaluation_digest: ["digest", evaluation], proposal_digest: ["digest", proposal],
    rollback_predecessor_digest: ["digest", rollback], selected_topology_digest: ["digest", selected],
  });
  assert(computed === stored, "candidate digest");
  return computed;
}
function rawProtocolDigest(raw, protocol) {
  const value = parseStrictJson(raw);
  if (protocol === "PromptDeliveryObservationV2") {
    assertUnsignedIntegerTokens(raw);
    return promptDigest(value);
  }
  if (protocol === "RuntimeTopologyCandidateV1") return topologyDigest(value);
  if (protocol === "parser") return value;
  throw new Error(`unknown raw protocol: ${protocol}`);
}
function verifyRawInvalid(vector) {
  try {
    rawProtocolDigest(vector.rawJson, vector.protocol);
  } catch (error) {
    assert(String(error.message).includes(vector.expectedError), `${vector.id}: wrong rejection ${error.message}`);
    return;
  }
  throw new Error(`${vector.id}: raw invalid vector accepted`);
}
function verifyStrictJsonBoundaries() {
  for (const raw of [
    '{"x":1,"\\u0078":2}',
    '{"outer":{"x":1,"x":2}}',
    '[{"x":1,"x":2}]',
  ]) {
    let rejected = false;
    try { parseStrictJson(raw); } catch (error) { rejected = error.message === "duplicate_key"; }
    assert(rejected, `decoded duplicate object key accepted: ${raw}`);
  }
  for (const raw of ['[{"x":1},{"x":2}]', '{"x":{"x":1}}', '{"x":"\\\"x\\\":1"}']) {
    parseStrictJson(raw);
  }
  parseStrictJson('[-0,1.0,1e0]');
  assertUnsignedIntegerTokens('["-0","1.0","1e0",0,1]');
  parseStrictJson("0" + " ".repeat(MAX_RAW_BYTES - 1));
  let rejected = false;
  try { parseStrictJson("0" + " ".repeat(MAX_RAW_BYTES)); } catch (error) { rejected = error.message === "size_exceeded"; }
  assert(rejected, "strict JSON admitted oversized raw input");
}
function verifyPromptCapacity() {
  for (const count of [1, 4095, 4096, 4097, 8192, 8193]) {
    const value = {
      kind: "prompt_delivery_observation_v2", compilation_id: "compilation-1",
      provider_request_digest: "11".repeat(32), delivered: true, rejected_reason: null,
      observed_token_positions: Array.from({length: count}, (_, index) => index),
      truncation_observed: false, legacy_v1_digest: null,
    };
    let result = null;
    try { result = promptDigest(value); } catch (error) {
      assert(count > 4096, `accepted boundary rejected: ${count}: ${error}`);
    }
    assert((result !== null) === (count <= 4096), `capacity mismatch: ${count}`);
    if (count === 4096) assert(result === "c499a4a2479291376878d2f3a506d342c7f96b3eaa0fea3d206aafcbaf5a4e36", "frozen capacity digest changed");
  }
  let rejected = false;
  try { encodeValue("array", Array.from({length: 4097}, () => ["u64", 0n])); } catch { rejected = true; }
  assert(rejected, "generic HPTC array bound bypassed");
}
for (const vector of VECTORS.validVectors) {
  const actual = vector.protocol === "PromptDeliveryObservationV2"
    ? promptDigest(vector.json)
    : topologyDigest(vector.json);
  assert(actual === vector.expectedHptcSha256, `${vector.id}: digest mismatch ${actual}`);
}
for (const vector of VECTORS.rawInvalidVectors) verifyRawInvalid(vector);
verifyStrictJsonBoundaries();
verifyPromptCapacity();
console.log(`platform.types prompt/topology JavaScript conformance: ok (${VECTORS.validVectors.length} valid, ${VECTORS.rawInvalidVectors.length} raw invalid, 6 capacity boundaries)`);
