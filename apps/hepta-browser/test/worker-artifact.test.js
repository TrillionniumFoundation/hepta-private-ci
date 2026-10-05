import assert from "node:assert/strict";
import test from "node:test";
import { appendFile, mkdtemp, open, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { readBoundedWorkerArtifact } from "../src/worker-artifact.js";

test("the artifact read limit survives growth after its first real file read", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "hepta-worker-artifact-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "worker.bin");
  await writeFile(path, Buffer.alloc(4, 1));
  const handle = await open(path, "r");
  assert.equal((await handle.stat()).size, 4);
  const originalRead = handle.read.bind(handle);
  let totalRead = 0;
  handle.read = async (...args) => {
    const result = await originalRead(...args);
    totalRead += result.bytesRead;
    if (totalRead === 4) await appendFile(path, Buffer.alloc(64, 2));
    return result;
  };
  try {
    await assert.rejects(
      readBoundedWorkerArtifact(handle, 8),
      /exceeds byte limit during read/,
    );
    assert.equal(totalRead, 9);
  } finally {
    await handle.close();
  }
});

test("a selected artifact exactly at the bound preserves every byte", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "hepta-worker-artifact-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "worker.bin");
  const bytes = Buffer.from([0, 1, 2, 3, 4, 5, 6, 255]);
  await writeFile(path, bytes);
  const handle = await open(path, "r");
  try {
    assert.deepEqual(
      await readBoundedWorkerArtifact(handle, bytes.length),
      bytes,
    );
  } finally {
    await handle.close();
  }
});
