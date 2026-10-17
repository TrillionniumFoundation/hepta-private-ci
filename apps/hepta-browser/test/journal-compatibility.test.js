import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { browserActionDigest } from "../src/action.js";
import {
  FileBrowserOperationJournal,
  MemoryBrowserOperationJournal,
} from "../src/journal.js";
import { BrowserProfileHost } from "../src/runtime.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const OPTIONS = { timeout: 5_000 };
const RECEIPT_METADATA = {
  kind: "BrowserEffectObservationV1",
  networkAuthority: false,
  filesystemAuthority: false,
  credentialExportAuthority: false,
};
const MUTABLE_FIELDS = new Set([
  "status",
  "outcomeDigest",
  "terminalObserved",
  "observationReason",
]);

function record(overrides = {}) {
  return {
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.1",
    requestDigest: D1,
    semanticDigest: D2,
    processId: "servo.process.1",
    pageGeneration: 1,
    documentDigest: D1,
    action: "navigate",
    destinationOrigin: "https://example.com",
    finalPayloadDigest: D1,
    profileGrantDigest: D1,
    effectGrantDigest: D2,
    authorityEpoch: 7,
    deadlineMs: 9000,
    verifiedUseTokenWitnessDigest: D1,
    status: "indeterminate",
    outcomeDigest: null,
    terminalObserved: false,
    observationReason: "dispatching",
    ...overrides,
  };
}
function terminal(overrides = {}) {
  return record({
    status: "succeeded",
    outcomeDigest: D3,
    terminalObserved: true,
    observationReason: "terminal_observed",
    ...overrides,
  });
}
function line(type, value) {
  const unsigned = {
    schema: "hepta.browser.operation-journal.v1",
    version: 1,
    type,
    record: value,
  };
  return (
    JSON.stringify({
      ...unsigned,
      checksum: createHash("sha256")
        .update(JSON.stringify(unsigned))
        .digest("hex"),
    }) + "\n"
  );
}
async function fixture(t, records) {
  const root = await mkdtemp(join(tmpdir(), "hepta-journal-v1-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "operations.jsonl");
  const bytes = records.map(([type, value]) => line(type, value)).join("");
  await writeFile(path, bytes, { mode: 0o600 });
  return {
    path,
    bytes: Buffer.from(bytes),
    journal: new FileBrowserOperationJournal(path),
  };
}

test(
  "V1 receipt history retains metadata across canonical observations and zero-byte retries",
  OPTIONS,
  async (t) => {
    const legacy = {
      ...record({ observationReason: "reconcile_error" }),
      ...RECEIPT_METADATA,
    };
    const { path, bytes, journal } = await fixture(t, [
      ["dispatch", record()],
      ["observation", legacy],
      ["observation", terminal()],
    ]);
    const expected = { ...terminal(), ...RECEIPT_METADATA };
    assert.deepEqual(
      await journal.getOperation("profile.1", 1, "operation.1"),
      expected,
    );
    await journal.recordDispatch(record());
    await journal.recordObservation(terminal());
    assert.deepEqual(await readFile(path), bytes);
    assert.deepEqual(
      await new FileBrowserOperationJournal(path).listOperations(
        "profile.1",
        1,
      ),
      [expected],
    );
  },
);

test(
  "V1 terminal receipt is preserved when a later canonical duplicate omits its adornment",
  OPTIONS,
  async (t) => {
    const { path, bytes, journal } = await fixture(t, [
      ["dispatch", record()],
      ["observation", { ...terminal(), ...RECEIPT_METADATA }],
      ["observation", terminal()],
    ]);
    assert.deepEqual(
      await journal.getOperation("profile.1", 1, "operation.1"),
      {
        ...terminal(),
        ...RECEIPT_METADATA,
      },
    );
    assert.deepEqual(await readFile(path), bytes);
  },
);

for (const [name, metadata] of [
  ["wrong discriminator", { ...RECEIPT_METADATA, kind: "BrowserDispatchV1" }],
  ["network authority", { ...RECEIPT_METADATA, networkAuthority: true }],
  ["filesystem authority", { ...RECEIPT_METADATA, filesystemAuthority: true }],
  [
    "credential authority",
    { ...RECEIPT_METADATA, credentialExportAuthority: true },
  ],
  ["nonboolean authority", { ...RECEIPT_METADATA, networkAuthority: "false" }],
  ["nested authority", { ...RECEIPT_METADATA, networkAuthority: {} }],
  ...Object.keys(RECEIPT_METADATA).map((missing) => [
    `missing ${missing}`,
    Object.fromEntries(
      Object.entries(RECEIPT_METADATA).filter(([key]) => key !== missing),
    ),
  ]),
]) {
  test(
    `V1 compatibility rejects ${name} despite a valid raw checksum`,
    OPTIONS,
    async (t) => {
      const { path, bytes, journal } = await fixture(t, [
        ["dispatch", record()],
        ["observation", { ...terminal(), ...metadata }],
      ]);
      await assert.rejects(
        journal.listOperations("profile.1", 1),
        /receipt metadata|JSON scalars/,
      );
      assert.deepEqual(await readFile(path), bytes);
    },
  );
}

test(
  "V1 compatibility cannot turn a receipt-bearing dispatch into an admitted intent",
  OPTIONS,
  async (t) => {
    const { journal } = await fixture(t, [
      ["dispatch", { ...record(), ...RECEIPT_METADATA }],
    ]);
    await assert.rejects(
      journal.listOperations("profile.1", 1),
      /receipt metadata/,
    );
  },
);

test(
  "raw checksum rejection precedes receipt compatibility",
  OPTIONS,
  async (t) => {
    const { path, journal } = await fixture(t, [
      ["dispatch", record()],
      ["observation", { ...terminal(), ...RECEIPT_METADATA }],
    ]);
    const raw = await readFile(path, "utf8");
    const corrupted = raw.replace(
      '"networkAuthority":false',
      '"networkAuthority":true',
    );
    assert.notEqual(corrupted, raw);
    await writeFile(path, corrupted, { mode: 0o600 });
    await assert.rejects(
      journal.listOperations("profile.1", 1),
      /checksum mismatch/,
    );
  },
);

for (const [field, value] of Object.entries(record()).filter(
  ([key]) => !MUTABLE_FIELDS.has(key),
)) {
  test(
    `V1 receipt compatibility retains immutable ${field} value and presence`,
    OPTIONS,
    async (t) => {
      const replacement =
        typeof value === "number"
          ? value + 1
          : value === D1 || value === D2
            ? D3
            : `${value}.changed`;
      for (const changed of [
        { ...terminal(), [field]: replacement },
        Object.fromEntries(
          Object.entries(terminal()).filter(([key]) => key !== field),
        ),
      ]) {
        const { path, bytes, journal } = await fixture(t, [
          ["dispatch", record()],
          ["observation", { ...changed, ...RECEIPT_METADATA }],
        ]);
        await assert.rejects(journal.listOperations("profile.1", 1));
        assert.deepEqual(await readFile(path), bytes);
      }
    },
  );
}

for (const [name, changed] of [
  ["rollback", record()],
  ["status", terminal({ status: "failed" })],
  ["outcome", terminal({ outcomeDigest: D2 })],
  ["reason", terminal({ observationReason: "changed_reason" })],
  ["unknown field", terminal({ unrelated: false })],
]) {
  test(
    `V1 receipt compatibility preserves terminal ${name} rejection`,
    OPTIONS,
    async (t) => {
      const { path, bytes, journal } = await fixture(t, [
        ["dispatch", record()],
        ["observation", { ...terminal(), ...RECEIPT_METADATA }],
        ["observation", changed],
      ]);
      await assert.rejects(
        journal.listOperations("profile.1", 1),
        /terminal|immutable semantics/,
      );
      assert.deepEqual(await readFile(path), bytes);
    },
  );
}

test(
  "live writes do not gain the legacy checksum-admitted exception",
  OPTIONS,
  async (t) => {
    const { journal: file } = await fixture(t, []);
    for (const journal of [new MemoryBrowserOperationJournal(), file]) {
      await assert.rejects(
        journal.recordDispatch({ ...record(), ...RECEIPT_METADATA }),
        /checksummed V1 history/,
      );
      await journal.recordDispatch(record());
      await assert.rejects(
        journal.recordObservation({ ...terminal(), ...RECEIPT_METADATA }),
        /checksummed V1 history/,
      );
      await journal.recordObservation(terminal());
      assert.deepEqual(
        await journal.getOperation("profile.1", 1, "operation.1"),
        terminal(),
      );
    }
  },
);

test(
  "actual host recovery keeps future writes canonical and historical receipts authority-free",
  OPTIONS,
  async (t) => {
    const action = {
      kind: "navigate",
      url: "https://example.com/path",
      policyDigest: D1,
      expectedRevision: 7,
    };
    const payload = browserActionDigest(action);
    const profile = {
      profileId: "profile.1",
      principalId: "principal.1",
      generation: 1,
      manifestDigest: D1,
      grantDigest: D2,
      expiresAtMs: 10000,
      allowedOrigins: ["https://example.com"],
      effectGrants: [
        {
          grantDigest: D3,
          action: "navigate",
          destinationOrigin: "https://example.com",
          finalPayloadDigest: payload,
          authorityEpoch: 7,
          expiresAtMs: 9500,
        },
      ],
    };
    const operation = {
      profileId: "profile.1",
      principalId: "principal.1",
      generation: 1,
      operationId: "operation.1",
      pageGeneration: 1,
      typedAction: action,
      destinationOrigin: "https://example.com",
      finalPayloadDigest: payload,
      effectGrantDigest: D3,
      authorityEpoch: 7,
      deadlineMs: 9000,
    };
    let dispatches = 0;
    let reconciles = 0;
    let authorizations = 0;
    const driver = {
      async start() {
        return { started: true, processId: "servo.process.1" };
      },
      async observe() {
        return {
          pageGeneration: 1,
          documentDigest: D1,
          origin: "https://example.com",
        };
      },
      async dispatch() {
        dispatches += 1;
        return { terminalObserved: false };
      },
      async reconcile() {
        reconciles += 1;
        return {
          terminalObserved: true,
          status: "succeeded",
          outcomeDigest: D3,
        };
      },
      async stop() {
        return { stopped: true };
      },
    };
    const authority = {
      async withVerifiedUse(request, consumer) {
        authorizations += 1;
        return consumer({
          authorized: true,
          witnessDigest: D3,
          authorityEpoch: request.authorityEpoch,
          requestDigest: request.requestDigest,
        });
      },
    };
    const base = new MemoryBrowserOperationJournal();
    const writes = [];
    const journal = {
      async recordDispatch(value) {
        writes.push(["dispatch", value]);
        await base.recordDispatch(value);
      },
      async recordObservation(value) {
        writes.push(["observation", value]);
        await base.recordObservation(value);
      },
      getOperation: (...args) => base.getOperation(...args),
      listOperations: (...args) => base.listOperations(...args),
    };
    const makeHost = (storage, clock) =>
      new BrowserProfileHost({
        driver,
        authority,
        journal: storage,
        clock: () => clock,
        driverCallTimeoutMs: 1000,
      });
    const first = makeHost(journal, 1000);
    await first.openProfile(profile);
    await first.observePage({
      profileId: "profile.1",
      principalId: "principal.1",
      generation: 1,
      observationBudget: 128,
    });
    const unknown = await first.navigateOrAct(operation);
    assert.equal(unknown.terminalObserved, false);
    const dispatch = writes[0][1];
    const historical = { ...dispatch, ...unknown }; // Exact old producer: durable + receipt.
    const { path, journal: oldHistory } = await fixture(t, [
      ["dispatch", dispatch],
      ["observation", historical],
    ]);
    const before = await readFile(path);
    assert.deepEqual(
      await oldHistory.getOperation("profile.1", 1, "operation.1"),
      historical,
    );
    const recovered = await makeHost(
      oldHistory,
      20000,
    ).reconcilePersistedOperation(operation);
    assert.equal(recovered.terminalObserved, true);
    assert.equal(recovered.kind, RECEIPT_METADATA.kind);
    for (const field of [
      "networkAuthority",
      "filesystemAuthority",
      "credentialExportAuthority",
    ]) {
      assert.equal(recovered[field], false);
    }
    const after = await readFile(path);
    assert.deepEqual(after.subarray(0, before.length), before);
    const latest = JSON.parse(
      after.toString("utf8").trimEnd().split("\n").at(-1),
    ).record;
    for (const field of Object.keys(RECEIPT_METADATA))
      assert.equal(Object.hasOwn(latest, field), false);
    assert.deepEqual(latest, {
      ...dispatch,
      status: recovered.status,
      outcomeDigest: recovered.outcomeDigest,
      terminalObserved: recovered.terminalObserved,
      observationReason: recovered.observationReason,
    });
    const replay = await makeHost(
      new FileBrowserOperationJournal(path),
      20000,
    ).reconcilePersistedOperation(operation);
    assert.deepEqual(replay, recovered);
    assert.deepEqual(await readFile(path), after);
    assert.deepEqual(
      { dispatches, reconciles, authorizations },
      { dispatches: 1, reconciles: 1, authorizations: 1 },
    );
  },
);
