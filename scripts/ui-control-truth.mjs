#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const evidenceDir = resolve(root, process.env.UI_CONTROL_EVIDENCE_DIR ?? "ui-control-evidence");
const readJson = async path => JSON.parse(await readFile(resolve(root, path), "utf8"));
const git = (...args) => execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();
const issues = [];
const requireTruth = (condition, code, detail) => {
  if (!condition) issues.push({ code, detail });
};
const repositoryPath = path => {
  const absolute = resolve(root, path);
  const fromRoot = relative(root, absolute);
  requireTruth(
    !isAbsolute(fromRoot) && fromRoot !== ".." && !fromRoot.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`),
    "UI_CONTROL_PATH_ESCAPE",
    path,
  );
  return absolute;
};
const exists = async path => {
  try {
    await stat(repositoryPath(path));
    return true;
  } catch {
    return false;
  }
};

const manifest = await readJson("qualification/ui-control/UI_CONTROL_MANIFEST.json");
const implementationMap = await readJson("docs/modules/ui.control/IMPLEMENTATION_MAP.json");
const gateMap = await readJson("qualification/ui-control/GATE_MAP.json");
const status = await readFile(resolve(root, "qualification/ui-control/STATUS.md"), "utf8");
const dossier = await readFile(
  resolve(root, "qualification/module-execution-dossiers/detail/ui.control.md"),
  "utf8",
);

requireTruth(manifest.schema === "hepta.ui-control.manifest.v1", "UI_CONTROL_MANIFEST_SCHEMA", manifest.schema);
requireTruth(manifest.module === "ui.control", "UI_CONTROL_MODULE_ID", manifest.module);
requireTruth(Array.isArray(manifest.sourceRoots) && manifest.sourceRoots.length > 0, "UI_CONTROL_SOURCE_ROOTS", manifest.sourceRoots);
for (const sourceRoot of manifest.sourceRoots ?? []) {
  requireTruth(await exists(sourceRoot), "UI_CONTROL_SOURCE_ROOT_MISSING", sourceRoot);
}

requireTruth(
  implementationMap.statusManifest === "qualification/ui-control/UI_CONTROL_MANIFEST.json",
  "UI_CONTROL_IMPLEMENTATION_MAP_SOURCE",
  implementationMap.statusManifest,
);
requireTruth(
  JSON.stringify(implementationMap.currentStatus) === JSON.stringify(manifest.status),
  "UI_CONTROL_IMPLEMENTATION_MAP_STATUS_DRIFT",
  "implementation map status does not match manifest",
);
requireTruth(
  gateMap.sourceManifest === "qualification/ui-control/UI_CONTROL_MANIFEST.json",
  "UI_CONTROL_GATE_MAP_SOURCE",
  gateMap.sourceManifest,
);
requireTruth(
  JSON.stringify(gateMap.stages) === JSON.stringify(manifest.verificationStages),
  "UI_CONTROL_GATE_MAP_STAGE_DRIFT",
  "gate map stages do not match manifest",
);
requireTruth(status.includes("Generated from `qualification/ui-control/UI_CONTROL_MANIFEST.json`"), "UI_CONTROL_STATUS_PROVENANCE", "missing generated provenance");
requireTruth(dossier.includes("Generated from `qualification/ui-control/UI_CONTROL_MANIFEST.json`"), "UI_CONTROL_DOSSIER_PROVENANCE", "missing generated provenance");

const expectedStages = [
  "designDefined",
  "codePresent",
  "sourceTestsPassed",
  "browserTestsPassed",
  "mergeTreePassed",
  "realBackendPassed",
  "productionDeploymentApproved",
];
requireTruth(
  JSON.stringify(Object.keys(manifest.verificationStages ?? {})) === JSON.stringify(expectedStages),
  "UI_CONTROL_STAGE_ORDER",
  Object.keys(manifest.verificationStages ?? {}),
);
requireTruth(
  manifest.verificationStages.realBackendPassed?.repositoryState === "external_evidence_absent",
  "UI_CONTROL_REAL_BACKEND_FALSE_CLAIM",
  manifest.verificationStages.realBackendPassed,
);
requireTruth(
  manifest.verificationStages.productionDeploymentApproved?.repositoryState === "external_authority_absent",
  "UI_CONTROL_PRODUCTION_FALSE_CLAIM",
  manifest.verificationStages.productionDeploymentApproved,
);

for (const operation of implementationMap.operations ?? []) {
  const sourcePath = operation.ownerEntrypoint?.path ?? operation.sourcePath;
  requireTruth(typeof sourcePath === "string", "UI_CONTROL_OPERATION_SOURCE_MISSING", operation.designOperation);
  if (typeof sourcePath === "string") {
    requireTruth(await exists(sourcePath), "UI_CONTROL_OPERATION_SOURCE_NOT_FOUND", sourcePath);
    requireTruth(
      manifest.sourceRoots.some(rootPath => sourcePath === rootPath || sourcePath.startsWith(`${rootPath}/`)),
      "UI_CONTROL_OPERATION_OUTSIDE_DECLARED_ROOT",
      sourcePath,
    );
  }
  for (const test of operation.tests ?? []) {
    requireTruth(await exists(test.path), "UI_CONTROL_OPERATION_TEST_NOT_FOUND", test.path);
  }
}

try {
  execFileSync("python3", ["scripts/ui-control-source-map.py"], {
    cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], maxBuffer: 64 * 1024,
  });
} catch (error) {
  requireTruth(false, "UI_CONTROL_SOURCE_IDENTITY",
    String(error.stderr ?? error.message).trim().split("\n").at(-1));
}

await mkdir(evidenceDir, { recursive: true });
const receipt = {
  schema: "hepta.ui-control.module-truth-observation.v1",
  observedAt: new Date().toISOString(),
  subject: { sha: git("rev-parse", "HEAD"), tree: git("rev-parse", "HEAD^{tree}") },
  sourceManifest: "qualification/ui-control/UI_CONTROL_MANIFEST.json",
  outcome: issues.length === 0 ? "passed" : "failed",
  issues,
  claimBoundary: {
    repositoryModuleTruthOnly: true,
    repositoryWideLaneBTruth: "separate-diagnostic",
    realBackendQualified: false,
    productionDeploymentApproved: false,
  },
};
await writeFile(
  resolve(evidenceDir, "module-truth-observation.json"),
  `${JSON.stringify(receipt, null, 2)}\n`,
);
if (issues.length > 0) {
  console.error(JSON.stringify(receipt, null, 2));
  process.exitCode = 1;
} else {
  console.log(`ui.control module truth passed for ${receipt.subject.sha} / ${receipt.subject.tree}`);
}
