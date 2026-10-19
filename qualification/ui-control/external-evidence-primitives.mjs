import { createHash } from "node:crypto";

export const SHA1 = /^[0-9a-f]{40}$/u;
export const SHA256 = /^[0-9a-f]{64}$/u;
export const TERMINAL = new Set(["succeeded", "failed", "rejected", "cancelled"]);
export const CHAOS_CASES = new Map([
  ["crash-before-admission-commit", { records: 0, effects: 0, terminal: false, durableRecord: false }],
  ["crash-after-admission-before-dispatch", { records: 1, effects: 0, terminal: false, durableRecord: true }],
  ["crash-after-dispatch-before-terminal-observation", { records: 1, effects: [0, 1], terminal: false, durableRecord: true }],
  ["restart-reconciles-terminal-state", { records: 1, effects: [0, 1], terminal: true, durableRecord: true }],
]);
export const INDEPENDENT_SECURITY_CONTROLS = Object.freeze([
  "tls",
  "csp",
  "csrf",
  "cors",
  "cookie",
  "production-identity-provider",
  "session",
  "operation-ledger",
  "browser-token-non-persistence",
  "logging-redaction",
  "penetration-test",
]);

export function assertEvidence(condition, code, message) {
  if (condition) return;
  const error = new Error(message);
  error.code = code;
  throw error;
}

export function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

export function boundedText(value, label, maximum = 256) {
  assertEvidence(typeof value === "string", "UI_CONTROL_EVIDENCE_TYPE", `${label} must be a string`);
  const normalized = value.normalize("NFC").replace(/[\u0000-\u001f\u007f]/gu, " ").trim();
  assertEvidence(normalized.length > 0 && normalized.length <= maximum, "UI_CONTROL_EVIDENCE_TEXT", `${label} is empty or too long`);
  return normalized;
}

export function exactSha(value, label, pattern) {
  assertEvidence(typeof value === "string" && pattern.test(value), "UI_CONTROL_EVIDENCE_DIGEST", `${label} has an invalid digest`);
  return value;
}

export function parseTimestamp(value, label, now, maxAgeMs) {
  const timestamp = Date.parse(value);
  assertEvidence(Number.isFinite(timestamp), "UI_CONTROL_EVIDENCE_TIME", `${label} is not a valid timestamp`);
  assertEvidence(timestamp <= now + 5 * 60_000, "UI_CONTROL_EVIDENCE_FUTURE", `${label} is in the future`);
  if (maxAgeMs !== null) {
    assertEvidence(timestamp >= now - maxAgeMs, "UI_CONTROL_EVIDENCE_EXPIRED", `${label} is older than the accepted evidence window`);
  }
  return timestamp;
}

export function deploymentSubject(rawBaseUrl, deploymentId) {
  const base = new URL(rawBaseUrl);
  assertEvidence(base.protocol === "https:", "UI_CONTROL_DEPLOYMENT_HTTPS", "deployment qualification requires HTTPS");
  assertEvidence(!base.username && !base.password && !base.search && !base.hash, "UI_CONTROL_DEPLOYMENT_URL", "base URL contains forbidden components");
  const path = base.pathname.replace(/\/+$/u, "") || "/";
  const id = boundedText(deploymentId, "deploymentId", 192);
  const subject = Object.freeze({ origin: base.origin, basePath: path, deploymentId: id });
  const digest = sha256(JSON.stringify([subject.origin, subject.basePath, subject.deploymentId]));
  return Object.freeze({ base, subject, digest });
}

export function safeFailure(error, stage) {
  const rawCode = typeof error?.code === "string" ? error.code : "UI_CONTROL_EXTERNAL_QUALIFICATION_FAILED";
  const code = /^[A-Z0-9_]{3,96}$/u.test(rawCode) ? rawCode : "UI_CONTROL_EXTERNAL_QUALIFICATION_FAILED";
  const rawMessage = String(error?.message ?? error ?? "external qualification failed");
  const message = rawMessage.normalize("NFC").replace(/[\u0000-\u001f\u007f]/gu, " ").slice(0, 1024);
  return Object.freeze({ stage: boundedText(stage, "failure stage", 128), code, message });
}

export function validateCommonReceipt(receipt, schema, expected, now, maxAgeMs) {
  assertEvidence(receipt && typeof receipt === "object" && !Array.isArray(receipt), "UI_CONTROL_EXTERNAL_RECEIPT", "external receipt must be an object");
  assertEvidence(receipt.schema === schema, "UI_CONTROL_EXTERNAL_SCHEMA", `expected ${schema}`);
  const productionApproval =
    schema === "hepta.ui-control.production-approval-receipt.v1";
  const acceptedStatus = productionApproval ? "approved" : "passed";
  const timestampField = productionApproval ? "approvedAt" : "executedAt";
  const forbiddenTimestampField = productionApproval ? "executedAt" : "approvedAt";
  assertEvidence(
    receipt.status === acceptedStatus,
    "UI_CONTROL_EXTERNAL_STATUS",
    `${schema} must have status ${acceptedStatus}`,
  );
  assertEvidence(
    receipt[forbiddenTimestampField] === undefined,
    "UI_CONTROL_EXTERNAL_TIMESTAMP_FIELD",
    `${schema} must not carry ${forbiddenTimestampField}`,
  );
  exactSha(receipt.candidateCommit, "candidateCommit", SHA1);
  exactSha(receipt.candidateTree, "candidateTree", SHA1);
  exactSha(receipt.backendDeploymentDigest, "backendDeploymentDigest", SHA256);
  assertEvidence(receipt.candidateCommit === expected.candidateCommit, "UI_CONTROL_EXTERNAL_COMMIT", `${schema} is bound to another candidate commit`);
  assertEvidence(receipt.candidateTree === expected.candidateTree, "UI_CONTROL_EXTERNAL_TREE", `${schema} is bound to another candidate tree`);
  assertEvidence(receipt.backendDeploymentDigest === expected.backendDeploymentDigest, "UI_CONTROL_EXTERNAL_DEPLOYMENT", `${schema} is bound to another deployment`);
  parseTimestamp(
    receipt[timestampField],
    `receipt.${timestampField}`,
    now,
    maxAgeMs,
  );
  exactSha(receipt.rawEvidenceDigest, "rawEvidenceDigest", SHA256);
}
