import assert from "node:assert/strict";
import test from "node:test";
import { createControlConsole } from "../src/browser-app.js";
import { ScopedRecoveryStore } from "../src/recovery-store.js";
import { fixture, operation, terminal, deferred } from "./browser-fixture.js";

const recordCount = storage => [...storage.values.keys()]
  .filter(key => key.startsWith("hepta.ui-control.scoped-recovery.v2:")).length;

for (const failure of ["lock", "removal"]) {
  test(`browser shows asynchronous ${failure} failure and retains the original record`, async t => {
    const f = fixture(); const store = await ScopedRecoveryStore.create(f.options);
    await store.prepare(operation()); f.view.completed = [terminal()];
    const originalRemove = f.options.storage.removeItem;
    if (failure === "lock") f.options.locks.reject = true;
    else f.options.storage.removeItem = () => {};
    const app = createControlConsole(f.config); t.after(() => app.destroy());
    await app.start();
    const error = f.document.getElementById("error-status");
    assert.equal(error.hidden, false); assert.match(error.textContent, /UI_CONTROL_STORAGE/);
    assert.equal(recordCount(f.options.storage), 1); assert.equal(f.counters.mutations, 0);
    f.options.locks.reject = false; f.options.storage.removeItem = originalRemove;
    await f.document.getElementById("refresh-view").fire();
    assert.equal(recordCount(f.options.storage), 0); assert.equal(error.hidden, true);
    const requests = f.options.locks.requests;
    await f.document.getElementById("refresh-view").fire();
    assert.equal(f.options.locks.requests, requests);
  });
}

test("unchanged large lists allocate no nodes; updated cells reuse exact rows", async t => {
  const f = fixture();
  f.view.snapshot.modules = Array.from({ length: 2048 }, (_, i) => ({
    id: `module-${i}`, status: "running", revision: 1, semanticDigest: "a".repeat(64),
  }));
  f.view.pending = Array.from({ length: 1024 }, (_, i) => ({ ...operation(`pending-${i}`), state: "indeterminate" }));
  f.view.completed = Array.from({ length: 1024 }, (_, i) => terminal(`done-${i}`));
  const app = createControlConsole(f.config); t.after(() => app.destroy());
  app.render();
  const table = f.document.getElementById("modules-body");
  const pending = f.document.getElementById("pending-list");
  const completed = f.document.getElementById("completed-list");
  const rows = [...table.children]; const count = f.document.created;
  const replacements = [table.replacements, pending.replacements, completed.replacements];
  const focused = pending.children[500].children[2]; focused.focus();
  for (let i = 0; i < 100; i += 1) app.render();
  assert.equal(f.document.created, count);
  assert.deepEqual([table.replacements, pending.replacements, completed.replacements], replacements);
  assert.equal(f.document.activeElement, focused);
  const writes = rows.map(row => row.children.reduce((n, cell) => n + cell.writes, 0));
  f.view.snapshot.modules[100].status = "stopped"; app.render();
  assert.equal(table.children[100], rows[100]);
  assert.equal(rows[100].children[1].textContent, "stopped");
  assert.equal(rows[100].children.reduce((n, cell) => n + cell.writes, 0), writes[100] + 1);
  assert.equal(f.document.created, count);
});

test("reused presentation cannot retain permissions or a stale confirmation", async t => {
  const f = fixture(); const app = createControlConsole(f.config); t.after(() => app.destroy());
  await app.start(); f.document.getElementById("operation-reason").value = "Maintenance";
  const row = f.document.getElementById("modules-body").children[0];
  const stop = f.document.getElementById("request-stop");
  assert.equal(stop.disabled, false); await stop.fire();
  f.view.permissionRevision += 1; f.view.permissions = []; app.render();
  assert.equal(stop.disabled, true);
  await f.document.getElementById("confirm-submit").fire();
  assert.equal(f.counters.mutations, 0);
  assert.equal(f.document.getElementById("modules-body").children[0], row);
  assert.match(f.document.getElementById("error-status").textContent, /STALE_REVISION/);
});

test("pending button reuse suppresses duplicate lookup and moves focus on terminal removal", async t => {
  const f = fixture(); const gate = deferred(); let lookups = 0;
  f.view.pending = [{ ...operation(), state: "indeterminate" }];
  f.client.recoverOperation = async () => {
    lookups += 1; await gate.promise;
    f.view.pending = []; f.view.completed = [terminal()]; return terminal();
  };
  const app = createControlConsole(f.config); t.after(() => app.destroy());
  app.render(); const button = f.document.getElementById("pending-list").children[0].children[2];
  button.focus(); const work = button.fire(); app.render(); await button.fire();
  assert.equal(lookups, 1); assert.equal(button.disabled, true);
  gate.resolve(); await work;
  assert.equal(f.document.activeElement, f.document.getElementById("live-status"));
  assert.equal(f.counters.mutations, 0);
});

test("destroy aborts queued cleanup and suppresses late error announcements", async () => {
  const f = fixture(); const store = await ScopedRecoveryStore.create(f.options);
  await store.prepare(operation()); f.view.completed = [terminal()];
  const gate = deferred();
  f.options.locks.request = async (name, options, callback) => {
    gate.resolve();
    await new Promise((resolve, reject) => {
      if (options.signal.aborted) reject(options.signal.reason);
      else options.signal.addEventListener("abort", () => reject(options.signal.reason), { once: true });
    });
    return callback();
  };
  const app = createControlConsole(f.config); const starting = app.start();
  const rejected = assert.rejects(starting, { code: "UI_CONTROL_ABORTED" });
  await gate.promise; const before = f.document.getElementById("error-status").textContent;
  await app.destroy(); await rejected;
  assert.equal(f.document.getElementById("error-status").textContent, before);
  assert.equal(recordCount(f.options.storage), 1); assert.equal(f.counters.close, 1);
});
