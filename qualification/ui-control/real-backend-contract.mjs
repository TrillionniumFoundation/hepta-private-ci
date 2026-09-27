#!/usr/bin/env node
import { createHash, randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { request as httpsRequest } from "node:https";
import { resolve } from "node:path";
import {
  UI_CONTROL_PROTOCOL_VERSION,
  buildOperationIntent,
  digestOperationIntent,
  normalizeSnapshot,
} from "../../apps/hepta-control-ui/src/index.js";

const required = name => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
};
const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};
const sha256 = value => createHash("sha256").update(value).digest("hex");
const command = (...args) => execFileSync(args[0], args.slice(1), { encoding: "utf8" }).trim();
const sleep = milliseconds => new Promise(resolveSleep => setTimeout(resolveSleep, milliseconds));

assert(
  process.env.HEPTA_UI_CONTROL_ALLOW_MUTATION === "I_UNDERSTAND_THIS_USES_A_DISPOSABLE_QUALIFICATION_TARGET",
  "HEPTA_UI_CONTROL_ALLOW_MUTATION must explicitly admit a disposable qualification target",
);
const base = new URL(required("HEPTA_UI_CONTROL_BASE_URL"));
assert(base.protocol === "https:", "real-backend qualification requires HTTPS");
assert(!base.username && !base.password && !base.search && !base.hash, "base URL contains forbidden components");
base.pathname = base.pathname.replace(/\/+$/, "");
const origin = base.origin;
const apiBase = new URL(`${base.pathname || ""}/api/ui-control/v1/`, origin);
const primaryCookie = required("HEPTA_UI_CONTROL_COOKIE");
const primaryCsrf = required("HEPTA_UI_CONTROL_CSRF_TOKEN");
const secondaryCookie = required("HEPTA_UI_CONTROL_SECONDARY_COOKIE");
const secondaryCsrf = required("HEPTA_UI_CONTROL_SECONDARY_CSRF_TOKEN");
const targetId = required("HEPTA_UI_CONTROL_TARGET_ID");
const action = process.env.HEPTA_UI_CONTROL_ACTION || "request_reconcile";
assert(["request_reconcile", "request_start", "request_stop"].includes(action), "unsupported qualification action");
const method = action === "request_start"
  ? "runtime/start"
  : action === "request_stop"
    ? "runtime/stop"
    : "runtime/request";
const timeoutMs = Number(process.env.HEPTA_UI_CONTROL_TERMINAL_TIMEOUT_MS || 120000);
assert(Number.isSafeInteger(timeoutMs) && timeoutMs >= 1000 && timeoutMs <= 900000, "invalid terminal timeout");
const output = process.argv[2] ? resolve(process.argv[2]) : null;

const chaosEvidenceText = await readFile(resolve(required("HEPTA_UI_CONTROL_CHAOS_EVIDENCE")), "utf8");
const chaosEvidence = JSON.parse(chaosEvidenceText);
assert(chaosEvidence.schema === "hepta.ui-control.agentd-chaos-evidence.v1", "unsupported chaos evidence schema");
const requiredChaosCases = new Set([
  "crash-before-admission-commit",
  "crash-after-admission-before-dispatch",
  "crash-after-dispatch-before-terminal-observation",
  "restart-reconciles-terminal-state",
]);
for (const item of chaosEvidence.cases || []) {
  if (item?.status === "passed") requiredChaosCases.delete(item.id);
}
assert(requiredChaosCases.size === 0, `chaos evidence is missing passed cases: ${[...requiredChaosCases].join(", ")}`);

async function requestJson(url, { cookie, csrf, method: httpMethod = "GET", body, originHeader = origin } = {}) {
  const response = await fetch(url, {
    method: httpMethod,
    redirect: "manual",
    cache: "no-store",
    headers: {
      accept: "application/json",
      ...(cookie ? { cookie } : {}),
      ...(originHeader ? { origin: originHeader } : {}),
      ...(body === undefined ? {} : { "content-type": "application/json" }),
      ...(csrf ? { "x-hepta-csrf-token": csrf } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  assert(!(response.status >= 300 && response.status < 400), `${url}: redirect is forbidden`);
  let payload = null;
  const text = await response.text();
  if (text) {
    try { payload = JSON.parse(text); } catch { throw new Error(`${url}: malformed JSON response`); }
  }
  return { response, payload };
}

async function connect(cookie, csrf) {
  const { response, payload } = await requestJson(new URL("session/connect", apiBase), {
    cookie,
    csrf,
    method: "POST",
    body: {
      protocolVersion: UI_CONTROL_PROTOCOL_VERSION,
      client: "hepta-control-ui-real-backend-qualification",
      requestedCapabilities: ["runtime.read", "runtime.request", "runtime.start", "runtime.stop"],
    },
  });
  assert(response.ok, `connect failed with ${response.status}`);
  assert(payload?.authenticated === true, "connect did not establish an authenticated session");
  return payload;
}

async function readSnapshot(session, cookie) {
  const { response, payload } = await requestJson(new URL("view", apiBase), {
    cookie,
    method: "POST",
    body: {
      sessionId: session.sessionId,
      connectionGeneration: session.connectionGeneration,
    },
  });
  assert(response.ok, `view failed with ${response.status}`);
  return normalizeSnapshot(payload, session);
}

async function operationBody(session, snapshot, operationId, reason) {
  const intent = buildOperationIntent({
    action,
    targetId,
    generation: snapshot.generation,
    displayedRevision: snapshot.revision,
    reason,
  });
  const semanticDigest = await digestOperationIntent(intent);
  return {
    method,
    protocolVersion: UI_CONTROL_PROTOCOL_VERSION,
    operationId,
    semanticDigest,
    action,
    targetId,
    reason,
    sessionId: session.sessionId,
    connectionGeneration: session.connectionGeneration,
    generation: snapshot.generation,
    displayedRevision: snapshot.revision,
    snapshotDigest: snapshot.semanticDigest,
  };
}

async function submit(body, cookie = primaryCookie, csrf = primaryCsrf) {
  return requestJson(new URL("operations", apiBase), {
    cookie,
    csrf,
    method: "POST",
    body,
  });
}

async function lookup(session, body, cookie) {
  const query = new URLSearchParams({
    sessionId: session.sessionId,
    connectionGeneration: String(session.connectionGeneration),
    semanticDigest: body.semanticDigest,
  });
  return requestJson(new URL(`operations/${encodeURIComponent(body.operationId)}?${query}`, apiBase), { cookie });
}

async function discardAcknowledgement(body) {
  const url = new URL("operations", apiBase);
  const serialized = JSON.stringify(body);
  await new Promise((resolveDiscard, reject) => {
    let settled = false;
    const settle = error => {
      if (settled) return;
      settled = true;
      if (error) reject(error); else resolveDiscard();
    };
    const request = httpsRequest(url, {
      method: "POST",
      headers: {
        accept: "application/json",
        cookie: primaryCookie,
        origin,
        "content-type": "application/json",
        "content-length": Buffer.byteLength(serialized),
        "x-hepta-csrf-token": primaryCsrf,
      },
    }, response => {
      const accepted = response.statusCode >= 200 && response.statusCode < 300;
      response.destroy();
      settle(accepted ? null : new Error(`response-loss operation was not accepted: ${response.statusCode}`));
    });
    request.on("error", error => {
      if (["ECONNRESET", "EPIPE", "ERR_STREAM_PREMATURE_CLOSE"].includes(error.code)) settle();
      else settle(error);
    });
    request.end(serialized);
  });
}

const terminal = new Set(["succeeded", "failed", "rejected", "cancelled"]);
async function waitForTerminal(session, body, cookie) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const { response, payload } = await lookup(session, body, cookie);
    assert(response.ok, `lookup failed with ${response.status}`);
    if (payload?.found === true && terminal.has(payload.status)) return payload;
    await sleep(500);
  }
  throw new Error(`operation ${body.operationId} did not reach a terminal observation within ${timeoutMs}ms`);
}

const primary = await connect(primaryCookie, primaryCsrf);
const secondary = await connect(secondaryCookie, secondaryCsrf);
assert(primary.identityId !== secondary.identityId, "secondary qualification session must use a different identity");
const snapshot = await readSnapshot(primary, primaryCookie);

const duplicateId = `uiq:${randomUUID()}`;
const duplicateBody = await operationBody(primary, snapshot, duplicateId, "Qualification: concurrent identical operation identity.");
const [first, second] = await Promise.all([submit(duplicateBody), submit(duplicateBody)]);
for (const result of [first, second]) {
  assert(result.response.ok, `identical submission failed with ${result.response.status}`);
  assert(result.payload?.operationId === duplicateId, "identical submission returned a different operation ID");
  assert(result.payload?.semanticDigest === duplicateBody.semanticDigest, "identical submission returned a different semantic digest");
}
assert(first.payload.auditTraceId === second.payload.auditTraceId, "identical submissions did not resolve to one durable record");

const conflictBody = await operationBody(primary, snapshot, duplicateId, "Qualification: changed payload under the same operation identity.");
const conflict = await submit(conflictBody);
assert(conflict.response.status === 409, `semantic reuse must return 409, got ${conflict.response.status}`);

const rejectedId = `uiq:${randomUUID()}`;
const rejectedBody = await operationBody(primary, snapshot, rejectedId, "Qualification: reject before admission without CSRF.");
const rejected = await submit(rejectedBody, primaryCookie, null);
assert([401, 403].includes(rejected.response.status), `missing CSRF must fail before admission, got ${rejected.response.status}`);
const rejectedLookup = await lookup(primary, rejectedBody, primaryCookie);
assert(rejectedLookup.response.ok && rejectedLookup.payload?.found === false, "pre-admission rejection created a durable operation");

const lossId = `uiq:${randomUUID()}`;
const lossBody = await operationBody(primary, snapshot, lossId, "Qualification: discard accepted acknowledgement and recover by operation ID.");
await discardAcknowledgement(lossBody);
const lossLookup = await lookup(primary, lossBody, primaryCookie);
assert(lossLookup.response.ok && lossLookup.payload?.found === true, "accepted response loss was not recoverable by operation ID");

const crossIdentity = await lookup(secondary, duplicateBody, secondaryCookie);
assert(
  [401, 403, 404].includes(crossIdentity.response.status) ||
    (crossIdentity.response.ok && crossIdentity.payload?.found === false),
  "a different authenticated identity could observe the primary operation",
);

const duplicateTerminal = await waitForTerminal(primary, duplicateBody, primaryCookie);
const lossTerminal = await waitForTerminal(primary, lossBody, primaryCookie);

const revoke = await requestJson(new URL("session/revoke", apiBase), {
  cookie: primaryCookie,
  csrf: primaryCsrf,
  method: "POST",
  body: {
    sessionId: primary.sessionId,
    connectionGeneration: primary.connectionGeneration,
  },
});
assert(revoke.response.ok, `session revoke failed with ${revoke.response.status}`);
const postRevoke = await requestJson(new URL("view", apiBase), {
  cookie: primaryCookie,
  method: "POST",
  body: {
    sessionId: primary.sessionId,
    connectionGeneration: primary.connectionGeneration,
  },
});
assert([401, 403].includes(postRevoke.response.status), `revoked session remained usable: ${postRevoke.response.status}`);

const closeSecondary = await requestJson(new URL("session/close", apiBase), {
  cookie: secondaryCookie,
  csrf: secondaryCsrf,
  method: "POST",
  body: {
    sessionId: secondary.sessionId,
    connectionGeneration: secondary.connectionGeneration,
  },
});
assert(closeSecondary.response.ok, `secondary close failed with ${closeSecondary.response.status}`);

const receipt = {
  schema: "hepta.ui-control.real-backend-receipt.v1",
  status: "passed",
  source: {
    sha: command("git", "rev-parse", "HEAD"),
    tree: command("git", "rev-parse", "HEAD^{tree}"),
  },
  backend: {
    origin,
    observedAt: new Date().toISOString(),
    primaryIdentity: primary.identityId,
    secondaryIdentity: secondary.identityId,
    runtimeGeneration: snapshot.generation,
    runtimeRevision: snapshot.revision,
  },
  cases: {
    concurrentIdenticalIdentity: "passed",
    changedPayloadConflict: "passed",
    rejectedBeforeAdmissionLeavesNoRecord: "passed",
    acceptedResponseLossLookup: "passed",
    crossIdentityLookupDenied: "passed",
    terminalLookup: "passed",
    sessionRevocation: "passed",
    crashRecoveryEvidence: "passed",
  },
  terminalObservations: {
    duplicateOperation: duplicateTerminal.status,
    responseLossOperation: lossTerminal.status,
  },
  evidence: {
    chaosEvidenceSha256: sha256(chaosEvidenceText),
  },
  claims: {
    realBackendSemanticsQualified: true,
    deployedSecurityObserved: false,
    independentAcceptanceSigned: false,
    productionDeploymentApproved: false,
  },
};
const serialized = `${JSON.stringify(receipt, null, 2)}\n`;
if (output) await writeFile(output, serialized);
process.stdout.write(serialized);