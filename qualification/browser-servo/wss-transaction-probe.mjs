#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

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
const endpoint = args.get("url") ?? "";
const sourceSha = args.get("source-sha") ?? "";
const manifestPath = resolve(args.get("candidate-manifest") ?? "candidate-manifest.json");
const output = resolve(args.get("output") ?? "wss-transaction.json");
const required = (args.get("required") ?? "false") === "true";
const timeoutMs = Number(args.get("timeout-ms") ?? "60000");
if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1000 || timeoutMs > 300000) {
  throw new Error("timeout-ms is outside the qualification bound");
}

function emit(receipt, exitCode = 0) {
  writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o600 });
  process.stdout.write(`${JSON.stringify(receipt)}\n`);
  if (exitCode !== 0) process.exitCode = exitCode;
}

if (!endpoint) {
  emit({
    schema: "hepta.browser.servo-wss-transaction-receipt.v1",
    executed: false,
    required,
    reason: "wss_endpoint_not_configured",
    sourceSha,
    phases: [],
  }, required ? 2 : 0);
} else {
  if (!endpoint.startsWith("wss://")) {
    throw new Error("qualification endpoint must use wss://");
  }
  if (!/^[0-9a-f]{40}$/.test(sourceSha)) throw new Error("source-sha must be lowercase Git SHA-1");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  if (manifest.source?.sha !== sourceSha || manifest.archivedProbe !== false) {
    throw new Error("candidate manifest is not bound to the requested exact source");
  }

  const requestId = `browser-servo-qualification.${randomUUID()}`;
  const expected = ["accepted", "executed", "committed", "observed"];
  const observed = [];
  const messages = [];
  const startedAt = new Date().toISOString();
  const protocols = (process.env.BROWSER_SERVO_WSS_SUBPROTOCOLS ?? "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);

  const receipt = await new Promise((resolveReceipt) => {
    const socket = protocols.length > 0 ? new WebSocket(endpoint, protocols) : new WebSocket(endpoint);
    let complete = false;
    const finish = (value) => {
      if (complete) return;
      complete = true;
      clearTimeout(timer);
      try { socket.close(); } catch { /* best effort */ }
      resolveReceipt(value);
    };
    const timer = setTimeout(() => finish({
      executed: false,
      reason: "wss_transaction_timeout",
    }), timeoutMs);

    socket.addEventListener("open", () => {
      socket.send(JSON.stringify({
        schema: "hepta.browser.servo-wss-qualification.v1",
        protocolVersion: 1,
        requestId,
        sourceSha,
        candidate: {
          agentdSha256: manifest.artifacts.agentd.sha256,
          servoWorkerSha256: manifest.artifacts.servoWorker.sha256,
          manifestDigest: manifest.manifestDigest,
        },
        operation: "browser_servo_product_probe",
      }));
    });
    socket.addEventListener("message", (event) => {
      let value;
      try { value = JSON.parse(String(event.data)); }
      catch { finish({ executed: false, reason: "wss_non_json_message" }); return; }
      messages.push(value);
      if (value.requestId !== requestId) return;
      const phase = value.phase ?? value.state ?? value.status;
      if (phase !== expected[observed.length]) {
        finish({ executed: false, reason: "wss_phase_order_violation", phase });
        return;
      }
      observed.push(phase);
      if (observed.length === expected.length) {
        finish({ executed: true, reason: null });
      }
    });
    socket.addEventListener("error", () => finish({ executed: false, reason: "wss_transport_error" }));
    socket.addEventListener("close", () => {
      if (!complete && observed.length !== expected.length) {
        finish({ executed: false, reason: "wss_closed_before_observed" });
      }
    });
  });

  const result = {
    schema: "hepta.browser.servo-wss-transaction-receipt.v1",
    sourceSha,
    requestId,
    endpointOrigin: new URL(endpoint).origin,
    startedAt,
    finishedAt: new Date().toISOString(),
    required,
    executed: receipt.executed,
    reason: receipt.reason,
    phases: observed,
    exactSequenceObserved: JSON.stringify(observed) === JSON.stringify(expected),
    messageCount: messages.length,
  };
  emit(result, result.executed && result.exactSequenceObserved ? 0 : (required ? 1 : 0));
}
