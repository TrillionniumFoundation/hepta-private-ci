#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

function parseArgs(argv) {
  const out = new Map();
  for (let index = 2; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`invalid argument sequence at ${key ?? "<end>"}`);
    }
    out.set(key.slice(2), value);
  }
  return out;
}

const args = parseArgs(process.argv);
const input = resolve(args.get("input") ?? "");
const stderrPath = resolve(args.get("stderr") ?? "");
const output = resolve(args.get("output") ?? "agentd-clippy-receipt.json");
const cargoStatus = Number.parseInt(args.get("cargo-status") ?? "-1", 10);
const expectedSha = args.get("expected-sha") ?? "";

if (!Number.isSafeInteger(cargoStatus) || cargoStatus < 0 || cargoStatus > 255) {
  throw new Error("cargo-status must be an integer in [0, 255]");
}

const TRANSITIONAL_WARNINGS = [
  {
    id: "browser-decoded-frame-sequence-copy",
    fileSuffix: "hepta-agentd/src/browser_servo.rs",
    code: "dead_code",
    message: "field `sequence` is never read",
    owner: "browser-platform",
    rationale: "The protocol consumes and validates the sequence against the monotonic port state before constructing the decoded frame; the retained copy is non-authoritative and scheduled for source cleanup.",
  },
  {
    id: "retrieval-learning-convenience-wrappers",
    fileSuffix: "hepta-agentd/src/cognitive_retrieval_learning.rs",
    code: "dead_code",
    message: "methods `append` and `append_with_delivery` are never used",
    owner: "cognitive-runtime",
    rationale: "The production caller uses the policy-bearing append_with_delivery_policy entrypoint; the convenience wrappers remain an explicitly tracked cross-module cleanup item.",
  },
  {
    id: "plasticity-producer-handle",
    fileSuffix: "hepta-agentd/src/plasticity_learning_producer.rs",
    code: "dead_code",
    message: "field `handle` is never read",
    owner: "learning-runtime",
    rationale: "The producer is attached behind a separately qualified activation seam that is not selected by the browser.servo product binary.",
  },
  {
    id: "plasticity-producer-submitters",
    fileSuffix: "hepta-agentd/src/plasticity_learning_producer.rs",
    code: "dead_code",
    message: "methods `submit_parameter` and `submit_topology` are never used",
    owner: "learning-runtime",
    rationale: "These named product methods are dormant until the governed plasticity activation composition is selected; browser.servo does not promote that composition.",
  },
  {
    id: "agentd-plasticity-state-submitters",
    fileSuffix: "hepta-agentd/src/state.rs",
    code: "dead_code",
    message: "methods `submit_parameter_plasticity_v1` and `submit_topology_plasticity_v1` are never used",
    owner: "learning-runtime",
    rationale: "The state façade is intentionally disconnected from the browser.servo service binary and remains fail-closed until its independent product caller is qualified.",
  },
];

function sha256(text) {
  return createHash("sha256").update(text).digest("hex");
}

function normalizePath(path) {
  return String(path ?? "").replaceAll("\\", "/").replace(/^\.\//, "");
}

function warningFrom(message) {
  const primary = Array.isArray(message.spans)
    ? message.spans.find((span) => span?.is_primary) ?? message.spans[0]
    : null;
  return {
    level: message.level ?? null,
    code: message.code?.code ?? null,
    message: message.message ?? "",
    file: normalizePath(primary?.file_name ?? ""),
    line: Number.isSafeInteger(primary?.line_start) ? primary.line_start : null,
    column: Number.isSafeInteger(primary?.column_start) ? primary.column_start : null,
  };
}

const raw = readFileSync(input, "utf8");
const stderr = readFileSync(stderrPath, "utf8");
const compilerMessages = [];
const malformed = [];
for (const [index, line] of raw.split(/\r?\n/u).entries()) {
  if (line.trim() === "") continue;
  try {
    const record = JSON.parse(line);
    if (record?.reason === "compiler-message" && record.message) {
      compilerMessages.push(warningFrom(record.message));
    }
  } catch (error) {
    malformed.push({ line: index + 1, digest: sha256(line), error: String(error) });
  }
}

const diagnostics = compilerMessages.filter((entry) =>
  entry.level === "warning" || entry.level === "error" || entry.level === "failure-note"
);
const acknowledged = [];
const rejected = [];
for (const diagnostic of diagnostics) {
  const matched = TRANSITIONAL_WARNINGS.find((entry) =>
    diagnostic.level === "warning"
      && diagnostic.code === entry.code
      && diagnostic.file.endsWith(entry.fileSuffix)
      && diagnostic.message === entry.message
  );
  if (matched) {
    acknowledged.push({ ...diagnostic, exception: matched });
  } else {
    rejected.push(diagnostic);
  }
}

const duplicateExceptionIds = acknowledged
  .map((entry) => entry.exception.id)
  .filter((id, index, all) => all.indexOf(id) !== index);
const passed = cargoStatus === 0
  && malformed.length === 0
  && rejected.length === 0
  && duplicateExceptionIds.length === 0;
const receipt = {
  schema: "hepta.browser.servo-agentd-clippy-receipt.v1",
  module: "browser.servo",
  sourceSha: expectedSha,
  cargoExitStatus: cargoStatus,
  strict: true,
  passed,
  messageStreamSha256: sha256(raw),
  stderrSha256: sha256(stderr),
  compilerMessageCount: compilerMessages.length,
  acknowledgedWarnings: acknowledged,
  rejectedDiagnostics: rejected,
  malformedRecords: malformed,
  duplicateExceptionIds,
  exceptionPolicy: {
    exactMatchRequired: true,
    additionalWarningsFail: true,
    compilerErrorsFail: true,
    knownExceptions: TRANSITIONAL_WARNINGS,
  },
};
receipt.receiptDigest = sha256(JSON.stringify(receipt));
writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o600 });
process.stdout.write(`${JSON.stringify(receipt)}\n`);
if (!passed) process.exitCode = 1;
