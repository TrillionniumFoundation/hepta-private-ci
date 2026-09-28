import assert from "node:assert/strict";
import test from "node:test";
import { clipboardTextReference, X11ClipboardPlatform } from "../src/x11-clipboard.js";
import { nativePlatformPayloadDigestV1 } from "../src/computer-action.js";

const text = "Hepta clipboard qualification — 合法文本";
const resource = clipboardTextReference(text);
const profile = (overrides = {}) => ({ executablePath: "/nonexistent/hepta-xclip-test",
  executableSha256: "1".repeat(64), display: ":12345", resources: [{ resource, text }],
  monotonicMicros: () => 1, finalUse: { withVerifiedUse() { throw new Error("authority denied"); } }, ...overrides });
const request = (overrides = {}) => ({ sessionId: "session.1", sessionGeneration: 1,
  operationId: "operation.1", action: "copy_text", resource,
  finalPayloadDigest: nativePlatformPayloadDigestV1("copy_text", resource),
  sourceActionDigest: "2".repeat(64), deadlineMonotonicMicros: 1000, ...overrides });

test("clipboard content identity binds exact UTF-8, not a caller-controlled alias", () => {
  assert.notEqual(clipboardTextReference(text), clipboardTextReference(text + "!"));
  for (const bad of ["", "x\0y", "\ud800", "x".repeat(65537), 12]) {
    assert.throws(() => clipboardTextReference(bad), /bounded exact UTF-8/);
  }
});

test("clipboard profile rejects changed content, duplicates and remote displays", () => {
  assert.throws(() => new X11ClipboardPlatform(profile({ resources: [{ resource, text: "replaced" }] })), /content-addressed/);
  assert.throws(() => new X11ClipboardPlatform(profile({ resources: [{ resource, text }, { resource, text }] })), /unique/);
  assert.throws(() => new X11ClipboardPlatform(profile({ display: "untrusted.example:0" })), /host profile/);
});

test("availability cannot bypass the host's final-use authorizer", async () => {
  const platform = new X11ClipboardPlatform(profile());
  assert.equal(platform.permission(request()).allowed, true);
  await assert.rejects(platform.invoke(request()), /authority denied/);
  assert.deepEqual(await platform.close(), { stopped: true, unresolvedWriters: 0 });
});

test("changed resource, payload, deadline and unsupported actions reject before authority", async () => {
  let authorizations = 0;
  const platform = new X11ClipboardPlatform(profile({ finalUse: { withVerifiedUse() { ++authorizations; } } }));
  for (const overrides of [{ resource: "unregistered" }, { finalPayloadDigest: "3".repeat(64) },
    { deadlineMonotonicMicros: 1 }, { action: "notify" }, { sourceActionDigest: "0".repeat(64) }]) {
    await assert.rejects(platform.invoke(request(overrides)), /not currently admissible/);
  }
  assert.equal(authorizations, 0);
  await platform.close();
});

test("clipboard input accessors and hidden fields reject without executing them", async () => {
  const platform = new X11ClipboardPlatform(profile());
  let read = false;
  const value = request();
  Object.defineProperty(value, "operationId", { enumerable: true, get() { read = true; return "operation.1"; } });
  await assert.rejects(platform.invoke(value), /exact own data fields/);
  await assert.rejects(platform.invoke({ ...request(), extra: true }), /exact own data fields/);
  assert.equal(read, false);
  await platform.close();
});

test("a final-use callback retained after return cannot later dispatch", async () => {
  let saved;
  const platform = new X11ClipboardPlatform(profile({ finalUse: { withVerifiedUse(_, start) { saved = start; } } }));
  await assert.rejects(platform.invoke(request()), /was not authorized/);
  assert.throws(() => saved(), /dispatch is closed/);
  await platform.close();
});

test("asynchronous final-use is not silently interpreted as permission", async () => {
  let saved;
  const platform = new X11ClipboardPlatform(profile({ finalUse: { withVerifiedUse(_, start) { saved = start; return Promise.resolve(); } } }));
  await assert.rejects(platform.invoke(request()), /synchronous final-use/);
  assert.throws(() => saved(), /dispatch is closed/);
  await platform.close();
});

test("closed adapter cannot revive an old authorized request", async () => {
  const platform = new X11ClipboardPlatform(profile());
  await platform.close();
  assert.equal(platform.permission(request()).allowed, false);
  await assert.rejects(platform.invoke(request()), /not currently admissible/);
});
