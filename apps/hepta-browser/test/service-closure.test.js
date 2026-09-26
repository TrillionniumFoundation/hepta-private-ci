import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  appendFile,
  copyFile,
  mkdir,
  mkdtemp,
  readFile,
  rm,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import test from "node:test";

const APP_ROOT = resolve(new URL("..", import.meta.url).pathname);
const BOOTSTRAP = join(APP_ROOT, "src", "verified-service-bootstrap.js");
const MANIFEST = join(APP_ROOT, "service-manifest.json");

function run(path) {
  return spawnSync(process.execPath, [path], {
    encoding: "utf8",
    env: { PATH: process.env.PATH ?? "" },
    timeout: 15_000,
  });
}

test("verified bootstrap authenticates every module before importing production service", () => {
  const result = run(BOOTSTRAP);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /HEPTA_BROWSER_PROFILE_ROOT is required/);
  assert.doesNotMatch(result.stderr, /service manifest digest mismatch|module digest mismatch/);
});

test("verified bootstrap rejects one-byte dependency drift before module execution", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "hepta-browser-service-closure-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const manifest = JSON.parse(await readFile(MANIFEST, "utf8"));
  await mkdir(join(root, "src"), { recursive: true, mode: 0o700 });
  await copyFile(MANIFEST, join(root, "service-manifest.json"));
  await copyFile(BOOTSTRAP, join(root, "src", "verified-service-bootstrap.js"));
  for (const relativePath of Object.keys(manifest.files)) {
    const source = join(APP_ROOT, relativePath);
    const destination = join(root, relativePath);
    await mkdir(dirname(destination), { recursive: true, mode: 0o700 });
    await copyFile(source, destination);
  }
  await appendFile(join(root, "src", "action.js"), "\n// injected drift\n");
  const result = run(join(root, "src", "verified-service-bootstrap.js"));
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Browser service module digest mismatch: src\/action\.js/);
  assert.doesNotMatch(result.stderr, /HEPTA_BROWSER_PROFILE_ROOT is required/);
});
