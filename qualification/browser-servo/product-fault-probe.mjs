#!/usr/bin/env node

import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

function parseArgs(argv) {
  const out = new Map();
  for (let index = 2; index < argv.length; index += 2) {
    if (!argv[index]?.startsWith("--") || argv[index + 1] === undefined) {
      throw new Error(`invalid argument sequence at ${argv[index] ?? "<end>"}`);
    }
    out.set(argv[index].slice(2), argv[index + 1]);
  }
  return out;
}

const args = parseArgs(process.argv);
const agentd = resolve(args.get("agentd") ?? "");
const worker = resolve(args.get("worker") ?? "");
const output = resolve(args.get("output") ?? "product-fault-probe.json");
const timeoutMs = Number(args.get("timeout-ms") ?? "10000");
if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1000 || timeoutMs > 120000) {
  throw new Error("timeout-ms is outside the qualification bound");
}

function bounded(value) {
  return value.toString("utf8").slice(0, 4096);
}

async function run(path, commandArgs, input = null) {
  const started = Date.now();
  const child = spawn(path, commandArgs, {
    stdio: ["pipe", "pipe", "pipe"],
    env: { PATH: process.env.PATH ?? "" },
  });
  const stdout = [];
  const stderr = [];
  child.stdout.on("data", (chunk) => stdout.push(Buffer.from(chunk)));
  child.stderr.on("data", (chunk) => stderr.push(Buffer.from(chunk)));
  child.stdin.on("error", (error) => {
    if (error?.code !== "EPIPE") throw error;
  });
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    child.kill("SIGKILL");
  }, timeoutMs);
  if (input === null) child.stdin.end();
  else child.stdin.end(input);
  const result = await new Promise((resolveResult, reject) => {
    child.once("error", reject);
    child.once("close", (code, signal) => resolveResult({ code, signal }));
  });
  clearTimeout(timer);
  return {
    ...result,
    timedOut,
    durationMs: Date.now() - started,
    stdout: bounded(Buffer.concat(stdout)),
    stderr: bounded(Buffer.concat(stderr)),
  };
}

function failedClosed(result) {
  return result.timedOut === false && result.code !== 0 && result.durationMs <= timeoutMs;
}
function redacted(result) {
  return {
    code: result.code,
    signal: result.signal,
    timedOut: result.timedOut,
    durationMs: result.durationMs,
    stdoutSha256: createHash("sha256").update(result.stdout).digest("hex"),
    stderrSha256: createHash("sha256").update(result.stderr).digest("hex"),
    stderrPreview: result.stderr.slice(0, 512),
  };
}

const temporary = mkdtempSync(join(tmpdir(), "browser-servo-fault-probe-"));
try {
  const malformedConfig = join(temporary, "malformed.json");
  writeFileSync(malformedConfig, "{not-json}\n", { mode: 0o600 });
  chmodSync(malformedConfig, 0o600);

  const noArgsFirst = await run(agentd, []);
  const noArgsSecond = await run(agentd, []);
  const missingConfig = await run(agentd, [join(temporary, "missing.json")]);
  const malformedConfigResult = await run(agentd, [malformedConfig]);

  const malformedWorkerFrame = Buffer.concat([
    Buffer.from([0, 0, 0, 2]),
    Buffer.from("{}", "utf8"),
  ]);
  const workerMalformed = await run(worker, [], malformedWorkerFrame);

  const faultSuitePassed = process.env.BROWSER_SERVO_FAULT_SUITE_PASSED === "true";
  const receipt = {
    schema: "hepta.browser.servo-product-fault-probe.v1",
    agentdCandidateSha256: createHash("sha256").update(readFileSync(agentd)).digest("hex"),
    workerCandidateSha256: createHash("sha256").update(readFileSync(worker)).digest("hex"),
    agentdNoArgumentFailureClosed: failedClosed(noArgsFirst),
    agentdMissingConfigFailureClosed: failedClosed(missingConfig),
    agentdMalformedConfigFailureClosed: failedClosed(malformedConfigResult),
    agentdRestartDeterministic: failedClosed(noArgsFirst) && failedClosed(noArgsSecond)
      && noArgsFirst.code === noArgsSecond.code,
    workerMalformedFrameRejected: failedClosed(workerMalformed),
    timeoutLateResultRecoverySuitePassed: faultSuitePassed,
    observations: {
      noArgsFirst: redacted(noArgsFirst),
      noArgsSecond: redacted(noArgsSecond),
      missingConfig: redacted(missingConfig),
      malformedConfig: redacted(malformedConfigResult),
      workerMalformedFrame: redacted(workerMalformed),
    },
  };
  receipt.fullyPassed = [
    receipt.agentdNoArgumentFailureClosed,
    receipt.agentdMissingConfigFailureClosed,
    receipt.agentdMalformedConfigFailureClosed,
    receipt.agentdRestartDeterministic,
    receipt.workerMalformedFrameRejected,
    receipt.timeoutLateResultRecoverySuitePassed,
  ].every(Boolean);
  writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o600 });
  process.stdout.write(`${JSON.stringify(receipt)}\n`);
  if (!receipt.fullyPassed) process.exitCode = 1;
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
