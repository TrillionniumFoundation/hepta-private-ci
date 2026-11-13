// Run from any directory. --check verifies checked-in oracle output without writes.
import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { canonicalJson, parseCanonicalJson, digestCanonical } from "../../../src/canonical.js";
import { projectRuntime, digestRuntimeProjection, buildOperationIntent, digestOperationIntent } from "../../../src/control.js";
import { normalizeSession } from "../../../src/runtime-contract.js";
import { normalizeSnapshot, validateSnapshotTransition } from "../../../src/snapshot.js";
import { captureConfirmation, assertConfirmation } from "../../../src/confirmation.js";

const outcome = async callback => {
  try { return { ok: await callback() }; }
  catch (error) { return { error: error.code, retryable: error.retryable }; }
};
const cases = [
  ["null", "null"], ["boolean", "true"], ["positive safe bound", "9007199254740991"],
  ["negative safe bound", "-9007199254740991"], ["too positive", "9007199254740992"],
  ["too negative", "-9007199254740992"], ["negative zero", "-0"], ["float negative zero", "-0.0"],
  ["integral float", "12.0"], ["fraction", "0.5"],
  ["integer rounded at epsilon", "1.0000000000000001"], ["rounded safe ceiling", "9007199254740991.1"],
  ["halfway integral rounding", "9007199254740990.5"], ["underflow", "1e-324"], ["negative underflow", "-1e-4000"], ["numeric key order", '{"2":"two","10":"ten"}'],
  ["UTF-16 astral key order", '{"":1,"😀":2,"𐀀":3,"a":4}'],
  ["NFC", '"é"'], ["not NFC", '"e\\u0301"'], ["lone high surrogate", '"\\ud800"'],
  ["lone low surrogate", '"\\udc00"'], ["control", '"a\\n"'], ["C1 control", '"\\u0085"'],
  ["bidi", '"\\u202e"'], ["zero width", '"\\u200b"'], ["BOM", '"\\ufeff"'],
  ["allowed separator", '"a b c"'], ["empty key", '{"":1}'],
  ["prototype key", '{"__proto__":1}'], ["constructor key", '{"constructor":1}'],
  ["prototype field", '{"prototype":1}'], ["empty string", '""'],
  ["depth at zero", "[]", { maxDepth: 0 }], ["depth over zero", "[0]", { maxDepth: 0 }],
  ["entry bound", '{"a":[1]}', { maxEntries: 2 }], ["entry exceeded", '{"a":[1]}', { maxEntries: 1 }],
  ["array bound", "[1,2]", { maxArrayLength: 2 }], ["array exceeded", "[1,2]", { maxArrayLength: 1 }],
  ["UTF-8 bytes bound", '"é"', { maxStringBytes: 2 }], ["UTF-8 bytes exceeded", '"é"', { maxStringBytes: 1 }],
  ["encoded bound", "[0]", { maxEncodedBytes: 3 }], ["encoded exceeded", "[0]", { maxEncodedBytes: 2 }],
  ["invalid depth limit", "0", { maxDepth: 65 }],
  ["invalid entry limit", "0", { maxEntries: 1000001 }],
  ["invalid array limit", "0", { maxArrayLength: 100001 }],
  ["invalid string limit", "0", { maxStringBytes: 16777217 }],
  ["invalid encoded limit", "0", { maxEncodedBytes: 33554433 }],
  ["zero encoded limit", "0", { maxEncodedBytes: 0 }],
];
const canonical = await Promise.all(cases.map(async ([name, input, limits = {}]) => ({
  name, input, limits,
  result: await outcome(() => canonicalJson(JSON.parse(input), limits)),
  parse: await outcome(() => parseCanonicalJson(input, limits)),
})));
for (const input of ['{"a":1,"a":1}', '{"a":1,"a":2}', '{"a":{"x":1,"x":2}}', ' {"a":1}', '1e0', '"\\u0061"', '"\\/"', '[1,]']) {
  canonical.push({ name: `strict parse ${input}`, input, limits: {}, parse: await outcome(() => parseCanonicalJson(input)) });
}
const runtimeInput = {
  generation: 2, revision: 3, modules: [
    { id: "z.module", status: "ready", revision: 1, semanticDigest: "a".repeat(64) },
    { id: "a.module", status: "degraded", revision: 2, semanticDigest: "b".repeat(64) },
  ],
};
const operationInput = { action: "request_reconcile", targetId: "a.module", generation: 2, displayedRevision: 3, reason: "Recover the degraded worker." };
const sessionInput = { authenticated: true, protocolVersion: "hepta.ui-control.v1", sessionId: "session-1", identityId: "operator-1", connectionGeneration: 1, permissionRevision: 1, expiresAt: 2000000, revoked: false,
  permissions: ["hepta://ui.control/runtime.stop", "hepta://ui.control/runtime.read", "hepta://ui.control/runtime.request", "hepta://ui.control/runtime.start"] };
const session = normalizeSession(sessionInput, "hepta.ui-control.v1", 1000);
const snapshotInput = { sessionId: session.sessionId, connectionGeneration: 1, ...runtimeInput, observedAt: "2026-10-02T00:00:00.000Z" };
const snapshot = await normalizeSnapshot(snapshotInput, session);
const transitionChanges = [
  ["no prior", null], ["unchanged", {}], ["observation only", { observedAt: "later" }],
  ["session drift", { sessionId: "session-2" }], ["connection rollback", { connectionGeneration: 0 }],
  ["connection rollover", { connectionGeneration: 2, generation: 1, revision: 1 }],
  ["generation rollback", { generation: 1 }], ["generation rollover", { generation: 3, revision: 1 }],
  ["revision rollback", { revision: 2 }], ["revision advance", { revision: 4 }], ["content drift", { semanticDigest: "c".repeat(64) }],
];
const transitions = await Promise.all(transitionChanges.map(async ([name, change]) => ({
  name, change, result: await outcome(() => validateSnapshotTransition(change === null ? null : snapshot, { ...snapshot, ...change })),
})));
const view = { connected: true, authenticated: true, stale: false, ...session, snapshot };
const confirmationInput = { ...operationInput, operationId: "op-1" };
const confirmation = captureConfirmation(view, confirmationInput);
const confirmationChanges = [
  ["sessionId", "session-2"], ["identityId", "operator-2"], ["permissionRevision", 2], ["connectionGeneration", 2],
  ["snapshot.generation", 3], ["snapshot.revision", 4], ["snapshot.semanticDigest", "c".repeat(64)],
  ["snapshot.modules.0.revision", 3], ["snapshot.modules.0.semanticDigest", "d".repeat(64)],
  ["input.targetId", "z.module"], ["input.action", "request_stop"], ["input.reason", "Changed"], ["input.operationId", "op-2"],
  ["connected", false], ["authenticated", false], ["stale", true],
];
const confirmationDrift = await Promise.all(confirmationChanges.map(async ([path, value]) => {
  const changedView = structuredClone(view); const input = structuredClone(confirmationInput);
  const parts = path.split("."); let target = parts[0] === "input" ? input : changedView;
  if (parts[0] === "input") parts.shift();
  while (parts.length > 1) target = target[parts.shift()];
  target[parts[0]] = value;
  return { path, value, result: await outcome(() => { assertConfirmation(confirmation, changedView, input); return true; }) };
}));
const output = {
  source: "JavaScript ui.control reference modules; deterministic, no clock/random inputs",
  canonical,
  domains: await Promise.all(["hepta.ui-control.one.v1", "hepta.ui-control.two.v1"].map(async domain => ({ domain, value: { a: 1 }, digest: await digestCanonical(domain, { a: 1 }) }))),
  runtime: { input: runtimeInput, projection: projectRuntime(runtimeInput), digest: await digestRuntimeProjection(runtimeInput) },
  operation: { input: operationInput, intent: buildOperationIntent(operationInput), digest: await digestOperationIntent(operationInput) },
  session: { input: sessionInput, normalized: session },
  snapshot: { input: snapshotInput, normalized: snapshot },
  transitions, confirmation: { input: confirmationInput, captured: confirmation, drift: confirmationDrift },
};
const file = new URL("./fixtures/javascript-reference.json", import.meta.url);
const encoded = `${JSON.stringify(output, null, 2)}\n`;
if (process.argv.includes("--check")) assert.equal(await readFile(file, "utf8"), encoded);
else await writeFile(file, encoded);
console.log(`${canonical.length} canonical vectors and projection/session/snapshot/confirmation reference verified`);
