import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

const MANIFEST_SHA256 =
  "12f2449790c63fb674c27c2fd58cbbfc87dea10be963aa8908aa9f351e7e49e4";
const PATCHED_LOCK_SHA256 =
  "0bcde31f680dacec39d1f1105712ce7d252bde888da58b8db85dc48b116c2ffe";
// Local compatibility changes are separate from the immutable upstream manifest.
const LOCAL_SOURCE_PATCHES = {
  "examples/clients/typescript/auth-test-reuse-credentials.ts":
    "23ad442ced4e7eb8e70781f6732f0f58982632a5feea2b17e8baeddb31a3977a",
  "src/scenarios/client/auth/index.test.ts":
    "0c34a0fa7e22719b1d627cbde35feddd820b17e9320605a44511839a3765762d",
  "src/scenarios/client/auth/helpers/createServer.ts":
    "bc38f0b9cfae877990150b91c855ef659c5f6a29e5b0538922dd30c02df59e60",
  "src/scenarios/client/auth/helpers/createAuthServer.ts":
    "e2559915395c37b6b8ca5aeea13bdb3e5cb9a1a0445d48f6ec5bb20198454b55",
  "src/scenarios/client/auth/helpers/serverLifecycle.ts":
    "8d7df6f2bb9fa8e6f7d7ecf3d8075952f583a2192b68b20d982378962241683c",
  "src/scenarios/client/auth/enterprise-managed-authorization.ts":
    "82e450d8eacb723a9fdab8f73c8f267c717898738b124809c59e515ce6465700",
  "examples/servers/typescript/everything-server.ts":
    "e9c87f467ae1488808063b43d764a5756809ab0d30197246d74cc5642e01ffa2",
  "package.json":
    "27e01fccaac383f7e695cc38419b36b2b4d5cfafeca5efe9afd3c86648a9be16",
};
const LOCAL_ARTIFACT_HASHES = {
  "third_party/mcp-conformance-patches/sdk-1.32-reference-clients.patch":
    "da28bd53e955eb7a5efb3826a8395c12603bc41e04e773176f3e3ac7ff30ebc3",
  "scripts/mcp_conformance/sdk132_negative_oauth_reuse.ts":
    "af46e13d70e2dd3eb0008df1d8e343925ee7438860b34489728fc2cbab162ad3",
  "third_party/mcp-conformance-patches/local-network-boundary.patch":
    "6a00eb547b040b8737482eb41007777c08a854a6c02f0fc356f734d3bace4a3d",
};
const LOCAL_ADDED_FILES = {
  "src/fixture-network.ts": {
    bytes: 3079,
    mode: "100644",
    sha256: "3a3ca2fd1ac10a0da57afb153ca02c2a4773ddbdd240676f03a6482baf6a1d38",
  },
  "src/fixture-network.test.ts": {
    bytes: 5687,
    mode: "100644",
    sha256: "25dc708ba11e4473592f933538e12c63de6e1203ccb9b81e70546462bc28262c",
  },
};
const UPSTREAM_COMMIT = "c37eec888e1c6ff140af79987a40008548b7cc5f";
const UPSTREAM_TREE = "22eb98b99b522401dd1911dc2c2a55bee3547b50";
const REPO_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

function requireCondition(condition, message) {
  if (!condition) throw new Error(`MCP conformance provenance: ${message}`);
}

function readFile(file) {
  const stat = fs.lstatSync(file);
  requireCondition(stat.isFile(), `expected a regular file: ${file}`);
  return fs.readFileSync(file);
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

export function verifyVendor(repoRoot = REPO_ROOT) {
  const vendor = path.join(repoRoot, "third_party/mcp-conformance");
  const manifestBytes = readFile(
    path.join(repoRoot, "third_party/mcp-conformance-upstream.json"),
  );
  requireCondition(
    sha256(manifestBytes) === MANIFEST_SHA256,
    "upstream manifest changed; review the pinned source before updating the verifier",
  );
  const manifest = JSON.parse(manifestBytes);
  requireCondition(
    manifest.commit === UPSTREAM_COMMIT && manifest.tree === UPSTREAM_TREE,
    "unexpected upstream revision",
  );
  const sdkVersion = JSON.parse(readFile(path.join(repoRoot, "package.json")))
    .resolutions?.["@modelcontextprotocol/sdk"];
  requireCondition(
    sdkVersion === "1.32.0",
    "local reference-client patch requires the reviewed SDK 1.32.0 pin",
  );
  for (const [name, expectedHash] of Object.entries(LOCAL_ARTIFACT_HASHES)) {
    requireCondition(
      sha256(readFile(path.join(repoRoot, name))) === expectedHash,
      `local compatibility artifact changed: ${name}`,
    );
  }
  const expected = { ...manifest.upstream_files, ...LOCAL_ADDED_FILES };
  const packageDirs = new Set(
    Object.keys(expected)
      .filter((name) => path.posix.basename(name) === "package.json")
      .map((name) => path.posix.dirname(name)),
  );
  const actual = [];
  function walk(relative = "") {
    for (const entry of fs.readdirSync(path.join(vendor, relative), {
      withFileTypes: true,
    })) {
      const name = relative ? `${relative}/${entry.name}` : entry.name;
      requireCondition(!entry.isSymbolicLink(), `unexpected symlink: ${name}`);
      if (entry.isDirectory()) {
        // Only outputs at original package roots are excluded. A new source
        // directory named src/node_modules or src/dist is still rejected.
        const packageOutput =
          packageDirs.has(relative || ".") &&
          ["node_modules", "dist"].includes(entry.name);
        const rootOutput =
          !relative &&
          ["results", ".sdk-under-test", ".sync-schema-tmp"].includes(
            entry.name,
          );
        if (!packageOutput && !rootOutput) walk(name);
      } else {
        requireCondition(entry.isFile(), `unexpected file type: ${name}`);
        actual.push(name);
      }
    }
  }
  walk();
  requireCondition(
    isDeepStrictEqual(actual.sort(), Object.keys(expected).sort()),
    "upstream file set changed",
  );
  for (const [name, entry] of Object.entries(expected)) {
    const file = path.join(vendor, name);
    const bytes = readFile(file);
    const expectedHash =
      name === "package-lock.json"
        ? PATCHED_LOCK_SHA256
        : (LOCAL_SOURCE_PATCHES[name] ?? entry.sha256);
    requireCondition(sha256(bytes) === expectedHash, `file changed: ${name}`);
    if (process.platform !== "win32") {
      requireCondition(
        Boolean(fs.statSync(file).mode & 0o111) === (entry.mode === "100755"),
        `executable mode changed: ${name}`,
      );
    }
  }
  const originalBytes = readFile(
    path.join(
      repoRoot,
      "third_party/mcp-conformance-upstream-package-lock.json",
    ),
  );
  requireCondition(
    sha256(originalBytes) === expected["package-lock.json"].sha256,
    "original upstream lock changed",
  );
  const original = JSON.parse(originalBytes);
  const patched = JSON.parse(readFile(path.join(vendor, "package-lock.json")));
  const oldProxy = original.packages["node_modules/proxy-addr"];
  requireCondition(
    isDeepStrictEqual(patched.packages["node_modules/proxy-addr"], {
      ...oldProxy,
      version: "2.0.8",
      resolved: "https://registry.npmjs.org/proxy-addr/-/proxy-addr-2.0.8.tgz",
      integrity:
        "sha512-5nnx0yGyVUcY6t9RnWcARWtwT9F1D8O9rt08htPvnd49W1IgZtmLkhu9WfMzQj1cFxjHIO6connUNVW5k7AVyQ==",
      funding: {
        type: "opencollective",
        url: "https://opencollective.com/express",
      },
    }),
    "proxy-addr patch differs from the reviewed npm resolution",
  );
  requireCondition(
    patched.packages[""].license === "SEE LICENSE IN LICENSE",
    "package license must defer to the complete upstream transition notice",
  );
  patched.packages[""].license = original.packages[""].license;
  patched.packages["node_modules/proxy-addr"] = oldProxy;
  requireCondition(
    isDeepStrictEqual(patched, original),
    "unreviewed changes outside the proxy-addr and root license lock records",
  );
  return { commit: UPSTREAM_COMMIT, files: actual.length };
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href
) {
  try {
    console.log(JSON.stringify(verifyVendor()));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
