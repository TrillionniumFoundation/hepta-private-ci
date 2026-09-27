import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { execFileSync } from "node:child_process";

const output = resolve(process.argv[2] ?? "ui-control-qualification-receipt.json");
const command = (...args) => execFileSync(args[0], args.slice(1), { encoding: "utf8" }).trim();
const buildManifest = await readFile(new URL("../dist/build-manifest.json", import.meta.url), "utf8");
const dependencyLock = await readFile(new URL("../package-lock.json", import.meta.url), "utf8");
const sha256 = value => createHash("sha256").update(value).digest("hex");
const receipt = {
  schema: "hepta.ui-control.qualification-receipt.v1",
  source: {
    sha: command("git", "rev-parse", "HEAD"),
    tree: command("git", "rev-parse", "HEAD^{tree}"),
  },
  runtime: {
    node: process.version,
    npm: command("npm", "--version"),
    platform: process.platform,
    architecture: process.arch,
  },
  checks: {
    dependencyLock: process.env.UI_CONTROL_DEPENDENCY_LOCK ?? "unknown",
    lint: process.env.UI_CONTROL_LINT ?? "unknown",
    unit: process.env.UI_CONTROL_UNIT ?? "unknown",
    contract: process.env.UI_CONTROL_CONTRACT ?? "unknown",
    build: process.env.UI_CONTROL_BUILD ?? "unknown",
    browserE2e: process.env.UI_CONTROL_E2E ?? "unknown",
    axe: process.env.UI_CONTROL_AXE ?? "unknown",
    laneBGuard: process.env.UI_CONTROL_LANE_B_GUARD ?? "unknown",
    documentation: process.env.UI_CONTROL_DOCS ?? "unknown",
  },
  artifacts: {
    dependencyLockSha256: sha256(dependencyLock),
    browserBuildManifestSha256: sha256(buildManifest),
  },
  claims: {
    repositoryBrowserCompositionQualified: process.env.UI_CONTROL_E2E === "passed",
    deployedBackendQualified: false,
    productionIdentityProviderQualified: false,
    productionCspObserved: false,
    independentAcceptanceSigned: false,
    releaseAuthorized: false,
  },
};
await mkdir(dirname(output), { recursive: true });
await writeFile(output, `${JSON.stringify(receipt, null, 2)}\n`);
console.log(output);
