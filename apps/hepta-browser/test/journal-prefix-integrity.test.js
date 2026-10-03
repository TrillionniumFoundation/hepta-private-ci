import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { FileBrowserOperationJournal } from "../src/journal.js";

const intent = {
  profileId: "profile.prefix",
  generation: 1,
  operationId: "operation.prefix",
  requestDigest: "1".repeat(64),
  semanticDigest: "2".repeat(64),
  status: "indeterminate",
  terminalObserved: false,
  outcomeDigest: null,
};

for (const fault of ["utf8", "json", "checksum", "truncated"]) {
  test(`changed verified prefix retains recovery fence before ${fault} replay rejection`, async (t) => {
    const root = await mkdtemp(join(tmpdir(), "hepta-browser-prefix-"));
    t.after(() => rm(root, { recursive: true, force: true }));
    const path = join(root, "operations.jsonl");
    const journal = new FileBrowserOperationJournal(path);
    await journal.recordDispatch(intent);
    const original = await readFile(path);
    let corrupt = Buffer.from(original);
    if (fault === "utf8") corrupt[0] = 0xff;
    if (fault === "json") corrupt[0] = 0x5b;
    if (fault === "checksum") {
      corrupt = Buffer.from(
        original.toString("utf8").replace("1".repeat(64), "3".repeat(64)),
      );
    }
    if (fault === "truncated")
      corrupt = original.subarray(0, original.length - 1);
    await writeFile(path, corrupt);
    await assert.rejects(
      journal.getOperation(intent.profileId, 1, intent.operationId),
    );
    assert.deepEqual(await readFile(path), corrupt);

    // Restoring fixture bytes is not an owner-recovery action or authority.
    await writeFile(path, original);
    await assert.rejects(
      journal.getOperation(intent.profileId, 1, intent.operationId),
      /owner recovery/,
    );
    await assert.rejects(
      journal.recordDispatch({ ...intent, operationId: "operation.next" }),
      /owner recovery/,
    );
    await assert.rejects(
      new FileBrowserOperationJournal(path).listOperations(intent.profileId, 1),
      /owner recovery/,
    );
    assert.deepEqual(await readFile(path), original);
    assert.ok((await stat(`${path}.writer-lock`)).isDirectory());
  });
}
