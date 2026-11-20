import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

export const PROFILE = "vendor-c37-sdk132-localnet-v2";
export const DESCRIPTOR_SHA256 = "81c9d77c66f68c5c12cc8392e1793c1e358a80334d3bff6dfd398b066d98aaa6";
const REPO_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const relative = (root, file) =>
  path.relative(root, file).split(path.sep).join("/");
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
function requireCondition(ok, message) {
  if (!ok) throw new Error(`MCP execution profile: ${message}`);
}
function readRegular(file) {
  requireCondition(
    fs.lstatSync(file).isFile(),
    `expected regular file: ${file}`,
  );
  return fs.readFileSync(file);
}
function readPackageRoot(entry, name) {
  let directory = path.dirname(entry);
  for (;;) {
    const file = path.join(directory, "package.json");
    if (fs.existsSync(file)) {
      const pkg = JSON.parse(readRegular(file));
      if (pkg.name === name) return { file, pkg };
    }
    const parent = path.dirname(directory);
    requireCondition(parent !== directory, `cannot resolve package ${name}`);
    directory = parent;
  }
}
function peerGraph(root, identity) {
  return identity.peerGraph.map(({ scope }) => {
    const require = createRequire(path.join(root, scope, "package.json"));
    const physicalSdk = fs.realpathSync(
      path.join(root, scope, "node_modules/@modelcontextprotocol/sdk"),
    );
    const sdkEntry = require.resolve(
      "@modelcontextprotocol/sdk/client/index.js",
    );
    const sdk = readPackageRoot(sdkEntry, "@modelcontextprotocol/sdk");
    requireCondition(
      fs.realpathSync(sdk.file) === path.join(physicalSdk, "package.json"),
      "resolved SDK link drifted",
    );
    const sdkRequire = createRequire(sdk.file);
    const zod = readPackageRoot(sdkRequire.resolve("zod"), "zod");
    const physicalZod = fs.realpathSync(path.resolve(physicalSdk, "../../zod"));
    requireCondition(
      fs.realpathSync(zod.file) === path.join(physicalZod, "package.json"),
      "resolved Zod peer link drifted",
    );
    return {
      scope,
      sdkVersion: sdk.pkg.version,
      sdkPackage: relative(root, sdk.file),
      sdkEntry: relative(root, sdkEntry),
      zodVersion: zod.pkg.version,
      zodPackage: relative(root, zod.file),
    };
  });
}
function distFiles(directory) {
  const result = {};
  function walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name);
      requireCondition(
        !entry.isSymbolicLink(),
        `symlink in built CLI: ${file}`,
      );
      if (entry.isDirectory()) walk(file);
      else result[relative(directory, file)] = sha(readRegular(file));
    }
  }
  walk(directory);
  return result;
}
function packageManager(identity, args, cwd, env) {
  // Use the Corepack shipped beside this Node runtime and the complete
  // packageManager integrity pin. A PATH pnpm or npm_execpath may be a different
  // version; neither is sufficient proof of the original build tool.
  const nodeBin = path.dirname(process.execPath);
  const candidates = [
    path.join(nodeBin, "corepack"),
    path.join(nodeBin, "node_modules/corepack/dist/corepack.js"),
  ];
  const entry = candidates.find((file) => fs.existsSync(file));
  requireCondition(
    entry,
    "Node runtime has no adjacent Corepack; initialize the exact pinned tool in CI",
  );
  const corepack = fs.realpathSync(entry);
  requireCondition(
    corepack.endsWith(".js"),
    "Corepack entry is not the Node distribution JavaScript entry",
  );
  const result = spawnSync(
    process.execPath,
    [corepack, identity.packageManager, ...args],
    {
      cwd,
      env,
      encoding: "utf8",
      maxBuffer: 8 * 1024 * 1024,
    },
  );
  requireCondition(
    !result.error && result.status === 0,
    `pinned package manager failed: ${result.error?.message ?? result.stderr ?? result.status}`,
  );
  return result.stdout.trim();
}

export async function verifyProfile(root = REPO_ROOT, selectedCli) {
  const descriptorFile = path.join(
    root,
    "scripts/mcp_conformance",
    `${PROFILE}.json`,
  );
  const descriptorBytes = readRegular(descriptorFile);
  requireCondition(
    sha(descriptorBytes) === DESCRIPTOR_SHA256,
    "code-owned descriptor changed",
  );
  const identity = JSON.parse(descriptorBytes);
  requireCondition(
    Number(process.versions.node.split(".")[0]) === identity.nodeMajor,
    "this profile requires the original SDK CI Node 22 runtime",
  );
  function verifyPins() {
    for (const [name, expected] of Object.entries(identity.sourcePins)) {
      requireCondition(
        sha(readRegular(path.join(root, name))) === expected,
        `source/lock changed: ${name}`,
      );
    }
  }
  verifyPins();
  // Hash the existing verifier before importing it, so an edited verifier is
  // rejected before its module can execute.
  const { verifyVendor } = await import(
    pathToFileURL(path.join(root, "scripts/verify-mcp-conformance-vendor.mjs"))
  );
  const verified = verifyVendor(root);
  requireCondition(
    verified.commit === identity.gitRef && verified.files === 293,
    "unexpected vendor identity",
  );
  requireCondition(
    isDeepStrictEqual(peerGraph(root, identity), identity.peerGraph),
    "resolved SDK/Zod peer graph changed",
  );
  const vendor = path.join(root, "third_party/mcp-conformance");
  const canonicalCli = path.join(vendor, "dist/index.js");
  requireCondition(
    fs.realpathSync(selectedCli ?? canonicalCli) ===
      fs.realpathSync(canonicalCli),
    "selected CLI is not the canonical verified vendor output",
  );
  const selectedDist = distFiles(path.join(vendor, "dist"));
  requireCondition(
    isDeepStrictEqual(selectedDist, identity.dist),
    "built CLI differs from the code-owned output",
  );
  const manifest = JSON.parse(
    readRegular(path.join(root, "third_party/mcp-conformance-upstream.json")),
  );
  const temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "hepta-conformance-rebuild-"),
  );
  const env = {
    ...process.env,
    CI: "true",
    COREPACK_ENABLE_NETWORK: "0",
    COREPACK_DEFAULT_TO_LATEST: "0",
  };
  delete env.LEFTHOOK;
  let managerVersion;
  try {
    const copy = path.join(temporary, "third_party/mcp-conformance");
    fs.mkdirSync(copy, { recursive: true });
    // Carry the exact packageManager pin into the private build tree. Without
    // it a Corepack shim may select a moving default tool version.
    fs.copyFileSync(
      path.join(root, "package.json"),
      path.join(temporary, "package.json"),
    );
    for (const name of [
      ...Object.keys(manifest.upstream_files),
      "src/fixture-network.ts",
      "src/fixture-network.test.ts",
    ]) {
      const source = path.join(vendor, name);
      const destination = path.join(copy, name);
      fs.mkdirSync(path.dirname(destination), { recursive: true });
      fs.copyFileSync(source, destination);
      fs.chmodSync(destination, fs.statSync(source).mode & 0o777);
    }
    fs.symlinkSync(
      path.join(root, "node_modules"),
      path.join(temporary, "node_modules"),
      "junction",
    );
    fs.symlinkSync(
      path.join(vendor, "node_modules"),
      path.join(copy, "node_modules"),
      "junction",
    );
    managerVersion = packageManager(identity, ["--version"], copy, env);
    requireCondition(
      managerVersion === "10.34.5",
      "package manager is not pnpm 10.34.5",
    );
    requireCondition(
      JSON.parse(readRegular(path.join(copy, "package.json"))).scripts.build ===
        identity.buildScript,
      "upstream build command changed",
    );
    packageManager(identity, ["run", "build"], copy, env);
    requireCondition(
      isDeepStrictEqual(distFiles(path.join(copy, "dist")), selectedDist),
      "selected CLI does not equal an independent rebuild",
    );
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
  verifyPins();
  verifyVendor(root);
  requireCondition(
    isDeepStrictEqual(peerGraph(root, identity), identity.peerGraph),
    "resolved SDK/Zod peer graph changed during verification",
  );
  requireCondition(
    isDeepStrictEqual(distFiles(path.join(vendor, "dist")), selectedDist),
    "selected CLI changed during verification",
  );
  return {
    identity,
    descriptorSha256: DESCRIPTOR_SHA256,
    observedRuntime: { node: process.version, pnpm: managerVersion },
    selectedCli: fs.realpathSync(canonicalCli),
    canonicalRebuildMatched: true,
    sourceVerified: true,
  };
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href
) {
  try {
    console.log(
      JSON.stringify(await verifyProfile(REPO_ROOT, process.argv[2])),
    );
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
