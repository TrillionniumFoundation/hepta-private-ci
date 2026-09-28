#!/usr/bin/env node
import { randomUUID } from "node:crypto";
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
import {
  assertEvidence,
  deploymentSubject,
  safeFailure,
  sha256,
  validateAuthorityEvidence,
  validateChaosEvidence,
} from "./external-evidence-lib.mjs";
import {
  assertOperationObservation,
  assertSessionReconnection,
  assertSnapshotNotRegressed,
} from "./real-backend-invariants.mjs";

const required = name => {
  const value = process.env[name];
  if (!value) {
    const error = new Error(`${name} is required`);
    error.code = "UI_CONTROL_EXTERNAL_INPUT_MISSING";
    throw error;
  }
  return value;
};
const command = (...args) => execFileSync(args[0], args.slice(1), { encoding: "utf8" }).trim();
const sleep = milliseconds => new Promise(resolveSleep => setTimeout(resolveSleep, milliseconds));
const output = process.argv[2] ? resolve(process.argv[2]) : null;
const source = {
  sha: command("git", "rev-parse", "HEAD"),
  tree: command("git", "rev-parse", "HEAD^{tree}"),
};
let stage = "initialization";
let deployment = null;
const completedCases = [];

async function emit(receipt) {
  const serialized = `${JSON.stringify(receipt, null, 2)}\n`;
  if (output) await writeFile(output, serialized);
  process.stdout.write(serialized);
}

try {
  assertEvidence(
    process.env.HEPTA_UI_CONTROL_ALLOW_MUTATION === "I_UNDERSTAND_THIS_USES_A_DISPOSABLE_QUALIFICATION_TARGET",
    "UI_CONTROL_MUTATION_ACKNOWLEDGEMENT",
    "HEPTA_UI_CONTROL_ALLOW_MUTATION must explicitly admit a disposable qualification target",
  );
  deployment = deploymentSubject(
    required("HEPTA_UI_CONTROL_BASE_URL"),
    required("HEPTA_UI_CONTROL_DEPLOYMENT_ID"),
  );
  const { base, subject, digest: backendDeploymentDigest } = deployment;
  const origin = subject.origin;
  const prefix = subject.basePath === "/" ? "" : subject.basePath;
  const apiBase = new URL(`${prefix}/api/ui-control/v1/`, origin);
  const primaryCookie = required("HEPTA_UI_CONTROL_COOKIE");
  const primaryCsrf = required("HEPTA_UI_CONTROL_CSRF_TOKEN");
  const secondaryCookie = required("HEPTA_UI_CONTROL_SECONDARY_COOKIE");
  const secondaryCsrf = required("HEPTA_UI_CONTROL_SECONDARY_CSRF_TOKEN");
  const targetId = required("HEPTA_UI_CONTROL_TARGET_ID");
  const action = process.env.HEPTA_UI_CONTROL_ACTION || "request_reconcile";
  assertEvidence(["request_reconcile", "request_start", "request_stop"].includes(action), "UI_CONTROL_ACTION", "unsupported qualification action");
  const method = action === "request_start"
    ? "runtime/start"
    : action === "request_stop"
      ? "runtime/stop"
      : "runtime/request";
  const timeoutMs = Number(process.env.HEPTA_UI_CONTROL_TERMINAL_TIMEOUT_MS || 120000);
  assertEvidence(Number.isSafeInteger(timeoutMs) && timeoutMs >= 1000 && timeoutMs <= 900000, "UI_CONTROL_TERMINAL_TIMEOUT", "invalid terminal timeout");

  stage = "external-chaos-and-authority-evidence";
  const chaosEvidenceText = await readFile(resolve(required("HEPTA_UI_CONTROL_CHAOS_EVIDENCE")), "utf8");
  const chaosEvidence = JSON.parse(chaosEvidenceText);
  const authorityEvidenceText = await readFile(resolve(required("HEPTA_UI_CONTROL_AUTHORITY_EVIDENCE")), "utf8");
  const authorityEvidence = JSON.parse(authorityEvidenceText);
  const expectedEvidence = {
    candidateCommit: source.sha,
    candidateTree: source.tree,
    backendDeploymentDigest,
  };
  const chaosSummary = validateChaosEvidence(chaosEvidence, expectedEvidence);
  validateAuthorityEvidence(authorityEvidence, expectedEvidence);
  completedCases.push("crash-restart-evidence", "permission-revision-and-revocation-evidence");

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
    assertEvidence(!(response.status >= 300 && response.status < 400), "UI_CONTROL_BACKEND_REDIRECT", `${url}: redirect is forbidden`);
    let payload = null;
    const text = await response.text();
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        const error = new Error(`${url}: malformed JSON response`);
        error.code = "UI_CONTROL_BACKEND_JSON";
        throw error;
      }
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
    assertEvidence(response.ok, "UI_CONTROL_BACKEND_CONNECT", `connect failed with ${response.status}`);
    assertEvidence(payload?.authenticated === true, "UI_CONTROL_BACKEND_AUTH", "connect did not establish an authenticated session");
    return payload;
  }

  async function readSnapshot(session, cookie) {
    const { response, payload } = await requestJson(new URL("view", apiBase), {
      cookie,
      method: "POST",
      body: { sessionId: session.sessionId, connectionGeneration: session.connectionGeneration },
    });
    assertEvidence(response.ok, "UI_CONTROL_BACKEND_VIEW", `view failed with ${response.status}`);
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
        settle(accepted ? null : Object.assign(new Error(`response-loss operation was not accepted: ${response.statusCode}`), { code: "UI_CONTROL_RESPONSE_LOSS_NOT_ACCEPTED" }));
      });
      request.on("error", error => {
        if (["ECONNRESET", "EPIPE", "ERR_STREAM_PREMATURE_CLOSE"].includes(error.code)) settle();
        else settle(error);
      });
      request.end(serialized);
    });
  }

  async function waitForTerminal(session, body, cookie, expectedAuditTraceId) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const { response, payload } = await lookup(session, body, cookie);
      assertEvidence(response.ok, "UI_CONTROL_BACKEND_LOOKUP", `lookup failed with ${response.status}`);
      if (payload?.found === true) {
        assertOperationObservation(payload, body, { expectedAuditTraceId });
        if (["succeeded", "failed", "rejected", "cancelled"].includes(payload.status)) {
          return assertOperationObservation(payload, body, {
            requireTerminal: true,
            expectedAuditTraceId,
          });
        }
      }
      await sleep(500);
    }
    const error = new Error(`operation ${body.operationId} did not reach a terminal observation within ${timeoutMs}ms`);
    error.code = "UI_CONTROL_TERMINAL_TIMEOUT";
    throw error;
  }

  stage = "connect-two-identities";
  const primary = await connect(primaryCookie, primaryCsrf);
  const secondary = await connect(secondaryCookie, secondaryCsrf);
  assertEvidence(primary.identityId !== secondary.identityId, "UI_CONTROL_IDENTITY_ISOLATION", "secondary qualification session must use a different identity");
  const snapshot = await readSnapshot(primary, primaryCookie);
  completedCases.push("two-authenticated-identities");

  stage = "concurrent-identical-admission";
  const duplicateId = `uiq:${randomUUID()}`;
  const duplicateBody = await operationBody(primary, snapshot, duplicateId, "Qualification: concurrent identical operation identity.");
  const [first, second] = await Promise.all([submit(duplicateBody), submit(duplicateBody)]);
  for (const result of [first, second]) {
    assertEvidence(result.response.ok, "UI_CONTROL_IDENTICAL_SUBMISSION", `identical submission failed with ${result.response.status}`);
    assertEvidence(result.payload?.operationId === duplicateId, "UI_CONTROL_OPERATION_ID_MISMATCH", "identical submission returned a different operation ID");
    assertEvidence(result.payload?.semanticDigest === duplicateBody.semanticDigest, "UI_CONTROL_SEMANTIC_DIGEST_MISMATCH", "identical submission returned a different semantic digest");
    assertEvidence(
      typeof result.payload?.auditTraceId === "string" && result.payload.auditTraceId.length > 0,
      "UI_CONTROL_AUDIT_TRACE_MISSING",
      "identical submission did not return a durable audit trace identity",
    );
  }
  assertEvidence(first.payload.auditTraceId === second.payload.auditTraceId, "UI_CONTROL_DUPLICATE_DURABILITY", "identical submissions did not resolve to one durable record");
  const duplicateAuditTraceId = first.payload.auditTraceId;
  completedCases.push("concurrent-identical-operation");

  stage = "semantic-conflict";
  const conflictBody = await operationBody(primary, snapshot, duplicateId, "Qualification: changed payload under the same operation identity.");
  const conflict = await submit(conflictBody);
  assertEvidence(conflict.response.status === 409, "UI_CONTROL_SEMANTIC_CONFLICT", `semantic reuse must return 409, got ${conflict.response.status}`);
  completedCases.push("changed-payload-conflict");

  stage = "pre-admission-rejection";
  const rejectedId = `uiq:${randomUUID()}`;
  const rejectedBody = await operationBody(primary, snapshot, rejectedId, "Qualification: reject before admission without CSRF.");
  const rejected = await submit(rejectedBody, primaryCookie, null);
  assertEvidence([401, 403].includes(rejected.response.status), "UI_CONTROL_PRE_ADMISSION_REJECTION", `missing CSRF must fail before admission, got ${rejected.response.status}`);
  const rejectedLookup = await lookup(primary, rejectedBody, primaryCookie);
  assertEvidence(rejectedLookup.response.ok && rejectedLookup.payload?.found === false, "UI_CONTROL_REJECTED_RECORD", "pre-admission rejection created a durable operation");
  completedCases.push("rejected-before-admission-no-record");

  stage = "cross-identity-isolation";
  const crossIdentity = await lookup(secondary, duplicateBody, secondaryCookie);
  assertEvidence(
    [401, 403, 404].includes(crossIdentity.response.status) ||
      (crossIdentity.response.ok && crossIdentity.payload?.found === false),
    "UI_CONTROL_CROSS_IDENTITY_LEAK",
    "a different authenticated identity could observe the primary operation",
  );
  completedCases.push("cross-identity-lookup-denied");

  stage = "first-operation-terminal-observation";
  const duplicateTerminal = await waitForTerminal(
    primary,
    duplicateBody,
    primaryCookie,
    duplicateAuditTraceId,
  );
  completedCases.push("first-operation-terminal-lookup");

  stage = "post-terminal-snapshot-refresh";
  const refreshedSnapshot = assertSnapshotNotRegressed(
    snapshot,
    await readSnapshot(primary, primaryCookie),
  );
  completedCases.push("fresh-snapshot-before-next-mutation");

  stage = "accepted-response-loss";
  const lossId = `uiq:${randomUUID()}`;
  const lossBody = await operationBody(primary, refreshedSnapshot, lossId, "Qualification: discard accepted acknowledgement and recover by operation ID.");
  await discardAcknowledgement(lossBody);
  const lossLookup = await lookup(primary, lossBody, primaryCookie);
  assertEvidence(lossLookup.response.ok, "UI_CONTROL_RESPONSE_LOSS_LOOKUP", `accepted response loss lookup failed with ${lossLookup.response.status}`);
  const lossObservation = assertOperationObservation(lossLookup.payload, lossBody);
  const lossAuditTraceId = lossObservation.auditTraceId;
  completedCases.push("accepted-response-loss-lookup");

  stage = "response-loss-terminal-observation";
  const lossTerminal = await waitForTerminal(
    primary,
    lossBody,
    primaryCookie,
    lossAuditTraceId,
  );
  completedCases.push("response-loss-terminal-lookup");

  stage = "final-snapshot-refresh";
  const finalSnapshot = assertSnapshotNotRegressed(
    refreshedSnapshot,
    await readSnapshot(primary, primaryCookie),
  );
  completedCases.push("post-qualification-snapshot-continuity");

  stage = "session-revocation";
  const revoke = await requestJson(new URL("session/revoke", apiBase), {
    cookie: primaryCookie,
    csrf: primaryCsrf,
    method: "POST",
    body: { sessionId: primary.sessionId, connectionGeneration: primary.connectionGeneration },
  });
  assertEvidence(revoke.response.ok, "UI_CONTROL_SESSION_REVOKE", `session revoke failed with ${revoke.response.status}`);
  const postRevoke = await requestJson(new URL("view", apiBase), {
    cookie: primaryCookie,
    method: "POST",
    body: { sessionId: primary.sessionId, connectionGeneration: primary.connectionGeneration },
  });
  assertEvidence([401, 403].includes(postRevoke.response.status), "UI_CONTROL_REVOKED_SESSION", `revoked session remained usable: ${postRevoke.response.status}`);
  completedCases.push("session-revocation");

  stage = "session-switch-and-principal-continuity";
  const reconnectedPrimary = assertSessionReconnection(
    primary,
    await connect(primaryCookie, primaryCsrf),
  );
  await readSnapshot(reconnectedPrimary, primaryCookie);
  const lookupAfterSessionSwitch = await lookup(reconnectedPrimary, duplicateBody, primaryCookie);
  assertEvidence(lookupAfterSessionSwitch.response.ok, "UI_CONTROL_SESSION_SWITCH_LOOKUP", `same-principal lookup failed with ${lookupAfterSessionSwitch.response.status}`);
  assertOperationObservation(lookupAfterSessionSwitch.payload, duplicateBody, {
    requireTerminal: true,
    expectedAuditTraceId: duplicateAuditTraceId,
  });
  const lossLookupAfterSessionSwitch = await lookup(reconnectedPrimary, lossBody, primaryCookie);
  assertEvidence(lossLookupAfterSessionSwitch.response.ok, "UI_CONTROL_SESSION_SWITCH_LOOKUP", `response-loss lookup after session switch failed with ${lossLookupAfterSessionSwitch.response.status}`);
  assertOperationObservation(lossLookupAfterSessionSwitch.payload, lossBody, {
    requireTerminal: true,
    expectedAuditTraceId: lossAuditTraceId,
  });
  const closeReconnected = await requestJson(new URL("session/close", apiBase), {
    cookie: primaryCookie,
    csrf: primaryCsrf,
    method: "POST",
    body: { sessionId: reconnectedPrimary.sessionId, connectionGeneration: reconnectedPrimary.connectionGeneration },
  });
  assertEvidence(closeReconnected.response.ok, "UI_CONTROL_RECONNECTED_CLOSE", `reconnected primary close failed with ${closeReconnected.response.status}`);
  completedCases.push("session-switch-principal-continuity");

  stage = "secondary-close";
  const closeSecondary = await requestJson(new URL("session/close", apiBase), {
    cookie: secondaryCookie,
    csrf: secondaryCsrf,
    method: "POST",
    body: { sessionId: secondary.sessionId, connectionGeneration: secondary.connectionGeneration },
  });
  assertEvidence(closeSecondary.response.ok, "UI_CONTROL_SECONDARY_CLOSE", `secondary close failed with ${closeSecondary.response.status}`);
  completedCases.push("secondary-session-close");

  await emit({
    schema: "hepta.ui-control.real-backend-receipt.v2",
    status: "passed",
    candidateCommit: source.sha,
    candidateTree: source.tree,
    backendDeploymentDigest,
    source,
    backend: {
      ...subject,
      observedAt: new Date().toISOString(),
      primaryIdentity: primary.identityId,
      secondaryIdentity: secondary.identityId,
      runtimeGeneration: finalSnapshot.generation,
      runtimeRevision: finalSnapshot.revision,
    },
    cases: completedCases,
    terminalObservations: {
      duplicateOperation: duplicateTerminal.status,
      responseLossOperation: lossTerminal.status,
    },
    operationBindings: {
      duplicateOperation: {
        operationIdSha256: sha256(duplicateBody.operationId),
        semanticDigest: duplicateBody.semanticDigest,
        auditTraceIdSha256: sha256(duplicateAuditTraceId),
      },
      responseLossOperation: {
        operationIdSha256: sha256(lossBody.operationId),
        semanticDigest: lossBody.semanticDigest,
        auditTraceIdSha256: sha256(lossAuditTraceId),
      },
    },
    evidence: {
      chaosEvidenceSha256: sha256(chaosEvidenceText),
      chaosRawEvidenceDigest: chaosSummary.rawEvidenceDigest,
      authorityEvidenceSha256: sha256(authorityEvidenceText),
    },
    claims: {
      realBackendSemanticsQualified: true,
      durableIdempotencyQualified: true,
      crashRestartQualified: true,
      permissionRevisionAndRevocationQualified: true,
      sessionSwitchQualified: true,
      deployedSecurityObserved: false,
      independentAcceptanceSigned: false,
      productionDeploymentApproved: false,
    },
  });
} catch (error) {
  await emit({
    schema: "hepta.ui-control.real-backend-receipt.v2",
    status: "failed",
    candidateCommit: source.sha,
    candidateTree: source.tree,
    backendDeploymentDigest: deployment?.digest ?? null,
    source,
    backend: deployment ? { ...deployment.subject, observedAt: new Date().toISOString() } : null,
    completedCases,
    failure: safeFailure(error, stage),
    claims: {
      realBackendSemanticsQualified: false,
      durableIdempotencyQualified: false,
      crashRestartQualified: false,
      permissionRevisionAndRevocationQualified: false,
      sessionSwitchQualified: false,
      deployedSecurityObserved: false,
      independentAcceptanceSigned: false,
      productionDeploymentApproved: false,
    },
  });
  process.exitCode = 1;
}
