import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

const MANIFEST_SHA256 =
  "12f2449790c63fb674c27c2fd58cbbfc87dea10be963aa8908aa9f351e7e49e4";
const PATCHED_LOCK_SHA256 =
  "fb9c17db4a77fa3a487ff83f1e767cdeea91b1feddc3250424e53f34c2889b6c";
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
  const expected = manifest.upstream_files;
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
      name === "package-lock.json" ? PATCHED_LOCK_SHA256 : entry.sha256;
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
  patched.packages["node_modules/proxy-addr"] = oldProxy;
  requireCondition(
    isDeepStrictEqual(patched, original),
    "unreviewed changes outside the proxy-addr lock record",
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
