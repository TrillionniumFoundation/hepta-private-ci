import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, writeFileSync, existsSync, chmodSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { clipboardTextReference, X11ClipboardPlatform } from "../src/x11-clipboard.js";
import { nativePlatformPayloadDigestV1 } from "../src/computer-action.js";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const now = () => Number(process.hrtime.bigint() / 1000n);
const alive = (pid) => { try { process.kill(pid, 0); return true; } catch (error) {
  if (error.code === "ESRCH") return false; throw error;
} };

test("timed-out clipboard observers are physically reaped, including SIGTERM-resistant processes",
  { skip: process.platform !== "linux", timeout: 10000 }, async () => {
  const directory = mkdtempSync(join(tmpdir(), "hepta-clipboard-process-"));
  const log = join(directory, "children.log");
  const executable = join(directory, "clipboard-fixture");
  const children = () => existsSync(log) ? readFileSync(log, "utf8").trim().split("\n")
    .filter(Boolean).map((line) => { const [pid, kind] = line.split(" "); return { pid: Number(pid), kind }; }) : [];
  let platform;
  try {
    // Owned test process only: it records its PID, ignores graceful stop, and
    // never opens the display or touches a real clipboard.
    writeFileSync(executable, `#!/usr/bin/python3
import os, signal, sys
signal.signal(signal.SIGTERM, signal.SIG_IGN)
with open(${JSON.stringify(log)}, "a") as stream:
    stream.write(str(os.getpid()) + " " + ("observer" if "-out" in sys.argv else "writer") + "\\n")
while True:
    signal.pause()
`);
    chmodSync(executable, 0o700);
    const text = "bounded observer cleanup", resource = clipboardTextReference(text);
    platform = new X11ClipboardPlatform({ executablePath: executable,
      executableSha256: createHash("sha256").update(readFileSync(executable)).digest("hex"),
      display: ":12345", resources: [{ resource, text }], monotonicMicros: now,
      finalUse: { withVerifiedUse(_, dispatch) { dispatch(); } } });
    const result = await platform.invoke({ sessionId: "session.process", sessionGeneration: 1,
      operationId: "operation.process", action: "copy_text", resource,
      finalPayloadDigest: nativePlatformPayloadDigestV1("copy_text", resource),
      sourceActionDigest: "2".repeat(64), deadlineMonotonicMicros: now() + 500000 });
    assert.equal(result.status, "indeterminate");
    assert.equal(result.terminalObserved, false);
    const observed = children();
    assert.ok(observed.some((child) => child.kind === "observer"), "must exercise a real observer");
    const closed = await platform.close();
    assert.equal(closed.stopped, true);
    assert.deepEqual(observed.filter((child) => alive(child.pid)), [], "no child survives bounded close");
  } finally {
    await platform?.close();
    const owned = children();
    for (const child of owned) { try { process.kill(child.pid, "SIGKILL"); } catch {} }
    for (let attempt = 0; attempt < 50 && owned.some((child) => alive(child.pid)); ++attempt) await sleep(10);
    rmSync(directory, { recursive: true, force: true });
  }
});
