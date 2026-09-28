/** Explicit real-OS qualification on a disposable, non-network Xvfb display.
 * The injected backend/authorization below are test fixtures, not production trust.
 */
import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { NativeShellRuntime } from "../src/shell-runtime.js";
import { InlineNativeReferenceResolver, nativePlatformPayloadDigestV1 } from "../src/computer-action.js";
import { clipboardTextReference, X11ClipboardPlatform } from "../src/x11-clipboard.js";
import { computerActionAuthorityBindingDigestV1, computerActionPayloadDigestV1,
  encodeComputerActionFrameV1 } from "../../../codex-rs/hepta-wire/js/computer-action-ir.js";

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const hash = (value) => sha256(Buffer.from(value));
const root = fileURLToPath(new URL("../../../", import.meta.url));
const git = (...args) => execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();
const source = { commit: git("rev-parse", "HEAD"), tree: git("rev-parse", "HEAD^{tree}"), dirty: git("status", "--porcelain") !== "" };
const server = spawn("/usr/bin/Xvfb", ["-displayfd", "3", "-screen", "0", "640x480x24", "-nolisten", "tcp", "-ac"],
  { stdio: ["ignore", "ignore", "pipe", "pipe"], env: { LANG: "C.UTF-8" }, shell: false });
server.stderr.resume();
let platform, runtime;
try {
  const number = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("isolated X server readiness timed out")), 5000);
    server.once("error", (error) => { clearTimeout(timer); reject(error); });
    server.stdio[3].once("data", (data) => { clearTimeout(timer); resolve(data.toString().trim()); });
  });
  assert.match(number, /^[0-9]{1,5}$/);
  const display = `:${number}`;
  const executable = "/usr/bin/xclip";
  const executableSha256 = sha256(readFileSync(executable));
  const text = "Hepta isolated clipboard / 原生二进制执行验证 / no secrets";
  const resource = clipboardTextReference(text);
  const origin = process.hrtime.bigint();
  const clock = () => Number((process.hrtime.bigint() - origin) / 1000n) + 1;
  const payload = { kind: "reference", referenceId: "clipboard.text.1" };
  const frame = { operationId: "operation.clipboard.1", subjectId: "principal.qualifier",
    actuatorId: "native-shell", opcode: "copy_text_reference", targetRef: null,
    bodyGeneration: 1, sessionGeneration: 1, observationRevision: 1,
    deadlineMonotonicMicros: clock() + 5_000_000, preconditionDigest: hash("isolated-display-view"),
    argumentPayloadDigest: computerActionPayloadDigestV1("copy_text_reference", payload),
    finalPayloadDigest: nativePlatformPayloadDigestV1("copy_text", resource),
    expectedPostconditionDigest: hash("content-equal-in-isolated-clipboard"), payload };
  const expected = computerActionAuthorityBindingDigestV1(frame);
  let finalUseCalls = 0;
  platform = new X11ClipboardPlatform({ executablePath: executable, executableSha256, display,
    resources: [{ resource, text }], monotonicMicros: clock,
    finalUse: { withVerifiedUse(request, dispatch) {
      assert.equal(request.sourceActionDigest, expected);
      assert.equal(request.operationId, frame.operationId);
      assert.equal(request.finalPayloadDigest, frame.finalPayloadDigest);
      assert.equal(request.sessionGeneration, 1);
      assert.ok(clock() < request.deadlineMonotonicMicros);
      assert.equal(finalUseCalls++, 0);
      dispatch();
    } } });
  runtime = new NativeShellRuntime({ platform, principalId: frame.subjectId, bodyGeneration: 1,
    monotonicMicros: clock, clock: () => Date.now(),
    binaryResolver: new InlineNativeReferenceResolver([{ referenceId: payload.referenceId, resource }]),
    backend: { async connect() { return { authenticated: true, protocolVersion: 1, sessionId: "session.qualifier", generation: 1 }; },
      async request() { throw new Error("unused qualification backend"); }, async close() {} },
    updater: { async verify() { throw new Error("updates not authorized"); }, async apply() { throw new Error("updates not authorized"); }, async rollback() {} } });
  await runtime.connectRuntime({ endpointId: "runtime.qualifier", manifestDigest: hash("fixture-backend"), protocolVersion: 1 });
  runtime.renderRuntimeView({ sessionId: "session.qualifier", sessionGeneration: 1, generation: 1,
    revision: 1, digest: frame.preconditionDigest, modules: [] });
  const bytes = encodeComputerActionFrameV1(frame);
  const began = process.hrtime.bigint();
  const result = await runtime.requestPlatformCapabilityBinary({ frameBytes: bytes, grantPayloadDigest: frame.finalPayloadDigest });
  assert.equal(result.status, "succeeded");
  const elapsedMicros = Number((process.hrtime.bigint() - began) / 1000n);
  const readback = execFileSync(executable, ["-display", display, "-selection", "clipboard", "-out"],
    { env: { DISPLAY: display, LANG: "C.UTF-8" }, timeout: 1000, maxBuffer: 65536 });
  assert.deepEqual(readback, Buffer.from(text));
  const retry = await runtime.requestPlatformCapabilityBinary({ frameBytes: bytes, grantPayloadDigest: frame.finalPayloadDigest });
  assert.deepEqual(retry, result);
  const changed = { ...frame, expectedPostconditionDigest: hash("different-postcondition") };
  await assert.rejects(runtime.requestPlatformCapabilityBinary({ frameBytes: encodeComputerActionFrameV1(changed),
    grantPayloadDigest: changed.finalPayloadDigest }), /changed semantics/);
  await runtime.close();
  const observation = runtime.observePlatformOperationBinary({ operationId: frame.operationId, sourceActionDigest: expected });
  assert.deepEqual(observation.receipt, result);
  const cleanup = await platform.close();
  assert.deepEqual(cleanup, { stopped: true, unresolvedWriters: 0 });
  assert.equal(finalUseCalls, 1);
  const receipt = { schema: "hepta.native-x11-clipboard-qualification.v1", source,
    executableSha256, xvfbSha256: sha256(readFileSync("/usr/bin/Xvfb")), frameSha256: sha256(bytes),
    sourceActionDigest: expected, outcomeDigest: result.outcomeDigest, readbackSha256: sha256(readback),
    elapsedMicros, finalUseCalls, exactRetryReused: true, changedIntentRejected: true,
    observationAfterClose: true, writerCleanupObserved: true, realOsClipboard: true,
    isolatedDisplay: true, tcpListenerEnabled: false, backendAndAuthorityAreFixtures: true,
    independentPrincipalObservation: false, durableCrossProcessRecovery: false,
    productionActivation: false, operatorAcceptance: false };
  const encoded = JSON.stringify(receipt, null, 2) + "\n";
  if (process.argv[2]) writeFileSync(process.argv[2], encoded, { flag: "wx", mode: 0o600 });
  console.log(encoded);
} finally {
  if (runtime) await runtime.close();
  if (platform) await platform.close();
  server.kill("SIGTERM");
  await new Promise((resolve) => {
    if (server.exitCode !== null || server.signalCode !== null) return resolve();
    const timer = setTimeout(() => { server.kill("SIGKILL"); resolve(); }, 1000);
    server.once("close", () => { clearTimeout(timer); resolve(); });
  });
}
