#!/usr/bin/env node
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const manifestPath = resolve(root, "qualification/ui-control/UI_CONTROL_MANIFEST.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
const mode = process.argv[2] ?? "--write";
if (!["--write", "--check"].includes(mode)) {
  throw new Error("usage: node scripts/ui-control-status.mjs [--write|--check]");
}

const rows = Object.entries(manifest.verificationStages)
  .map(([stage, value]) => [
    `\`${stage}\``,
    `\`${value.repositoryState}\``,
    value.observationAuthority,
    value.acceptanceAuthority,
  ].join(" | "))
  .map(row => `| ${row} |`)
  .join("\n");
const markdown = `# ui.control verification status model

> Generated from \`qualification/ui-control/UI_CONTROL_MANIFEST.json\`. This file defines stage meanings; it does not cache mutable CI or deployment outcomes.

## Evidence semantics

- **Observed outcome:** ${manifest.evidenceSemantics.observedOutcome}
- **Accepted evidence:** ${manifest.evidenceSemantics.acceptedEvidence}
- **Overall acceptance:** ${manifest.evidenceSemantics.overallAcceptance}

| Stage | Repository state | Observation authority | Acceptance authority |
|---|---|---|---|
${rows}

A later stage never upgrades an earlier stage by implication, and a later failure never rewrites an earlier accepted stage to false. In particular, code presence is not a test pass, a source-head observation is not an accepted receipt, a source-head receipt is not a merge-tree receipt, and repository qualification is not real-backend or production-deployment approval.
`;
const gateMap = {
  schema: "hepta.ui-control.gate-map.v2",
  module: manifest.module,
  sourceManifest: "qualification/ui-control/UI_CONTROL_MANIFEST.json",
  evidenceSemantics: manifest.evidenceSemantics,
  stages: manifest.verificationStages,
  immutableOrdering: Object.keys(manifest.verificationStages),
  outcomeAuthority: {
    repositoryReceipts: "hepta.ui-control.qualification-receipt.v2",
    realBackend: "hepta.ui-control.real-backend-receipt.v2",
    deploymentSecurity: "hepta.ui-control.deployment-security-receipt.v2",
    independentAcceptance: "hepta.ui-control.independent-acceptance-receipt.v2",
    independentSecurity: "hepta.ui-control.independent-security-review-receipt.v1",
    operationalExercise: "hepta.ui-control.operational-exercise-receipt.v1",
    productionApproval: "hepta.ui-control.production-approval-receipt.v1",
    externalEvidenceBundle: "hepta.ui-control.external-evidence-bundle.v1",
  },
};
const outputs = new Map([
  ["qualification/ui-control/STATUS.md", markdown],
  ["qualification/ui-control/GATE_MAP.json", `${JSON.stringify(gateMap, null, 2)}\n`],
]);
let stale = false;
for (const [relativePath, expected] of outputs) {
  const path = resolve(root, relativePath);
  if (mode === "--write") {
    await writeFile(path, expected);
    console.log(`wrote ${relativePath}`);
  } else {
    const actual = await readFile(path, "utf8");
    if (actual !== expected) {
      stale = true;
      console.error(`stale generated artifact: ${relativePath}`);
    }
  }
}
if (stale) process.exitCode = 1;
