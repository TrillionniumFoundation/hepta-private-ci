from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


host = "apps/hepta-browser/src/runtime-host.js"
replace_once(host, """  #clock;
  #driverCallTimeoutMs;
""", """  #clock;
  #setTimer;
  #clearTimer;
  #driverCallTimeoutMs;
""")
replace_once(host, """    clock = () => Date.now(),
    driverCallTimeoutMs = DEFAULT_DRIVER_CALL_TIMEOUT_MS,
  }) {
""", """    clock = () => Date.now(),
    setTimer = (callback, delayMs) => {
      const handle = setTimeout(callback, delayMs);
      handle.unref?.();
      return handle;
    },
    clearTimer = (handle) => clearTimeout(handle),
    driverCallTimeoutMs = DEFAULT_DRIVER_CALL_TIMEOUT_MS,
  }) {
""")
replace_once(host, """    if (typeof clock !== "function") throw new TypeError("clock must be a function");
    positiveInteger(driverCallTimeoutMs, "driverCallTimeoutMs");
""", """    if (typeof clock !== "function") throw new TypeError("clock must be a function");
    if (typeof setTimer !== "function" || typeof clearTimer !== "function") {
      throw new TypeError("profile lease scheduler must provide setTimer and clearTimer");
    }
    positiveInteger(driverCallTimeoutMs, "driverCallTimeoutMs");
""")
replace_once(host, """    this.#clock = clock;
    this.#driverCallTimeoutMs = driverCallTimeoutMs;
""", """    this.#clock = clock;
    this.#setTimer = setTimer;
    this.#clearTimer = clearTimer;
    this.#driverCallTimeoutMs = driverCallTimeoutMs;
""")
replace_once(host, """          operations: new Map(),
        };
        this.#profiles.set(profileId, state);
""", """          operations: new Map(),
          fenced: false,
          stopped: false,
          stopReason: null,
          stopError: null,
          leaseTimer: null,
        };
        this.#profiles.set(profileId, state);
        this.#scheduleLease(state);
""")
replace_once(host, """      const state = this.#profile(input, true);
      const { operationId, requestSemantics, requestDigest } = admitNewOperation(
        state,
        input,
        this.#clock(),
      );
      let prior = state.operations.get(operationId);
      if (!prior) {
        const durable = await this.#journal.getOperation(
          state.profileId,
          state.generation,
          operationId,
        );
        if (durable) prior = this.#entryFromDurable(durable, requestSemantics);
      }
      if (prior) {
        if (prior.requestDigest !== requestDigest) {
          throw new TypeError("operation identity was reused with changed semantics");
        }
        if (!state.operations.has(operationId) && !prior.receipt.terminalObserved) {
          state.operations.set(operationId, prior);
        }
        return prior.receipt;
      }
      if (this.#activeOperationCount(state) >= MAX_OUTSTANDING_OPERATIONS) {
""", """      const state = this.#profile(input, false);
      const operationId = stableId(input.operationId, "operationId");
      let prior = state.operations.get(operationId);
      if (!prior) {
        const durable = await this.#journal.getOperation(
          state.profileId,
          state.generation,
          operationId,
        );
        if (durable) {
          prior = this.#entryFromDurable(
            durable,
            this.#requestSemanticsFromDurableInput(state, input, durable),
          );
        }
      }
      if (prior) {
        if (prior.requestDigest !== reconciliationRequestDigest(state, input, prior.semantics)) {
          throw new TypeError("operation identity was reused with changed semantics");
        }
        if (!state.operations.has(operationId) && !prior.receipt.terminalObserved) {
          state.operations.set(operationId, prior);
        }
        return prior.receipt;
      }
      this.#assertNewEffectAllowed(state);
      const { requestSemantics, requestDigest } = admitNewOperation(
        state,
        input,
        this.#clock(),
      );
      if (this.#activeOperationCount(state) >= MAX_OUTSTANDING_OPERATIONS) {
""")
replace_once(host, """      await this.#journal.recordObservation({ ...durable, ...receipt });
      return receipt;
""", """      await this.#journal.recordObservation({
        ...durable,
        status: receipt.status,
        outcomeDigest: receipt.outcomeDigest,
        terminalObserved: receipt.terminalObserved,
        observationReason: receipt.observationReason,
      });
      return receipt;
""")
replace_once(host, """  async closeProfile(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return exclusive(this.#locks, profileId, async () => {
      const state = this.#profile(input, false);
      const durable = await this.#journal.listOperations(
        state.profileId,
        state.generation,
      );
      if (
        durable.some((entry) => entry.terminalObserved !== true) ||
        [...state.operations.values()].some((entry) => !entry.receipt.terminalObserved)
      ) {
        throw new TypeError("profile has indeterminate browser effects requiring reconciliation");
      }
      const observed = requireRecord(
        await this.#callDriver(
          "stop",
          {
            profileId: state.profileId,
            processId: state.processId,
            generation: state.generation,
          },
          this.#clock() + this.#driverCallTimeoutMs,
        ),
        "driver stop observation",
      );
      if (observed.stopped !== true) throw new TypeError("driver did not observe profile stop");
      this.#profiles.delete(state.profileId);
      return freezeResult({
        kind: "BrowserProfileClosedV1",
        profileId: state.profileId,
        processId: state.processId,
        generation: state.generation,
        terminalObserved: true,
      });
    });
  }
""", """  async closeProfile(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return exclusive(this.#locks, profileId, async () => {
      const state = this.#profile(input, false);
      await this.#stopState(state, "explicit_close");
      const durable = await this.#journal.listOperations(
        state.profileId,
        state.generation,
      );
      const unresolvedIds = new Set(
        durable
          .filter((entry) => entry.terminalObserved !== true)
          .map((entry) => entry.operationId),
      );
      for (const [operationId, entry] of state.operations) {
        if (!entry.receipt.terminalObserved) unresolvedIds.add(operationId);
      }
      const retired = unresolvedIds.size === 0;
      if (retired) this.#profiles.delete(state.profileId);
      return freezeResult({
        kind: retired ? "BrowserProfileClosedV1" : "BrowserProfileFencedV1",
        profileId: state.profileId,
        processId: state.processId,
        generation: state.generation,
        terminalObserved: true,
        executionStopped: true,
        retired,
        unresolvedOperationCount: unresolvedIds.size,
        stopReason: state.stopReason,
      });
    });
  }
""")
replace_once(host, """  #profile(input, requireLiveGrant) {
""", """  #assertNewEffectAllowed(state) {
    if (this.#clock() >= state.expiresAtMs || state.fenced || state.stopped) {
      throw new TypeError("profile grant has expired or execution is fenced");
    }
  }

  #profile(input, requireLiveGrant) {
""")
replace_once(host, """    if (requireLiveGrant && this.#clock() >= state.expiresAtMs) {
      throw new TypeError("profile grant has expired");
    }
""", """    if (requireLiveGrant) this.#assertNewEffectAllowed(state);
""")
replace_once(host, """  #activeOperationCount(state) {
""", """  #scheduleLease(state) {
    if (state.leaseTimer !== null || state.fenced || state.stopped) return;
    const remaining = Math.max(0, state.expiresAtMs - this.#clock());
    const delayMs = Math.min(remaining, 2_147_483_647);
    state.leaseTimer = this.#setTimer(() => {
      state.leaseTimer = null;
      void exclusive(this.#locks, state.profileId, async () => {
        if (this.#profiles.get(state.profileId) !== state || state.stopped) return;
        if (this.#clock() < state.expiresAtMs) {
          this.#scheduleLease(state);
          return;
        }
        try {
          await this.#stopState(state, "profile_expired");
        } catch (error) {
          state.stopError = String(error?.message ?? error).slice(0, 512);
        }
      });
    }, delayMs);
  }

  async #stopState(state, reason) {
    state.fenced = true;
    state.stopReason ??= reason;
    if (state.leaseTimer !== null) {
      this.#clearTimer(state.leaseTimer);
      state.leaseTimer = null;
    }
    if (state.stopped) return;
    const observed = requireRecord(
      await this.#callDriver(
        "stop",
        {
          profileId: state.profileId,
          processId: state.processId,
          generation: state.generation,
        },
        this.#clock() + this.#driverCallTimeoutMs,
      ),
      "driver stop observation",
    );
    if (observed.stopped !== true) throw new TypeError("driver did not observe profile stop");
    state.stopped = true;
  }

  #activeOperationCount(state) {
""")

worker = "apps/hepta-browser/src/worker-driver.js"
replace_once(worker, """  WorkerFrameDecoder,
  buildWorkerFrame,
  encodeWorkerFrame,
} from "./worker-protocol.js";
""", """  WorkerFrameDecoder,
  buildWorkerFrame,
  encodeWorkerFrame,
  workerPayloadDigest,
} from "./worker-protocol.js";
""")
replace_once(worker, """const DIGEST = /^[0-9a-f]{64}$/;
const MAX_WORKER_ARTIFACT_BYTES = 512 * 1024 * 1024;
""", """const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const MAX_WORKER_ARTIFACT_BYTES = 512 * 1024 * 1024;
""")
replace_once(worker, """function expectedDigest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value)) {
    throw new TypeError(`${name} must be a lowercase SHA-256 digest`);
  }
  return value;
}
""", """function expectedDigest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value)) {
    throw new TypeError(`${name} must be a lowercase SHA-256 digest`);
  }
  return value;
}

function validateOperationObservation(observed, input) {
  const observation = requireRecord(observed, "worker operation observation");
  if (observation.operationId !== input.operationId) {
    throw new TypeError("worker operation observation crossed operation identity");
  }
  const expectedPayloadDigest = workerPayloadDigest(input);
  if (observation.operationPayloadDigest !== expectedPayloadDigest) {
    throw new TypeError("worker operation observation crossed payload identity");
  }
  if (
    !Number.isSafeInteger(observation.observedPageGeneration) ||
    observation.observedPageGeneration < 0
  ) {
    throw new TypeError("worker operation observation page generation is invalid");
  }
  if (
    observation.observedDocumentDigest !== null &&
    (typeof observation.observedDocumentDigest !== "string" ||
      !DIGEST.test(observation.observedDocumentDigest) ||
      observation.observedDocumentDigest === ZERO_DIGEST)
  ) {
    throw new TypeError("worker operation observation document digest is invalid");
  }
  return observation;
}
""")
replace_once(worker, """    const response = this.#client.request("dispatch", input.operationId, input, {
      signal,
      onDispatched: () => {
        if (crossed) return;
        crossed = true;
        resolveBoundary();
      },
    });
""", """    const response = this.#client
      .request("dispatch", input.operationId, input, {
        signal,
        onDispatched: () => {
          if (crossed) return;
          crossed = true;
          resolveBoundary();
        },
      })
      .then((observed) => validateOperationObservation(observed, input));
""")
replace_once(worker, """  async reconcile(input, { signal } = {}) {
    this.#requireSession(input);
    return this.#client.request("reconcile", input.operationId, input, { signal });
  }
""", """  async reconcile(input, { signal } = {}) {
    this.#requireSession(input);
    const observed = await this.#client.request("reconcile", input.operationId, input, { signal });
    return validateOperationObservation(observed, input);
  }
""")

runtime_test = "apps/hepta-browser/test/runtime.test.js"
replace_once(runtime_test, """  await assert.rejects(
    host.closeProfile({ profileId: "profile.1", principalId: "principal.1", generation: 1 }),
    /requiring reconciliation/,
  );
""", """  const fenced = await host.closeProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
  });
  assert.equal(fenced.executionStopped, true);
  assert.equal(fenced.retired, false);
  assert.equal(fenced.unresolvedOperationCount, 1);
""")
replace_once(runtime_test, """  await assert.rejects(close, /requiring reconciliation/);
  assert.equal(fakeDriver.stopCalls, 0);
""", """  const fenced = await close;
  assert.equal(fenced.executionStopped, true);
  assert.equal(fenced.retired, false);
  assert.equal(fakeDriver.stopCalls, 1);
""")
replace_once(runtime_test, "/profile grant has expired/", "/profile grant has expired|execution is fenced/")
replace_once(runtime_test, """test("typed action bytes are bound to final payload digest and destination", async () => {
""", """test("physical profile lease fences and stops the worker at expiry", async () => {
  let now = 1_000;
  let scheduled = null;
  const fakeDriver = driver();
  const host = new BrowserProfileHost({
    driver: fakeDriver,
    authority: authority(),
    journal: new MemoryBrowserOperationJournal(),
    clock: () => now,
    setTimer(callback, delayMs) {
      scheduled = { callback, delayMs };
      return scheduled;
    },
    clearTimer(handle) {
      if (scheduled === handle) scheduled = null;
    },
    driverCallTimeoutMs: 50,
  });
  await host.openProfile(input());
  assert.equal(scheduled.delayMs, 9_000);
  now = 10_000;
  const callback = scheduled.callback;
  callback();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(fakeDriver.stopCalls, 1);
  await assert.rejects(
    host.admitEffectGrant({
      profileId: "profile.1",
      principalId: "principal.1",
      generation: 1,
      effectGrant: effectGrant({ grantDigest: "6".repeat(64) }),
    }),
    /expired|fenced/,
  );
  const result = await host.closeProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
  });
  assert.equal(result.executionStopped, true);
  assert.equal(result.retired, true);
  assert.equal(fakeDriver.stopCalls, 1);
});

test("typed action bytes are bound to final payload digest and destination", async () => {
""")

worker_test = "apps/hepta-browser/test/worker-driver.test.js"
replace_once(worker_test, """  WorkerFrameDecoder,
  buildWorkerFrame,
  encodeWorkerFrame,
} from "../src/worker-protocol.js";
""", """  WorkerFrameDecoder,
  buildWorkerFrame,
  encodeWorkerFrame,
  workerPayloadDigest,
} from "../src/worker-protocol.js";
""")
replace_once(worker_test, """function fakeLauncher({ holdDispatchResponse = null } = {}) {
""", """function fakeLauncher({ holdDispatchResponse = null, corruptReconcileIdentity = false } = {}) {
""")
replace_once(worker_test, """      const decoder = new WorkerFrameDecoder();
      let sequence = 1;
""", """      const decoder = new WorkerFrameDecoder();
      const operations = new Map();
      let sequence = 1;
""")
replace_once(worker_test, """            case "dispatch":
              observation = { terminalObserved: false };
              break;
            case "reconcile":
              observation = {
                terminalObserved: true,
                status: "succeeded",
                outcomeDigest: D1,
              };
              break;
""", """            case "dispatch":
              operations.set(request.payload.operationId, workerPayloadDigest(request.payload));
              observation = {
                terminalObserved: false,
                operationId: request.payload.operationId,
                operationPayloadDigest: workerPayloadDigest(request.payload),
                observedPageGeneration: 1,
                observedDocumentDigest: D1,
              };
              break;
            case "reconcile": {
              const expected = operations.get(request.payload.operationId);
              if (expected !== workerPayloadDigest(request.payload)) {
                throw new Error("fake worker reconciliation payload drifted from dispatch");
              }
              observation = {
                terminalObserved: true,
                status: "succeeded",
                outcomeDigest: D1,
                operationId: corruptReconcileIdentity
                  ? "operation.corrupt"
                  : request.payload.operationId,
                operationPayloadDigest: workerPayloadDigest(request.payload),
                observedPageGeneration: 1,
                observedDocumentDigest: D1,
              };
              break;
            }
""")
replace_once(worker_test, """test("artifact-bound subprocess driver uses only the private framed channel", async () => {
""", """function operationPayload(operationId = "operation.1") {
  return {
    profileId: "profile.1",
    processId: "servo.pid.4242",
    profileGeneration: 1,
    operationId,
    pageGeneration: 1,
    documentDigest: D1,
    destinationOrigin: "https://example.com",
  };
}

test("artifact-bound subprocess driver uses only the private framed channel", async () => {
""")
replace_once(worker_test, """  const dispatched = await driver.dispatch({
    profileId: "profile.1",
    processId: started.processId,
    profileGeneration: 1,
    operationId: "operation.1",
  });
""", """  const operation = operationPayload();
  operation.processId = started.processId;
  const dispatched = await driver.dispatch(operation);
""")
replace_once(worker_test, """  const terminal = await driver.reconcile({
    profileId: "profile.1",
    processId: started.processId,
    profileGeneration: 1,
    generation: 1,
    operationId: "operation.1",
  });
""", """  const terminal = await driver.reconcile(operation);
""")
replace_once(worker_test, """    driver.dispatch({
      profileId: "profile.1",
      processId: started.processId,
      profileGeneration: 1,
      operationId: "operation.boundary",
    }),
""", """    driver.dispatch({
      ...operationPayload("operation.boundary"),
      processId: started.processId,
    }),
""")
replace_once(worker_test, """  const terminal = await driver.reconcile({
    profileId: "profile.1",
    processId: started.processId,
    profileGeneration: 1,
    generation: 1,
    operationId: "operation.boundary",
  });
""", """  const terminal = await driver.reconcile({
    ...operationPayload("operation.boundary"),
    processId: started.processId,
  });
""")
replace_once(worker_test, """test("subprocess driver fails closed on worker artifact digest drift", async () => {
""", """test("subprocess driver rejects a terminal receipt for another operation", async () => {
  const { driver, started } = await preparedDriver({
    launcher: fakeLauncher({ corruptReconcileIdentity: true }),
  });
  const operation = {
    ...operationPayload("operation.bound"),
    processId: started.processId,
  };
  await driver.dispatch(operation);
  await assert.rejects(driver.reconcile(operation), /crossed operation identity/);
});

test("subprocess driver fails closed on worker artifact digest drift", async () => {
""")
