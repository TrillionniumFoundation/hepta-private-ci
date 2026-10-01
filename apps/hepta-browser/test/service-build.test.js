import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildService } from "../scripts/build-service.mjs";

async function fixture(t, entry, module) {
  const root = await mkdtemp(join(tmpdir(), "browser-service-build-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const sourceRoot = join(root, "src");
  await mkdir(sourceRoot);
  await writeFile(join(sourceRoot, "agentd-service-main.js"), entry);
  if (module !== undefined)
    await writeFile(join(sourceRoot, "owner.js"), module);
  return { root, sourceRoot, outputPath: join(root, "service.mjs") };
}

test("service bundle and receipt reproduce independently without source paths", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "browser-service-repro-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const source = fileURLToPath(new URL("../src", import.meta.url));
  const receipts = [];
  const outputs = [];
  for (const name of ["first", "second"]) {
    const sourceRoot = join(root, name, "src");
    await cp(source, sourceRoot, { recursive: true });
    const outputPath = join(root, name, "artifact", "service.mjs");
    receipts.push(await buildService({ sourceRoot, outputPath }));
    outputs.push(await readFile(outputPath));
  }
  assert.deepEqual(outputs[0], outputs[1]);
  assert.deepEqual(receipts[0], receipts[1]);
  assert.equal(
    receipts[0].bundleSha256,
    createHash("sha256").update(outputs[0]).digest("hex"),
  );
  assert.equal(
    receipts[0].inputs.some(
      (input) => input.path === "src/agentd-service-main.js",
    ),
    true,
  );
  assert.equal(outputs[0].includes(Buffer.from(root)), false);
});

test("service bundle binds a changed transitive module", async (t) => {
  const f = await fixture(
    t,
    'import { value } from "./owner.js"; console.log(value);',
    'export const value = "first";',
  );
  const first = await buildService(f);
  await writeFile(
    join(f.sourceRoot, "owner.js"),
    'export const value = "second";',
  );
  const second = await buildService({
    ...f,
    outputPath: join(f.root, "second.mjs"),
  });
  assert.notEqual(first.bundleSha256, second.bundleSha256);
  assert.notEqual(
    first.inputs.find((i) => i.path.endsWith("owner.js")).sha256,
    second.inputs.find((i) => i.path.endsWith("owner.js")).sha256,
  );
});

test("service build rejects computed module loads and unreviewed builtins", async (t) => {
  for (const entry of [
    "await import(process.env.MODULE);",
    'const load = require; load("./owner.js");',
    'import { createRequire } from "node:module"; createRequire(import.meta.url)("./owner.js");',
    'import "node:net";',
    'const load = process.getBuiltinModule("node:module")[process.env.LOADER](import.meta.url); load(process.env.MODULE);',
    'process["getBuiltinModule"]("node:module")[process.env.LOADER](import.meta.url)(process.env.MODULE);',
  ]) {
    const f = await fixture(t, entry);
    await assert.rejects(buildService(f));
    await assert.rejects(readFile(f.outputPath), { code: "ENOENT" });
  }
});

test("service build rejects source escaping the reviewed directory", async (t) => {
  const f = await fixture(t, 'import "../outside.js";');
  await writeFile(join(f.root, "outside.js"), 'console.log("outside");');
  await assert.rejects(buildService(f), /escapes/);
  await assert.rejects(readFile(f.outputPath), { code: "ENOENT" });
});
