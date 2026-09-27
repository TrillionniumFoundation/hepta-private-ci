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
  .map(([stage, value]) => `| \`${stage}\` | \`${value.repositoryState}\` | ${value.passAuthority} |`)
  .join("\n");
const markdown = `# ui.control verification status model

> Generated from \`qualification/ui-control/UI_CONTROL_MANIFEST.json\`. This file defines stage meanings; it does not cache mutable CI or deployment outcomes.

| Stage | Repository state | Pass authority |
|---|---|---|
${rows}

A later stage never upgrades an earlier stage by implication. In particular, code presence is not a test pass, a source-head test pass is not a merge-tree pass, and repository qualification is not real-backend or production-deployment approval.
`;
const gateMap = {
  schema: "hepta.ui-control.gate-map.v1",
  module: manifest.module,
  sourceManifest: "qualification/ui-control/UI_CONTROL_MANIFEST.json",
  stages: manifest.verificationStages,
  immutableOrdering: Object.keys(manifest.verificationStages),
  outcomeAuthority: {
    repositoryReceipts: "hepta.ui-control.qualification-receipt.v2",
    realBackend: "hepta.ui-control.real-backend-receipt.v1",
    deploymentSecurity: "hepta.ui-control.deployment-security-receipt.v1",
    productionApproval: "external deployment and release authority",
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