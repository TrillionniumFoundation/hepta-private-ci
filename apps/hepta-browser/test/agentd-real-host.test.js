import assert from "node:assert/strict";
import test from "node:test";
import { spawn } from "node:child_process";
import { mkdtemp, rm, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { PassThrough } from "node:stream";
import { browserActionDigest } from "../src/action.js";
import { AgentdBrowserChannel, BrowserAgentdService, ParentFinalUseAuthority } from "../src/agentd-service.js";
import { FileBrowserOperationJournal } from "../src/journal.js";
import { BrowserProfileHost } from "../src/runtime.js";

const D1 = "1".repeat(64), D2 = "2".repeat(64), D3 = "3".repeat(64), D4 = "4".repeat(64);
const scope = { profileId: "profile.1", principalId: "principal.1", generation: 1 };
const action = { kind: "click", selector: "#approved" };
const actionDigest = browserActionDigest(action);
const operation = { ...scope, operationId: "operation.1", pageGeneration: 1,
  typedAction: action, destinationOrigin: "https://example.test", finalPayloadDigest: actionDigest,
  effectGrantDigest: D4, authorityEpoch: 7, deadlineMs: 7_000 };

async function composition(t, { path, terminal = false } = {}) {
  const root = await mkdtemp(join(tmpdir(), "hepta-browser-host-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const journal = new FileBrowserOperationJournal(path ?? join(root, "operations.jsonl"));
  const inbound = new PassThrough(), outbound = new PassThrough();
  const parent = new AgentdBrowserChannel({ input: outbound, output: inbound });
  const child = new AgentdBrowserChannel({ input: inbound, output: outbound });
  const authority = new ParentFinalUseAuthority(child);
  const counts = { dispatch: 0, reconcile: 0 };
  const host = new BrowserProfileHost({ journal, authority, clock: () => 1_000,
    driverCallTimeoutMs: 1_000,
    driver: {
      async start() { return { started: true, processId: "worker.1" }; },
      async observe() { return { pageGeneration: 1, documentDigest: D3, origin: "https://example.test" }; },
      async dispatch() { counts.dispatch++; return { terminalObserved: false }; },
      async reconcile() {
        counts.reconcile++;
        return terminal ? { terminalObserved: true, status: "succeeded", outcomeDigest: D2 }
          : { terminalObserved: false };
      },
      async stop() { return { stopped: true }; },
    },
  });
  // The selected production class, not the plain-object host double used by
  // earlier service tests. Driver replies remain controlled observations.
  const service = new BrowserAgentdService({ host, channel: child, authority });
  const running = service.run();
  running.catch(() => {}); // Attach before any injected failure; checked by close.
  let closed = false;
  async function close() {
    if (closed) return;
    closed = true;
    inbound.end(); outbound.end();
    await running;
  }
  t.after(close);
  let sequence = 0;
  async function request(method, input) {
    const requestId = `request.${++sequence}`;
    await parent.send("request", requestId, { method, input });
    const response = await parent.nextFrame();
    assert.equal(response?.kind, "response");
    assert.equal(response.requestId, requestId);
    assert.equal(response.payload.ok, true, response.payload.error);
    return response.payload.result;
  }
  return { parent, journal, counts, request, close, root };
}

async function openObserved(f) {
  await f.request("open_profile", { ...scope, manifestDigest: D1, grantDigest: D2, expiresAtMs: 9_000,
    allowedOrigins: ["https://example.test"], effectGrants: [{ grantDigest: D4, action: "click",
      destinationOrigin: "https://example.test", finalPayloadDigest: actionDigest,
      authorityEpoch: 7, expiresAtMs: 8_000 }] });
  await f.request("observe_page", { ...scope, observationBudget: 64 });
}

test("real selected host composes with private authority and durable operation recovery", { timeout: 10_000 }, async (t) => {
  const f = await composition(t);
  await openObserved(f);
  await f.parent.send("request", "request.effect", { method: "navigate_or_act", input: operation });
  const challenge = await f.parent.nextFrame();
  assert.equal(challenge.kind, "authority_challenge");
  assert.equal(f.counts.dispatch, 0);
  assert.deepEqual(await f.journal.listOperations(scope.profileId, scope.generation), []);
  await f.parent.send("authority_enter", "request.effect", { authorized: true,
    witnessDigest: D4, requestDigest: challenge.payload.requestDigest, authorityEpoch: 7 });
  const boundary = await f.parent.nextFrame();
  assert.equal(boundary.kind, "dispatch_boundary");
  const response = await f.parent.nextFrame();
  assert.equal(response.kind, "response");
  assert.equal(response.payload.ok, true, response.payload.error);
  assert.equal(response.payload.result.status, "indeterminate");
  assert.equal(response.payload.result.terminalObserved, false);
  assert.equal(f.counts.dispatch, 1);
  assert.equal((await f.journal.listOperations(scope.profileId, 1)).length, 1);
  assert.deepEqual(await f.request("navigate_or_act", operation), response.payload.result);
  assert.equal(f.counts.dispatch, 1);
  await f.close();

  // A fresh selected host reads the actual fsynced file and reconciles the old
  // operation without entering a new authority fence or re-running dispatch.
  const recovered = await composition(t, { path: join(f.root, "operations.jsonl"), terminal: true });
  const observed = await recovered.request("reconcile_persisted_operation", operation);
  assert.equal(observed.status, "succeeded");
  assert.equal(observed.outcomeDigest, D2);
  assert.equal(observed.terminalObserved, true);
  assert.deepEqual(recovered.counts, { dispatch: 0, reconcile: 1 });
  assert.deepEqual(await recovered.request("reconcile_persisted_operation", operation), observed);
  assert.deepEqual(recovered.counts, { dispatch: 0, reconcile: 1 });
  await recovered.close();
});

test("real selected host rejects a mismatched final-use witness without durable dispatch", { timeout: 10_000 }, async (t) => {
  const f = await composition(t);
  await openObserved(f);
  await f.parent.send("request", "request.denied", { method: "navigate_or_act", input: operation });
  const challenge = await f.parent.nextFrame();
  assert.equal(challenge.kind, "authority_challenge");
  await f.parent.send("authority_enter", "request.denied", { authorized: true,
    witnessDigest: D4, requestDigest: challenge.payload.requestDigest, authorityEpoch: 8 });
  const response = await f.parent.nextFrame();
  assert.equal(response.kind, "response");
  assert.equal(response.payload.ok, false);
  assert.match(response.payload.error, /does not bind/);
  assert.equal(f.counts.dispatch, 0);
  assert.deepEqual(await f.journal.listOperations(scope.profileId, 1), []);
  await f.close();
});

test("actual service executable starts and rejects an unopened profile without launching a worker", { timeout: 10_000 }, async (t) => {
  const root = await mkdtemp(join(tmpdir(), "hepta-browser-main-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const child = spawn(process.execPath, [fileURLToPath(new URL("../src/agentd-service-main.js", import.meta.url))], {
    stdio: ["pipe", "pipe", "pipe"],
    env: { PATH: process.env.PATH ?? "", LANG: "C.UTF-8",
      HEPTA_BROWSER_WORKER_PATH: join(root, "absent-worker"),
      HEPTA_BROWSER_WORKER_SHA256: D1,
      HEPTA_BROWSER_PROFILE_ROOT: join(root, "profiles"),
      HEPTA_BROWSER_JOURNAL_PATH: join(root, "operations.jsonl") },
  });
  const exit = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });
  let stderr = "";
  child.stderr.on("data", (bytes) => { stderr = (stderr + bytes.toString()).slice(-8192); });
  const timer = setTimeout(() => child.kill("SIGKILL"), 5_000);
  t.after(async () => { clearTimeout(timer); child.stdin.destroy(); if (child.exitCode === null) child.kill("SIGKILL"); await exit; });
  if (process.platform !== "linux") {
    child.stdin.end();
    assert.deepEqual(await exit, { code: 1, signal: null });
    assert.match(stderr, /requires the qualified Linux launcher/);
    return;
  }
  const parent = new AgentdBrowserChannel({ input: child.stdout, output: child.stdin });
  await parent.send("request", "startup.1", { method: "observe_page", input: { ...scope, observationBudget: 64 } });
  const response = await parent.nextFrame();
  assert.equal(response?.kind, "response", stderr);
  assert.equal(response.payload.ok, false);
  assert.match(response.payload.error, /profile is not open/);
  child.stdin.end();
  assert.deepEqual(await exit, { code: 0, signal: null }, stderr);
  await assert.rejects(access(join(root, "profiles")), { code: "ENOENT" });
  await assert.rejects(access(join(root, "operations.jsonl")), { code: "ENOENT" });
});
