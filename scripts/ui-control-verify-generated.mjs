#!/usr/bin/env node
import { createHash } from "node:crypto";
import { spawnSync, execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const evidenceDir = resolve(root, process.env.UI_CONTROL_EVIDENCE_DIR ?? "ui-control-evidence");
const generatedPaths = [
  "docs/modules/ui.control/TECHNICAL.md",
  "docs/modules/ui.control/IMPLEMENTATION_MAP.json",
  "qualification/module-execution-dossiers/detail/ui.control.md",
  "qualification/ui-control/STATUS.md",
  "qualification/ui-control/GATE_MAP.json",
];
const generators = [
  ["scripts/ui-control-artifacts.mjs", "--write"],
  ["scripts/ui-control-status.mjs", "--write"],
];
const sha256 = value => createHash("sha256").update(value).digest("hex");
const git = (...args) => execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();

await mkdir(evidenceDir, { recursive: true });
const originals = new Map();
for (const relativePath of generatedPaths) {
  originals.set(relativePath, await readFile(resolve(root, relativePath)));
}

const generatorRuns = [];
let generationFailure = null;
let changedFiles = [];
let patch = "";
try {
  for (const [script, mode] of generators) {
    const result = spawnSync(process.execPath, [resolve(root, script), mode], {
      cwd: root,
      encoding: "utf8",
    });
    const run = {
      command: [process.execPath, script, mode],
      exitCode: result.status,
      signal: result.signal,
      stdout: result.stdout ?? "",
      stderr: result.stderr ?? "",
    };
    generatorRuns.push(run);
    if (result.status !== 0) {
      generationFailure = run;
      break;
    }
  }

  if (!generationFailure) {
    for (const relativePath of generatedPaths) {
      const current = originals.get(relativePath);
      const generated = await readFile(resolve(root, relativePath));
      if (!current.equals(generated)) {
        changedFiles.push({
          path: relativePath,
          trackedSha256: sha256(current),
          generatedSha256: sha256(generated),
        });
      }
    }
    if (changedFiles.length > 0) {
      const result = spawnSync(
        "git",
        ["diff", "--no-ext-diff", "--text", "--unified=80", "--", ...generatedPaths],
        { cwd: root, encoding: "utf8" },
      );
      patch = result.stdout ?? "";
    }
  }
} finally {
  for (const [relativePath, content] of originals) {
    await writeFile(resolve(root, relativePath), content);
  }
}

const subject = {
  sha: git("rev-parse", "HEAD"),
  tree: git("rev-parse", "HEAD^{tree}"),
};
const common = {
  schema: "hepta.ui-control.generated-truth-observation.v1",
  observedAt: new Date().toISOString(),
  subject,
  generatedPaths,
  generatorRuns,
};

if (generationFailure) {
  const failure = {
    ...common,
    outcome: "generator-failed",
    failedCommand: generationFailure.command,
    exitCode: generationFailure.exitCode,
    signal: generationFailure.signal,
    stdout: generationFailure.stdout,
    stderr: generationFailure.stderr,
  };
  await writeFile(
    resolve(evidenceDir, "generated-truth-failure.json"),
    `${JSON.stringify(failure, null, 2)}\n`,
  );
  console.error(JSON.stringify(failure, null, 2));
  process.exitCode = 1;
} else if (changedFiles.length > 0) {
  const failure = {
    ...common,
    outcome: "stale",
    changedFiles,
    diffArtifact: "generated-truth-diff.patch",
  };
  await writeFile(resolve(evidenceDir, "generated-truth-diff.patch"), patch);
  await writeFile(
    resolve(evidenceDir, "generated-truth-failure.json"),
    `${JSON.stringify(failure, null, 2)}\n`,
  );
  console.error(`generated ui.control truth is stale:\n${patch || JSON.stringify(changedFiles, null, 2)}`);
  process.exitCode = 1;
} else {
  const observation = { ...common, outcome: "passed", changedFiles: [] };
  await writeFile(
    resolve(evidenceDir, "generated-truth-observation.json"),
    `${JSON.stringify(observation, null, 2)}\n`,
  );
  console.log(`ui.control generated truth matches ${subject.sha} / ${subject.tree}`);
}
