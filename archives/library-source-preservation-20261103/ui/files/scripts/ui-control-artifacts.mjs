#!/usr/bin/env node
// The former JavaScript/browser generator is preserved in the exact oracle archive.
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const manifestPath = "qualification/ui-control/UI_CONTROL_MANIFEST.json";
const manifest = JSON.parse(await readFile(resolve(root, manifestPath), "utf8"));
const mode = process.argv[2] ?? "--write";
if (!["--write", "--check"].includes(mode) || manifest.implementationLanguage !== "rust") {
  throw new Error("Rust ui.control manifest and --write/--check are required");
}
const q = value => `\`${value}\``;
const sourceObject = path => {
  const object = manifest.sourceObjects.find(item => item.path === path)?.object;
  if (typeof path !== "string" || !/^[0-9a-f]{40}$/.test(object ?? "")) {
    throw new Error("exact Rust source binding is missing");
  }
  return object;
};
const statusRows = Object.entries(manifest.status)
  .map(([key, value]) => `| ${q(key)} | ${q(value)} |`).join("\n");
const commands = manifest.verification.commands.map(value => `- ${q(value)}`).join("\n");
const guide = await readFile(resolve(root, "apps/hepta-control-ui/RUST_DEVELOPMENT.md"), "utf8");
const technical = `# ui.control Rust technical development guide

> Generated from ${q(manifestPath)} and ${q("apps/hepta-control-ui/RUST_DEVELOPMENT.md")}. Edit those sources, not this projection.

| Dimension | Current state |
|---|---|
${statusRows}

${guide.replace(/^# .*\n/, "")}`;
const operations = manifest.operations.map(operation => {
  if (!Array.isArray(operation.tests) || operation.tests.length === 0 || !operation.symbol) {
    throw new Error("each Rust operation needs an exact entrypoint and tests");
  }
  return {
    designOperation: operation.id,
    mappingClass: "owner_boundary",
    ownerEntrypoint: { role: "owner_entrypoint", path: operation.sourcePath,
      symbol: operation.symbol, buildTarget: operation.buildTarget },
    delegatedCallees: [], tests: operation.tests, sourceSemantics: operation.semantics,
    operation: operation.id, nativeSymbol: operation.symbol,
    sourcePath: operation.sourcePath, sourceBlob: sourceObject(operation.sourcePath), sourcePathExists: true,
  };
});
const map = {
  schema: "hepta.module-implementation-map.v3", schemaVersion: 3,
  sourceBase: manifest.historicalSourceBase,
  sourceIdentityPolicy: "candidate_or_exact_observation_v1", mappingSourceIdentityMode: "exact_blob",
  observedAtHead: manifest.sourceObservation, observedSourcePaths: manifest.sourceRoots,
  sourceObjects: manifest.sourceObjects, laneId: manifest.laneId, module: manifest.module,
  sourceMaturity: "rust_control_client_candidate", declaredRoots: manifest.sourceRoots,
  resolvedRoots: manifest.sourceRoots, statusManifest: manifestPath, currentStatus: manifest.status,
  evidenceSemantics: manifest.evidenceSemantics, verificationStages: manifest.verificationStages,
  receiptSchemas: manifest.receiptSchemas,
  stateOwnerDisposition: "Owns bounded presentation/session and local recovery identities; backend owners retain authority, operation uniqueness and terminal facts.",
  terminalObserverDisposition: "Only authenticated backend observations establish terminal state; acknowledgement, timeout and local storage never do.",
  operations, repositoryControlledGaps: manifest.repositoryControlledGaps,
  externalEvidenceGates: manifest.externalEvidenceGates,
  claimBoundary: {
    nativeSourceMappingComplete: true, repositoryControlledDocumentationGapsClosed: false,
    repositoryControlledMappingGapsClosed: true, repositoryControlledSourceBoundaryGapsClosed: false,
    clientCoreSubstantiallyImplemented: true, repositoryBrowserShellImplemented: false,
    repositoryAuthTransportAdaptersImplemented: true, browserCorrelationIdentifiersRedacted: false,
    dependencyLockCommitted: true, serverIdempotencyContractDefined: true,
    exactHeadQualificationWorkflowPresent: true, exactHeadQualificationDerivedByWorkflow: false,
    productExecutionComplete: false, deploymentQualificationComplete: false,
    independentAcceptanceComplete: false, sourceRootPresent: true,
    productionImplementation: false, productExecutionProved: false,
    independentAcceptance: false, activation: false, release: false,
    implementedOperationMappingComplete: true,
  },
  sourceRootPresent: true, productionImplementation: false,
  productCallerState: manifest.productCallerState, productCallers: manifest.productCallers,
  productCallerBindingPolicy: manifest.productCallerBindingPolicy,
  productCallerBindings: manifest.productCallerBindings,
  mutationClientCallerState: manifest.mutationClientCallerState,
  productionWriterState: "backend_contract_defined_writer_unobserved",
  owner: manifest.owner, deputy: manifest.deputy,
  technicalGuide: "docs/modules/ui.control/TECHNICAL.md", sourceRoot: manifest.sourceRoots,
};
const dossier = `# ui.control Rust execution dossier

> Generated from ${q(manifestPath)}.

The Rust client is a candidate. Native presentation composition does not compose the independent mutation backend.

## Current repository gaps

${manifest.repositoryControlledGaps.map(value => `- ${value}`).join("\n")}

## Verification commands

${commands}

## Qualification boundary

${manifest.evidenceSemantics.overallAcceptance}

No JavaScript or browser receipt qualifies this Rust candidate. Backend admission, private-store portability, host accessibility, independent acceptance and release remain separate requirements.
`;
const outputs = new Map([
  ["docs/modules/ui.control/TECHNICAL.md", `${technical.trimEnd()}\n`],
  ["docs/modules/ui.control/IMPLEMENTATION_MAP.json", `${JSON.stringify(map, null, 2)}\n`],
  ["qualification/module-execution-dossiers/detail/ui.control.md", `${dossier.trimEnd()}\n`],
]);
let changed = false;
for (const [path, expected] of outputs) {
  if (mode === "--write") {
    await writeFile(resolve(root, path), expected);
    console.log(`wrote ${path}`);
  } else if (await readFile(resolve(root, path), "utf8") !== expected) {
    changed = true;
    console.error(`stale generated artifact: ${path}`);
  }
}
if (changed) process.exitCode = 1;
