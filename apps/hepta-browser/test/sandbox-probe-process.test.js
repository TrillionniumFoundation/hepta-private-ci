import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import test from "node:test";
import {
  observeProbeProcess, probeProcessIdentity, snapshotProbeTree, waitForProbeTreeExit,
} from "../scripts/sandbox-probe-process.js";

function fixture(t, source, options, cleanupSignal = "SIGKILL") {
  const child = spawn(process.execPath, ["--input-type=module", "-e", source], { stdio: "pipe" });
  const observed = observeProbeProcess(child, options);
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) child.kill(cleanupSignal);
    await observed.completion.catch(() => {});
  });
  return { child, observed };
}

test("probe completion drains all output through close", async t => {
  const { observed } = fixture(t, "process.stdout.write('finished\\n');process.stderr.write('detail\\n');");
  const result = await observed.completion;
  assert.equal(result.stdout, "finished\n");
  assert.equal(result.stderr, "detail\n");
  assert.deepEqual(result.exit, { code: 0, signal: null });
});

test("probe readiness retains the parent until explicit release", async t => {
  const { child, observed } = fixture(t, `
    process.stdout.write('rea'); setTimeout(() => process.stdout.write('dy\\n'), 20);
    process.stdin.once('data', () => process.exit(0));
  `);
  assert.equal(await observed.readyLine(), "ready");
  assert.equal(child.exitCode, null);
  assert.equal(child.signalCode, null);
  child.stdin.end("release\n");
  await observed.completion;
});

test("early zero exit is not readiness evidence", async t => {
  const { observed } = fixture(t, "process.stdout.write('ready\\n');");
  await observed.completion;
  await assert.rejects(observed.readyLine(), /exited before readiness/);
});

test("SIGKILL with a printed marker cannot qualify successful execution", async t => {
  const { child, observed } = fixture(t, "process.stdout.write('ready\\n');setInterval(()=>{},1000)");
  await observed.readyLine();
  child.kill("SIGKILL");
  await assert.rejects(observed.completion, error => {
    assert.equal(error.probe.exit.signal, "SIGKILL");
    assert.equal(error.probe.stdout, "ready\n");
    return true;
  });
});

test("hung probe is killed and remains failed at its deadline", async t => {
  const { observed } = fixture(t, "setInterval(()=>{},1000)", { timeoutMs: 100 });
  await assert.rejects(observed.completion, /deadline exceeded/);
});

for (const stream of ["stdout", "stderr"]) {
  test(`probe ${stream} cannot exhaust the diagnostic budget`, async t => {
    const { observed } = fixture(t, `process.${stream}.write('x'.repeat(65536));setInterval(()=>{},1000)`, { maxOutputBytes: 128 });
    await assert.rejects(observed.completion, error => {
      assert.match(error.message, /exceeds diagnostic budget/);
      assert.equal(Buffer.byteLength(error.probe[stream]), 128);
      return true;
    });
  });
}

test("probe spawn error is retained rather than reported as successful close", async () => {
  const child = spawn("/hepta-probe-no-such-program", [], { stdio: "pipe" });
  const observed = observeProbeProcess(child);
  await assert.rejects(observed.completion, /process error/);
});

test("readiness timeout cannot be satisfied by a partial line", async t => {
  const { observed } = fixture(t, "process.stdout.write('ready');setInterval(()=>{},1000)");
  await assert.rejects(observed.readyLine({ timeoutMs: 100 }), /readiness deadline exceeded/);
  await assert.rejects(observed.completion);
});

test("process census rejects missing and unsafe host identities", async () => {
  for (const pid of [0, 1, -1, 1.5, true]) await assert.rejects(probeProcessIdentity(pid), TypeError);
  await assert.rejects(snapshotProbeTree(2_147_483_647), /disappeared/);
  await assert.rejects(waitForProbeTreeExit([]), TypeError);
  await assert.rejects(waitForProbeTreeExit([{ pid: 3, startTime: "1" }, { pid: 3, startTime: "1" }]), /duplicate/);
});

test("real child and descendant are captured before release and both must disappear", async t => {
  const { child, observed } = fixture(t, `
    import { spawn } from 'node:child_process';
    const leaf = spawn(process.execPath, ['-e', "process.stdout.write('alive');setInterval(()=>{},1000)"], {stdio:['ignore','pipe','ignore']});
    leaf.stdout.once('data', () => process.stdout.write('ready\\n'));
    const stop = () => { leaf.once('close', () => process.exit(0)); leaf.kill('SIGTERM'); };
    process.stdin.once('data', stop);
    process.on('SIGTERM', stop);
  `, undefined, 'SIGTERM');
  // Reap the descendant before the fixture parent on assertion failure too.
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) {
      child.stdin.end("release\n");
      await observed.completion.catch(() => {});
    }
  });
  assert.equal(await observed.readyLine(), "ready");
  const identities = await snapshotProbeTree(child.pid);
  assert.ok(identities.length >= 2);
  assert.ok(identities.every(value => /^\d+$/.test(value.startTime)));
  await assert.rejects(waitForProbeTreeExit(identities, 30), /lifetimes remain/);
  child.stdin.end("release\n");
  await observed.completion;
  await waitForProbeTreeExit(identities);
});
