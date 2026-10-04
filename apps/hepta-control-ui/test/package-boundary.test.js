import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

test("product package exposes only the built Rust Makepad artifact", async () => {
  const packageJson=JSON.parse(await readFile(new URL("../package.json",import.meta.url),"utf8"));
  assert.equal(packageJson.type,"module");
  assert.equal(packageJson.main,undefined);
  assert.equal(packageJson.types,undefined);
  assert.deepEqual(packageJson.exports,{});
  assert.equal(packageJson.files.includes("src/"),false);
  assert.equal(packageJson.files.includes("web/"),false);
  assert.equal(packageJson.files.includes("dist/"),true);
  assert.equal(packageJson.engines.node,">=22.0.0");
});

test("browser-test dependencies are exactly and integrally locked", async () => {
  const packageJson = JSON.parse(
    await readFile(new URL("../package.json", import.meta.url), "utf8"),
  );
  const packageLock = JSON.parse(
    await readFile(new URL("../package-lock.json", import.meta.url), "utf8"),
  );
  assert.equal(packageLock.lockfileVersion, 3);
  assert.equal(packageLock.name, packageJson.name);
  assert.equal(packageLock.version, packageJson.version);
  assert.deepEqual(packageLock.packages[""].devDependencies, packageJson.devDependencies);
  for (const [name, version] of Object.entries(packageJson.devDependencies)) {
    assert.match(version, /^\d+\.\d+\.\d+$/);
    assert.equal(packageLock.packages[`node_modules/${name}`].version, version);
    assert.match(packageLock.packages[`node_modules/${name}`].integrity, /^sha512-/);
  }
});

test("unexported src deep imports are rejected", async () => {
  await assert.rejects(
    import("@hepta/control-ui/src/control.js"),
    error => error?.code === "ERR_PACKAGE_PATH_NOT_EXPORTED",
  );
});

test("browser sources avoid unsafe HTML injection sinks", async () => {
  const source = await readFile(new URL("../src/browser-app.js", import.meta.url), "utf8");
  for (const sink of ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"])
    assert.equal(source.includes(sink), false, `browser source contains ${sink}`);
});

test("browser shell exposes separate session, identity, pending, and terminal evidence regions", async () => {
  const html = await readFile(new URL("../web/index.html", import.meta.url), "utf8");
  for (const id of ["session-state", "identity-state", "pending-list", "completed-list"]) {
    assert.equal(html.includes(`id=\"${id}\"`), true, `browser shell is missing ${id}`);
  }
});
