import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, beforeEach, test } from "node:test";
import { fileURLToPath } from "node:url";
import { verifyVendor } from "../verify-mcp-conformance-vendor.mjs";

const source = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "mcp-vendor-proof-"));
let root;
beforeEach(() => {
  root = fs.mkdtempSync(path.join(temporary, "case-"));
  fs.mkdirSync(path.join(root, "third_party"));
  for (const name of [
    "package.json",
    "scripts/mcp_conformance/sdk132_negative_oauth_reuse.ts",
    "third_party/mcp-conformance-patches/sdk-1.32-reference-clients.patch",
    "third_party/mcp-conformance-patches/local-network-boundary.patch",
  ]) {
    fs.mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
    fs.copyFileSync(path.join(source, name), path.join(root, name));
  }
  for (const name of [
    "mcp-conformance-upstream.json",
    "mcp-conformance-upstream-package-lock.json",
  ]) {
    fs.copyFileSync(
      path.join(source, "third_party", name),
      path.join(root, "third_party", name),
    );
  }
  fs.cpSync(
    path.join(source, "third_party/mcp-conformance"),
    path.join(root, "third_party/mcp-conformance"),
    {
      recursive: true,
      filter: (file) =>
        !["node_modules", "dist", "results"].includes(path.basename(file)),
    },
  );
});
after(() => fs.rmSync(temporary, { recursive: true, force: true }));

test("accepts the original rule set with the exact reviewed SDK reference-client and local network patches", () => {
  assert.deepEqual(verifyVendor(root), {
    commit: "c37eec888e1c6ff140af79987a40008548b7cc5f",
    files: 293,
  });
});

test("rejects any change to the original oracle code", () => {
  fs.appendFileSync(
    path.join(root, "third_party/mcp-conformance/src/index.ts"),
    "\n// changed\n",
  );
  assert.throws(() => verifyVendor(root), /file changed: src\/index.ts/);
});

test("rejects a rewritten provenance manifest", () => {
  const file = path.join(root, "third_party/mcp-conformance-upstream.json");
  const manifest = JSON.parse(fs.readFileSync(file));
  manifest.upstream_files["src/index.ts"].sha256 = "0".repeat(64);
  fs.writeFileSync(file, JSON.stringify(manifest));
  assert.throws(() => verifyVendor(root), /upstream manifest changed/);
});

test("rejects a dependency lock regression", () => {
  const file = path.join(root, "third_party/mcp-conformance/package-lock.json");
  const lock = JSON.parse(fs.readFileSync(file));
  lock.packages["node_modules/proxy-addr"].version = "2.0.7";
  fs.writeFileSync(file, JSON.stringify(lock));
  assert.throws(() => verifyVendor(root), /file changed: package-lock.json/);
});

test("rejects added source even in a directory named node_modules", () => {
  const directory = path.join(
    root,
    "third_party/mcp-conformance/src/node_modules",
  );
  fs.mkdirSync(directory);
  fs.writeFileSync(path.join(directory, "extra.js"), "export default 1;\n");
  assert.throws(() => verifyVendor(root), /upstream file set changed/);
});

test("rejects missing oracle files", () => {
  fs.unlinkSync(path.join(root, "third_party/mcp-conformance/src/index.ts"));
  assert.throws(() => verifyVendor(root), /upstream file set changed/);
});

test("rejects a changed raw negative producer", () => {
  fs.appendFileSync(
    path.join(root, "scripts/mcp_conformance/sdk132_negative_oauth_reuse.ts"),
    "\n// changed\n",
  );
  assert.throws(
    () => verifyVendor(root),
    /local compatibility artifact changed/,
  );
});

test("rejects applying the local client patch to an unreviewed SDK version", () => {
  const file = path.join(root, "package.json");
  const pkg = JSON.parse(fs.readFileSync(file));
  pkg.resolutions["@modelcontextprotocol/sdk"] = "1.29.0";
  fs.writeFileSync(file, JSON.stringify(pkg));
  assert.throws(
    () => verifyVendor(root),
    /requires the reviewed SDK 1.32.0 pin/,
  );
});
