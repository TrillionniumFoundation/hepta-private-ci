import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { verifyProfile } from "../verify-mcp-conformance-local-network-profile.mjs";

const ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const PROFILE_FILE = "scripts/mcp_conformance/vendor-c37-sdk132-localnet-v2.json";
const IDENTITY = JSON.parse(fs.readFileSync(path.join(ROOT, PROFILE_FILE)));
const VENDOR = path.join(ROOT, "third_party/mcp-conformance");

function copiedSourceFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "hepta-profile-tamper-"));
  const manifest = JSON.parse(
    fs.readFileSync(
      path.join(ROOT, "third_party/mcp-conformance-upstream.json"),
    ),
  );
  const names = new Set([
    PROFILE_FILE,
    ...Object.keys(IDENTITY.sourcePins),
    "third_party/mcp-conformance-upstream-package-lock.json",
    ...Object.keys(manifest.upstream_files).map(
      (name) => `third_party/mcp-conformance/${name}`,
    ),
  ]);
  for (const name of names) {
    const source = path.join(ROOT, name);
    const dest = path.join(root, name);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(source, dest);
    fs.chmodSync(dest, fs.statSync(source).mode & 0o777);
  }
  return root;
}

async function rejectedSourceEdit(name, edit, pattern) {
  const root = copiedSourceFixture();
  try {
    const file = path.join(root, name);
    fs.writeFileSync(file, edit(fs.readFileSync(file, "utf8")));
    await assert.rejects(verifyProfile(root), pattern);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

test("the real local-network c37 derivative CLI equals an independent offline original-script rebuild", async () => {
  const result = await verifyProfile(ROOT, path.join(VENDOR, "dist/index.js"));
  assert.deepEqual(result.identity, IDENTITY);
  assert.equal(result.sourceVerified, true);
  assert.equal(result.canonicalRebuildMatched, true);
  assert.equal(result.observedRuntime.pnpm, "10.34.5");
});

test("rejects a changed code-owned profile or claimed upstream revision", async () => {
  await rejectedSourceEdit(
    PROFILE_FILE,
    (s) => s.replace(IDENTITY.gitRef, "0".repeat(40)),
    /descriptor changed/,
  );
  await rejectedSourceEdit(
    "third_party/mcp-conformance-upstream.json",
    (s) => s.replace(IDENTITY.gitRef, "0".repeat(40)),
    /source\/lock changed/,
  );
});

test("rejects vendor source outside the reviewed local patches", async () => {
  await rejectedSourceEdit(
    "third_party/mcp-conformance/src/index.ts",
    (s) => `${s}\n// unreviewed\n`,
    /file changed/,
  );
});

test("rejects altered reviewed local patch artifacts and either dependency lock", async () => {
  for (const name of [
    "third_party/mcp-conformance-patches/sdk-1.32-reference-clients.patch",
    "scripts/mcp_conformance/sdk132_negative_oauth_reuse.ts",
    "third_party/mcp-conformance/package-lock.json",
    "pnpm-lock.yaml",
  ])
    await rejectedSourceEdit(name, (s) => `${s}\n`, /source\/lock changed/);
});

test("rejects an edited verifier before importing or executing it", async () => {
  const root = copiedSourceFixture();
  try {
    const marker = path.join(root, "executed-edited-verifier");
    const verifier = path.join(
      root,
      "scripts/verify-mcp-conformance-vendor.mjs",
    );
    fs.appendFileSync(
      verifier,
      `\nfs.writeFileSync(${JSON.stringify(marker)}, "bad");\n`,
    );
    await assert.rejects(verifyProfile(root), /source\/lock changed/);
    assert.equal(fs.existsSync(marker), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("rejects an executable outside the canonical verified vendor output", async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "hepta-wrong-cli-"));
  try {
    const cli = path.join(tmp, "index.js");
    fs.copyFileSync(path.join(VENDOR, "dist/index.js"), cli);
    await assert.rejects(
      verifyProfile(ROOT, cli),
      /not the canonical verified vendor output/,
    );
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test("rejects actual built CLI byte drift and restores this candidate's owned output", async () => {
  const cli = path.join(VENDOR, "dist/index.js");
  const original = fs.readFileSync(cli);
  try {
    fs.appendFileSync(cli, "\n// tampered output\n");
    await assert.rejects(verifyProfile(ROOT, cli), /built CLI differs/);
  } finally {
    fs.writeFileSync(cli, original);
  }
});

test("rejects a real SDK peer-link substitution even after Node resolver caching", async () => {
  const link = path.join(VENDOR, "node_modules/@modelcontextprotocol/sdk");
  const backup = `${link}.profile-test-${process.pid}`;
  // Prime normal resolver state; a cached require.resolve must not conceal
  // a subsequent change of the actual generated dependency link.
  await verifyProfile(ROOT);
  fs.renameSync(link, backup);
  try {
    const wrong = path.join(
      ROOT,
      path.dirname(IDENTITY.peerGraph[1].sdkPackage),
    );
    fs.symlinkSync(wrong, link, "junction");
    await assert.rejects(verifyProfile(ROOT), /SDK|peer|Zod/);
  } finally {
    fs.unlinkSync(link);
    fs.renameSync(backup, link);
  }
});
