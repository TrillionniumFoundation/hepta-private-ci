#!/usr/bin/env node
// Independent strict-JSON -> HPTC oracle for platform.types manifests.

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const VECTOR_PATH = path.join(ROOT, "codex-rs/hepta-types/MANIFEST_V1_CONFORMANCE.json");
const SCHEMA_ROOT = path.join(ROOT, "codex-rs/hepta-types");
const DOMAIN = Buffer.from("hepta.platform.types.canonical-digest.v1");
const U64_MAX = (1n << 64n) - 1n;
const I64_MIN = -(1n << 63n);
const I64_MAX = (1n << 63n) - 1n;
const STABLE_ID = /^[A-Za-z0-9._:-]+$/;
const ENUM_TOKEN = /^(?:[a-z][a-z0-9._:-]*[a-z0-9]|[a-z0-9])$/;
const DIGEST = /^[0-9a-f]{64}$/;
const U64_TEXT = /^(?:0|[1-9][0-9]*)$/;
const I64_TEXT = /^(?:0|-?[1-9][0-9]*)$/;
const UTC = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z$/;

const RANDOM_KEYS = new Set([
  "kind", "manifest_id", "root_seed_digest", "algorithm_namespace", "episode_id",
  "decision_id", "stream_id", "counter_start", "counter_end_exclusive",
  "generator_id", "generator_version",
]);
const EXTERNAL_KEYS = new Set([
  "kind", "system_id", "system_class", "host_identity_digest", "os_release_digest",
  "package_inventory_digest", "service_graph_digest", "filesystem_scope_digest",
  "identity_map_digest", "network_surface_digest", "secret_reference_digest",
  "observed_at", "authorization_witness",
]);
const SENSOR_KEYS = new Set([
  "kind", "sensor_id", "sensor_class", "hardware_or_adapter_digest",
  "calibration_generation", "clock_domain", "valid_from", "valid_until",
  "uncertainty_profile", "operating_range", "failure_policy",
]);
const UNCERTAINTY_KEYS = new Set([
  "distribution_class", "lower_q32", "upper_q32", "confidence_ppm",
]);
const OPERATING_KEYS = new Set(["unit", "minimum_q32", "maximum_q32"]);

function fail(message) {
  throw new Error(message);
}

function strictKeys(value, expected, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail(`${name}: object required`);
  }
  const actual = Object.keys(value);
  const extra = actual.filter((key) => !expected.has(key)).sort();
  const missing = [...expected].filter((key) => !Object.hasOwn(value, key)).sort();
  if (extra.length > 0) fail(`unknown field in ${name}: ${extra[0]}`);
  if (missing.length > 0) fail(`missing field in ${name}: ${missing[0]}`);
  return value;
}

function utf8Length(value) {
  return Buffer.byteLength(value, "utf8");
}

function stableId(value, name) {
  if (typeof value !== "string" || utf8Length(value) < 1 || utf8Length(value) > 128) {
    fail(`${name}: stable id bound`);
  }
  if (!STABLE_ID.test(value)) fail(`${name}: stable id syntax`);
  return value;
}

function boundedText(value, name, maximum) {
  if (typeof value !== "string" || value.length === 0 || value.includes("\0")) {
    fail(`${name}: text`);
  }
  if (utf8Length(value) > maximum) fail(`${name}: text bound`);
  return value;
}

function enumToken(value, name, maximum = 64) {
  const checked = boundedText(value, name, maximum);
  if (!ENUM_TOKEN.test(checked)) fail(`${name}: enum token`);
  return checked;
}

function digest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value)) fail(`${name}: digest`);
  if (value === "0".repeat(64)) fail(`${name}: zero digest`);
  return value;
}

function u64Text(value, name, positive = false) {
  if (typeof value !== "string" || !U64_TEXT.test(value)) fail(`${name}: u64`);
  const parsed = BigInt(value);
  if (parsed > U64_MAX || (positive && parsed === 0n)) fail(`${name}: u64`);
  return parsed;
}

function i64Text(value, name) {
  if (typeof value !== "string" || !I64_TEXT.test(value)) fail(`${name}: i64`);
  const parsed = BigInt(value);
  if (parsed < I64_MIN || parsed > I64_MAX) fail(`${name}: i64`);
  return parsed;
}

function leapYear(year) {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function daysInMonth(year, month) {
  if ([1, 3, 5, 7, 8, 10, 12].includes(month)) return 31;
  if ([4, 6, 9, 11].includes(month)) return 30;
  if (month === 2) return leapYear(year) ? 29 : 28;
  return 0;
}

function timestamp(value, name) {
  if (typeof value !== "string") fail(`${name}: timestamp`);
  const match = UTC.exec(value);
  if (match === null) fail(`${name}: timestamp`);
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number);
  if (
    year === 0 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)
    || hour > 23 || minute > 59 || second > 59
  ) {
    fail(`${name}: timestamp`);
  }
  const fraction = (match[7] ?? "").padEnd(6, "0");
  return [year, month, day, hour, minute, second, Number(fraction || "0")];
}

function compareTimestamp(left, right) {
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] < right[index]) return -1;
    if (left[index] > right[index]) return 1;
  }
  return 0;
}

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

function u64(value) {
  const output = Buffer.alloc(8);
  output.writeBigUInt64BE(BigInt(value));
  return output;
}

function i64(value) {
  const output = Buffer.alloc(8);
  const parsed = BigInt(value);
  output.writeBigUInt64BE(parsed < 0n ? (1n << 64n) + parsed : parsed);
  return output;
}

function label(value) {
  const encoded = Buffer.from(value);
  return Buffer.concat([u16(encoded.length), encoded]);
}

function encodeValue(kind, value) {
  if (kind === "bool") return Buffer.from([0x01, value ? 1 : 0]);
  if (kind === "u64") return Buffer.concat([Buffer.from([0x02]), u64(value)]);
  if (kind === "i64") return Buffer.concat([Buffer.from([0x04]), i64(value)]);
  if (kind === "text") {
    const payload = Buffer.from(value);
    return Buffer.concat([Buffer.from([0x06]), u32(payload.length), payload]);
  }
  if (kind === "digest") return Buffer.concat([Buffer.from([0x07]), Buffer.from(value, "hex")]);
  if (kind === "stable_id") {
    const payload = Buffer.from(value);
    return Buffer.concat([Buffer.from([0x08]), u16(payload.length), payload]);
  }
  if (kind === "map") {
    const entries = Object.entries(value).sort(([left], [right]) => Buffer.from(left).compare(Buffer.from(right)));
    return Buffer.concat([
      Buffer.from([0x0a]),
      u32(entries.length),
      ...entries.flatMap(([key, item]) => [label(key), encodeValue(item[0], item[1])]),
    ]);
  }
  fail(`unknown canonical kind: ${kind}`);
}

function hptc(typeId, fields) {
  const typeBytes = Buffer.from(typeId);
  const entries = Object.entries(fields).sort(([left], [right]) => Buffer.from(left).compare(Buffer.from(right)));
  const encoded = Buffer.concat([
    Buffer.from("HPTC"),
    u16(1),
    u16(DOMAIN.length),
    DOMAIN,
    u16(typeBytes.length),
    typeBytes,
    u32(1),
    u32(entries.length),
    ...entries.flatMap(([name, item]) => [label(name), encodeValue(item[0], item[1])]),
  ]);
  return crypto.createHash("sha256").update(encoded).digest("hex");
}

function randomProjection(value) {
  strictKeys(value, RANDOM_KEYS, "random manifest");
  if (value.kind !== "random_stream_manifest_v1") fail("kind");
  const start = u64Text(value.counter_start, "counter_start");
  const end = u64Text(value.counter_end_exclusive, "counter_end_exclusive");
  if (end <= start) fail("counter range");
  return ["platform.types:random-stream-manifest-v1", {
    algorithm_namespace: ["text", enumToken(value.algorithm_namespace, "algorithm_namespace")],
    counter_end_exclusive: ["u64", end],
    counter_start: ["u64", start],
    decision_id: ["stable_id", stableId(value.decision_id, "decision_id")],
    episode_id: ["stable_id", stableId(value.episode_id, "episode_id")],
    generator_id: ["text", enumToken(value.generator_id, "generator_id")],
    generator_version: ["text", boundedText(value.generator_version, "generator_version", 64)],
    manifest_id: ["stable_id", stableId(value.manifest_id, "manifest_id")],
    root_seed_digest: ["digest", digest(value.root_seed_digest, "root_seed_digest")],
    stream_id: ["stable_id", stableId(value.stream_id, "stream_id")],
  }];
}

function externalProjection(value) {
  strictKeys(value, EXTERNAL_KEYS, "external manifest");
  if (value.kind !== "external_system_manifest_v1") fail("kind");
  const classes = new Set(["debian_host", "debian_service", "posix_host", "posix_service", "digital_adapter"]);
  if (!classes.has(value.system_class)) fail("system_class");
  timestamp(value.observed_at, "observed_at");
  return ["platform.types:external-system-manifest-v1", {
    authorization_witness: ["digest", digest(value.authorization_witness, "authorization_witness")],
    filesystem_scope_digest: ["digest", digest(value.filesystem_scope_digest, "filesystem_scope_digest")],
    host_identity_digest: ["digest", digest(value.host_identity_digest, "host_identity_digest")],
    identity_map_digest: ["digest", digest(value.identity_map_digest, "identity_map_digest")],
    network_surface_digest: ["digest", digest(value.network_surface_digest, "network_surface_digest")],
    observed_at: ["text", value.observed_at],
    os_release_digest: ["digest", digest(value.os_release_digest, "os_release_digest")],
    package_inventory_digest: ["digest", digest(value.package_inventory_digest, "package_inventory_digest")],
    secret_reference_digest: ["digest", digest(value.secret_reference_digest, "secret_reference_digest")],
    service_graph_digest: ["digest", digest(value.service_graph_digest, "service_graph_digest")],
    system_class: ["text", value.system_class],
    system_id: ["stable_id", stableId(value.system_id, "system_id")],
  }];
}

function sensorProjection(value) {
  strictKeys(value, SENSOR_KEYS, "sensor manifest");
  strictKeys(value.uncertainty_profile, UNCERTAINTY_KEYS, "uncertainty_profile");
  strictKeys(value.operating_range, OPERATING_KEYS, "operating_range");
  if (value.kind !== "sensor_calibration_manifest_v1") fail("kind");
  const classes = new Set([
    "physical_sensor", "browser_session", "matrix_session", "provider_runtime",
    "filesystem_mount", "service_adapter", "simulator",
  ]);
  const distributions = new Set(["bounded_interval", "normal_approximation", "empirical_quantiles"]);
  const policies = new Set(["reject", "degrade", "abstain", "reflex_stop"]);
  if (!classes.has(value.sensor_class)) fail("sensor_class");
  if (!distributions.has(value.uncertainty_profile.distribution_class)) fail("distribution_class");
  if (!policies.has(value.failure_policy)) fail("failure_policy");
  const validFrom = timestamp(value.valid_from, "valid_from");
  const validUntil = timestamp(value.valid_until, "valid_until");
  if (compareTimestamp(validUntil, validFrom) <= 0) fail("validity window");
  const lower = i64Text(value.uncertainty_profile.lower_q32, "lower_q32");
  const upper = i64Text(value.uncertainty_profile.upper_q32, "upper_q32");
  const confidence = value.uncertainty_profile.confidence_ppm;
  if (!Number.isInteger(confidence) || confidence < 1 || confidence > 1_000_000) fail("confidence");
  if (lower > upper) fail("uncertainty range");
  const minimum = i64Text(value.operating_range.minimum_q32, "minimum_q32");
  const maximum = i64Text(value.operating_range.maximum_q32, "maximum_q32");
  if (minimum > maximum) fail("operating range");
  return ["platform.types:sensor-calibration-manifest-v1", {
    calibration_generation: ["u64", u64Text(value.calibration_generation, "calibration_generation", true)],
    clock_domain: ["text", boundedText(value.clock_domain, "clock_domain", 128)],
    failure_policy: ["text", value.failure_policy],
    hardware_or_adapter_digest: ["digest", digest(value.hardware_or_adapter_digest, "hardware_or_adapter_digest")],
    operating_range: ["map", {
      maximum_q32: ["i64", maximum],
      minimum_q32: ["i64", minimum],
      unit: ["text", boundedText(value.operating_range.unit, "unit", 64)],
    }],
    sensor_class: ["text", value.sensor_class],
    sensor_id: ["stable_id", stableId(value.sensor_id, "sensor_id")],
    uncertainty_profile: ["map", {
      confidence_ppm: ["u64", BigInt(confidence)],
      distribution_class: ["text", value.uncertainty_profile.distribution_class],
      lower_q32: ["i64", lower],
      upper_q32: ["i64", upper],
    }],
    valid_from: ["text", value.valid_from],
    valid_until: ["text", value.valid_until],
  }];
}

function semanticDigest(value) {
  let projection;
  if (value?.kind === "random_stream_manifest_v1") projection = randomProjection(value);
  else if (value?.kind === "external_system_manifest_v1") projection = externalProjection(value);
  else if (value?.kind === "sensor_calibration_manifest_v1") projection = sensorProjection(value);
  else fail("kind");
  return hptc(projection[0], projection[1]);
}

function verifySchemaAnchors(document) {
  const expected = new Map([
    ["random-stream-manifest-v1.schema.json", RANDOM_KEYS],
    ["external-system-manifest-v1.schema.json", EXTERNAL_KEYS],
    ["sensor-calibration-manifest-v1.schema.json", SENSOR_KEYS],
  ]);
  for (const relative of document.transport.schemas) {
    const schemaPath = path.join(SCHEMA_ROOT, relative);
    const schema = JSON.parse(fs.readFileSync(schemaPath, "utf8"));
    if (schema.additionalProperties !== false) fail(`${relative}: schema must reject unknown fields`);
    const actual = new Set(schema.required ?? []);
    const wanted = expected.get(path.basename(schemaPath));
    if (wanted === undefined || actual.size !== wanted.size || [...wanted].some((key) => !actual.has(key))) {
      fail(`${relative}: required field drift`);
    }
  }
}

const document = JSON.parse(fs.readFileSync(VECTOR_PATH, "utf8"));
if (
  document.schema !== "hepta.platform-types.manifest-conformance.v1"
  || document.schemaVersion !== 1
  || document.semanticCommitment?.format !== "HPTC"
  || document.semanticCommitment?.domain !== DOMAIN.toString()
) {
  fail("manifest conformance header mismatch");
}
verifySchemaAnchors(document);
for (const vector of document.validVectors) {
  if (vector.kind !== vector.json?.kind) fail(`${vector.id}: kind mismatch`);
  const actual = semanticDigest(vector.json);
  if (actual !== vector.expectedHptcSha256) fail(`${vector.id}: semantic digest mismatch: ${actual}`);
}
for (const vector of document.invalidVectors) {
  try {
    semanticDigest(vector.json);
  } catch (error) {
    if (!String(error.message).includes(vector.expectedError)) {
      fail(`${vector.id}: wrong rejection ${error.message}; expected ${vector.expectedError}`);
    }
    continue;
  }
  fail(`${vector.id}: invalid manifest accepted`);
}
console.log(
  `platform.types Node manifest codec: ${document.validVectors.length} accepted, `
  + `${document.invalidVectors.length} rejected`,
);
