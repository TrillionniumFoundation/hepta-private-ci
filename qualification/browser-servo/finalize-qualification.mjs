#!/usr/bin/env node

import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync, writeFileSync } from "node:fs";
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
const output = resolve(args.get("output") ?? "runtime-qualification.json");
const markdown = resolve(args.get("markdown") ?? "runtime-qualification.md");
const requireQualified = (args.get("require-qualified") ?? "false") === "true";
const requireSignatures = (args.get("require-signatures") ?? "true") === "true";

function load(name) {
  const path = resolve(args.get(name) ?? "");
  if (!existsSync(path) || !lstatSync(path).isFile()) {
    throw new Error(`missing qualification input ${name}: ${path}`);
  }
  return { path, value: JSON.parse(readFileSync(path, "utf8")) };
}
function bool(value) { return value === true; }
function all(object, names) { return names.every((name) => bool(object?.[name])); }
function digest(path) { return createHash("sha256").update(readFileSync(path)).digest("hex"); }
function signature(path) {
  if (!path) return null;
  const resolved = resolve(path);
  if (!existsSync(resolved) || !lstatSync(resolved).isFile() || lstatSync(resolved).size === 0) return null;
  return { path: resolved, sha256: digest(resolved) };
}

const candidate = load("candidate-manifest");
const protocol = load("protocol");
const worker = load("real-worker");
const browser = load("real-browser");
const soak = load("soak");
const fault = load("fault");
const wss = load("wss");
const sourceResult = args.get("source-result") ?? "unknown";
const workspaceResult = args.get("workspace-result") ?? "unknown";
const stagedResult = args.get("staged-result") ?? "unknown";
const sourceReceiptsPresent = (args.get("source-receipts-present") ?? "false") === "true";
const expectedSha = args.get("expected-sha") ?? "";

const agentdAttestation = signature(args.get("agentd-attestation"));
const workerAttestation = signature(args.get("worker-attestation"));
const signaturesPresent = Boolean(agentdAttestation && workerAttestation);

const sourceBoundaryChecks = {
  sourceJobsSucceeded: sourceResult === "success",
  workspaceJobsSucceeded: workspaceResult === "success",
  stagedWorkspaceSucceeded: stagedResult === "success",
  sourceReceiptsPresent,
  exactCandidateSource: candidate.value.source?.sha === expectedSha
    && candidate.value.source?.exactHead === true
    && candidate.value.source?.dirtyTracked === false,
  candidateIsNotArchivedProbe: candidate.value.archivedProbe === false,
};
const sourceBoundaryQualified = Object.values(sourceBoundaryChecks).every(Boolean);

const workerChecks = {
  pagePrototypeHooksIsolated: worker.value.pagePrototypeHooksIsolated,
  failureSerializationCannotForgeSuccess: worker.value.failureSerializationCannotForgeSuccess,
  privateHandlesNotLeakedThroughArrayHooks: worker.value.privateHandlesNotLeakedThroughArrayHooks,
};
const browserChecks = {
  openNavigateObserveTypeClickClose: browser.value.openNavigateObserveTypeClickClose,
  exactOriginEgressObserved: browser.value.exactOriginEgressObserved,
  crossOriginSubresourceDenied: browser.value.crossOriginSubresourceDenied,
  redirectEscapeDenied: browser.value.redirectEscapeDenied,
  profileExpiryContainsBackgroundNetwork: browser.value.profileExpiryContainsBackgroundNetwork,
  profileCloseRevocationContainsBackgroundNetwork: browser.value.profileCloseRevocationContainsBackgroundNetwork,
  revocationRaceBlockedUntilDispatchBoundary: browser.value.revocationRaceBlockedUntilDispatchBoundary,
  persistedCrashReconciliation: browser.value.persistedCrashReconciliation,
  authenticatedPersistedCrashReconciliation: browser.value.authenticatedPersistedCrashReconciliation,
  crossProfileCookieIsolation: browser.value.crossProfileCookieIsolation,
  crossProfileStorageIsolation: browser.value.crossProfileStorageIsolation,
  crossProfileCacheIsolation: browser.value.crossProfileCacheIsolation,
  noExternallyReachableWorkerListener: browser.value.noExternallyReachableWorkerListener,
};
const soakChecks = {
  boundedFdGrowth: soak.value.boundedFdGrowth,
  boundedRssGrowth: soak.value.boundedRssGrowth,
  cyclesAtLeast32: Number.isSafeInteger(soak.value.cycles) && soak.value.cycles >= 32,
};
const protocolChecks = {
  matrixSchema: protocol.value.schema === "hepta.browser.servo-protocol-compatibility.v1",
  protocolsFailClosed: Array.isArray(protocol.value.protocols)
    && protocol.value.protocols.length >= 3
    && protocol.value.protocols.every((entry) =>
      bool(entry.exactVersionAccepted)
      && bool(entry.futureVersionRejected)
      && bool(entry.unknownCriticalFieldRejected)),
};
const productExecutionChecks = {
  candidateManifestV2: candidate.value.schema === "hepta.browser.servo-candidate-manifest.v2",
  candidateDigestsPresent: /^[0-9a-f]{64}$/.test(candidate.value.artifacts?.agentd?.sha256 ?? "")
    && /^[0-9a-f]{64}$/.test(candidate.value.artifacts?.servoWorker?.sha256 ?? ""),
  protocolCompatibility: Object.values(protocolChecks).every(Boolean),
  realWorkerSuccess: Object.values(workerChecks).every(Boolean),
  realBrowserSuccessAndIsolation: Object.values(browserChecks).every(Boolean),
  boundedSoak: Object.values(soakChecks).every(Boolean),
  restartTimeoutLateResultRecovery: fault.value.fullyPassed === true,
  wssAcceptedExecutedCommittedObserved: wss.value.executed === true
    && wss.value.exactSequenceObserved === true
    && JSON.stringify(wss.value.phases) === JSON.stringify(["accepted", "executed", "committed", "observed"]),
  signedAgentdAndWorker: requireSignatures ? signaturesPresent : true,
};
const productExecutionQualified = sourceBoundaryQualified
  && Object.values(productExecutionChecks).every(Boolean);

const blockers = [
  ...Object.entries(sourceBoundaryChecks).filter(([, passed]) => !passed).map(([id]) => `source:${id}`),
  ...Object.entries(productExecutionChecks).filter(([, passed]) => !passed).map(([id]) => `product:${id}`),
];
const receipt = {
  schema: "hepta.browser.servo-runtime-qualification.v2",
  module: "browser.servo",
  sourceSha: expectedSha,
  sourceBoundaryQualified,
  productExecutionQualified,
  qualificationStatus: productExecutionQualified ? "qualified" : "not_qualified",
  selfAuthorizing: false,
  sourceBoundaryChecks,
  productExecutionChecks,
  detail: { workerChecks, browserChecks, soakChecks, protocolChecks },
  candidate: {
    manifestDigest: candidate.value.manifestDigest,
    agentdSha256: candidate.value.artifacts?.agentd?.sha256,
    servoWorkerSha256: candidate.value.artifacts?.servoWorker?.sha256,
    archivedProbe: candidate.value.archivedProbe,
  },
  attestations: { agentd: agentdAttestation, worker: workerAttestation, required: requireSignatures },
  evidenceDigests: Object.fromEntries([
    ["candidateManifest", candidate.path],
    ["protocolCompatibility", protocol.path],
    ["realWorker", worker.path],
    ["realBrowser", browser.path],
    ["soak", soak.path],
    ["fault", fault.path],
    ["wss", wss.path],
  ].map(([name, path]) => [name, digest(path)])),
  blockers,
  run: {
    repository: process.env.GITHUB_REPOSITORY ?? null,
    workflow: process.env.GITHUB_WORKFLOW ?? null,
    runId: process.env.GITHUB_RUN_ID ?? null,
    runAttempt: process.env.GITHUB_RUN_ATTEMPT ?? null,
    event: process.env.GITHUB_EVENT_NAME ?? null,
    ref: process.env.GITHUB_REF ?? null,
  },
};
receipt.receiptDigest = createHash("sha256").update(JSON.stringify(receipt)).digest("hex");
writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o600 });

const lines = [
  "<!-- browser-servo-runtime-qualification:start -->",
  "## browser.servo runtime qualification",
  "",
  `- Exact source: \`${expectedSha}\``,
  `- Source boundary qualified: **${sourceBoundaryQualified}**`,
  `- Product execution qualified: **${productExecutionQualified}**`,
  `- Agentd candidate: \`${receipt.candidate.agentdSha256 ?? "missing"}\``,
  `- Servo worker candidate: \`${receipt.candidate.servoWorkerSha256 ?? "missing"}\``,
  `- Qualification run: \`${receipt.run.runId ?? "local"}\` attempt \`${receipt.run.runAttempt ?? "n/a"}\``,
  `- Receipt digest: \`${receipt.receiptDigest}\``,
  "",
  blockers.length === 0 ? "No open runtime qualification blockers." : `Open blockers: ${blockers.map((item) => `\`${item}\``).join(", ")}`,
  "",
  "This runtime receipt is evidence-bound and non-self-authorizing. Promotion and release remain separate operator decisions.",
  "<!-- browser-servo-runtime-qualification:end -->",
  "",
];
writeFileSync(markdown, lines.join("\n"), { mode: 0o600 });
process.stdout.write(`${JSON.stringify(receipt)}\n`);
if (requireQualified && !productExecutionQualified) process.exitCode = 1;
