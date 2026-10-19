#!/usr/bin/env node
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const output = resolve(root, process.argv[2] ?? "ui-control-evidence/observation.json");
const stage = process.env.UI_CONTROL_OBSERVATION_STAGE ?? "unknown";
const acceptanceReceipt = resolve(root, process.env.UI_CONTROL_ACCEPTANCE_RECEIPT ?? "ui-control-evidence/receipt.json");
const git = (...args) => execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();
const sha256 = value => createHash("sha256").update(value).digest("hex");
const exists = async path => {
  try { await access(path); return true; } catch { return false; }
};

const checks = Object.fromEntries(
  Object.entries(process.env)
    .filter(([name]) => name.startsWith("UI_CONTROL_CHECK_"))
    .map(([name, value]) => [name.slice("UI_CONTROL_CHECK_".length).toLowerCase(), value]),
);
const jobStatus = process.env.UI_CONTROL_JOB_STATUS ?? "unknown";
const receiptExists = await exists(acceptanceReceipt);
const receiptBytes = receiptExists ? await readFile(acceptanceReceipt) : null;
const accepted = jobStatus === "success" && checks.acceptance === "success" && receiptExists;
const currentSha = git("rev-parse", "HEAD");
const currentTree = git("rev-parse", "HEAD^{tree}");
const observation = {
  schema: "hepta.ui-control.observation-receipt.v1",
  observedAt: new Date().toISOString(),
  stage,
  subject: {
    evaluated: { sha: currentSha, tree: currentTree },
    sourceHeadSha: process.env.UI_CONTROL_SOURCE_SHA || currentSha,
    baseSha: process.env.UI_CONTROL_BASE_SHA || null,
  },
  workflow: {
    repository: process.env.GITHUB_REPOSITORY ?? null,
    runId: process.env.GITHUB_RUN_ID ?? null,
    runAttempt: process.env.GITHUB_RUN_ATTEMPT ?? null,
    workflowSha: process.env.GITHUB_WORKFLOW_SHA ?? null,
    ref: process.env.GITHUB_REF ?? null,
    event: process.env.GITHUB_EVENT_NAME ?? null,
    jobStatus,
  },
  observedOutcome: jobStatus === "success" ? "passed" : jobStatus,
  acceptedEvidence: {
    accepted,
    authority: "same-job immutable qualification receipt plus successful job conclusion",
    receiptPath: receiptExists ? process.env.UI_CONTROL_ACCEPTANCE_RECEIPT ?? "ui-control-evidence/receipt.json" : null,
    receiptSha256: receiptBytes ? sha256(receiptBytes) : null,
  },
  checks,
  claims: {
    sourceOrMergeStageAccepted: accepted,
    realBackendQualified: false,
    productionDeploymentApproved: false,
    independentSecurityReviewPassed: false,
    manualScreenReaderAcceptancePassed: false,
    releaseAuthorized: false,
  },
};
await mkdir(dirname(output), { recursive: true });
await writeFile(output, `${JSON.stringify(observation, null, 2)}\n`);
console.log(output);
