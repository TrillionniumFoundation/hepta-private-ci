const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const MAX_OPERATION_RECORDS = 4096;
const PLATFORM_ACTIONS = new Set([
  "open_path",
  "reveal_path",
  "copy_text",
  "notify",
]);

function record(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw new TypeError(`${name} must be a plain object`);
  }
  const snapshot = Object.create(null);
  for (const key of Reflect.ownKeys(value)) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (
      typeof key !== "string" ||
      !Object.hasOwn(descriptor, "value") ||
      !descriptor.enumerable
    ) {
      throw new TypeError(
        `${name} fields must be enumerable own data properties`,
      );
    }
    snapshot[key] = descriptor.value;
  }
  return Object.freeze(snapshot);
}

function resourceReference(value) {
  if (
    typeof value !== "string" ||
    value.length > 4096 ||
    value.includes("\0")
  ) {
    throw new TypeError("resource must be a bounded text reference");
  }
  return value;
}

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function digest(value, name) {
  if (
    typeof value !== "string" ||
    !DIGEST.test(value) ||
    value === ZERO_DIGEST
  ) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function positive(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function result(value) {
  return Object.freeze({
    ...value,
    authorityGranted: false,
    filesystemAuthority: false,
    notificationAuthority: false,
    updateAuthority: false,
  });
}

export class NativeShellRuntime {
  #backend;
  #platform;
  #updater;
  #session = null;
  #view = null;
  #operations = new Map();
  #connectionEpoch = 0;
  #updates = new Map();
  #pendingUpdate = null;

  constructor({ backend, platform, updater }) {
    for (const [name, value, methods] of [
      ["backend", backend, ["connect", "request", "close"]],
      ["platform", platform, ["permission", "invoke"]],
      ["updater", updater, ["verify", "apply", "rollback"]],
    ]) {
      if (value === null || typeof value !== "object" || Array.isArray(value)) {
        throw new TypeError(`${name} must be an object`);
      }
      for (const method of methods) {
        if (typeof value[method] !== "function") {
          throw new TypeError(`${name}.${method} must be a function`);
        }
      }
    }
    this.#backend = backend;
    this.#platform = platform;
    this.#updater = updater;
  }

  async connectRuntime(manifest) {
    if (this.#pendingUpdate) {
      throw new TypeError("shell update is already in progress");
    }
    manifest = record(manifest, "manifest");
    const endpointId = stableId(manifest.endpointId, "endpointId");
    const manifestDigest = digest(manifest.manifestDigest, "manifestDigest");
    const protocolVersion = positive(
      manifest.protocolVersion,
      "protocolVersion",
    );
    const epoch = ++this.#connectionEpoch;
    this.#session = null;
    this.#view = null;
    const observed = record(
      await this.#backend.connect({
        endpointId,
        manifestDigest,
        protocolVersion,
      }),
      "backend connection",
    );
    if (epoch !== this.#connectionEpoch) {
      throw new TypeError("backend connection was superseded");
    }
    if (observed.authenticated !== true) {
      throw new TypeError("backend connection is not authenticated");
    }
    if (observed.protocolVersion !== protocolVersion) {
      throw new TypeError("backend protocol version mismatch");
    }
    this.#session = {
      endpointId,
      manifestDigest,
      protocolVersion,
      sessionId: stableId(observed.sessionId, "sessionId"),
      generation: positive(observed.generation, "generation"),
    };
    this.#view = null;
    return result({ kind: "NativeSessionV1", ...this.#session });
  }

  renderRuntimeView(view) {
    this.#requireSession();
    view = record(view, "view");
    if (view.sessionId !== this.#session.sessionId) {
      throw new TypeError("view session mismatch");
    }
    if (view.sessionGeneration !== this.#session.generation) {
      throw new TypeError("view session generation mismatch");
    }
    const generation = positive(view.generation, "view generation");
    const revision = positive(view.revision, "view revision");
    const viewDigest = digest(view.digest, "view digest");
    if (this.#view) {
      if (generation < this.#view.generation) {
        throw new TypeError("view generation regressed");
      }
      if (
        generation === this.#view.generation &&
        revision <= this.#view.revision
      ) {
        throw new TypeError("view revision did not advance");
      }
    }
    this.#view = {
      generation,
      revision,
      digest: viewDigest,
      modules: Object.freeze([...(view.modules ?? [])]),
    };
    return result({
      kind: "NativePresentationStateV1",
      sessionId: this.#session.sessionId,
      ...this.#view,
      stale: false,
    });
  }

  async requestPlatformCapability(input) {
    this.#requireView();
    input = record(input, "input");
    const operationId = stableId(input.operationId, "operationId");
    const action = input.action;
    if (!PLATFORM_ACTIONS.has(action)) {
      throw new TypeError("platform action is not registered");
    }
    if (input.displayedRevision !== this.#view.revision) {
      throw new TypeError(
        "platform request was confirmed against a stale view",
      );
    }
    const resource = resourceReference(input.resource);
    const finalPayloadDigest = digest(
      input.finalPayloadDigest,
      "finalPayloadDigest",
    );
    const grantPayloadDigest = digest(
      input.grantPayloadDigest,
      "grantPayloadDigest",
    );
    if (finalPayloadDigest !== grantPayloadDigest) {
      throw new TypeError("grant does not bind final platform payload");
    }
    const session = this.#session;
    const view = this.#view;
    const prior = this.#operations.get(operationId);
    if (prior) {
      if (
        prior.finalPayloadDigest !== finalPayloadDigest ||
        prior.action !== action ||
        prior.resource !== resource ||
        prior.session !== session
      ) {
        throw new TypeError(
          "operation identity was reused with changed binding",
        );
      }
      return prior.promise;
    }
    if (this.#operations.size >= MAX_OPERATION_RECORDS) {
      throw new TypeError("native operation capacity exhausted");
    }
    // Reserve identity before any asynchronous permission/dispatch boundary.
    // Retain unknown outcomes so a lost acknowledgement cannot cause replay.
    const operation = {
      operationId,
      action,
      resource,
      finalPayloadDigest,
      session,
    };
    this.#operations.set(operationId, operation);
    operation.promise = Promise.resolve().then(() =>
      this.#executePlatformRequest(operation, view),
    );
    return operation.promise;
  }

  async #executePlatformRequest(operation, view) {
    const { operationId, action, resource, finalPayloadDigest, session } =
      operation;
    let permission;
    try {
      if (this.#session !== session || this.#view !== view) {
        throw new TypeError(
          "platform request session or view changed before dispatch",
        );
      }
      permission = record(
        await this.#platform.permission({ action, resource }),
        "platform permission",
      );
      if (this.#session !== session || this.#view !== view) {
        throw new TypeError(
          "platform request session or view changed before dispatch",
        );
      }
      if (permission.allowed !== true && permission.allowed !== false) {
        throw new TypeError(
          "platform permission must be exactly true or false",
        );
      }
      if (permission.allowed === false) {
        return result({
          kind: "PlatformDecisionV1",
          operationId,
          action,
          status: "rejected",
          terminalObserved: true,
          outcomeDigest: digest(permission.outcomeDigest, "outcomeDigest"),
        });
      }
    } catch (error) {
      // No effect adapter was entered, so retry remains safe.
      this.#operations.delete(operationId);
      throw error;
    }
    try {
      const observed = record(
        await this.#platform.invoke({
          sessionId: session.sessionId,
          sessionGeneration: session.generation,
          operationId,
          action,
          resource,
          finalPayloadDigest,
        }),
        "platform observation",
      );
      if (observed.terminalObserved === true) {
        if (observed.status !== "succeeded" && observed.status !== "failed") {
          throw new TypeError("terminal platform status is not registered");
        }
        return result({
          kind: "PlatformDecisionV1",
          operationId,
          action,
          status: observed.status,
          terminalObserved: true,
          outcomeDigest: digest(observed.outcomeDigest, "outcomeDigest"),
        });
      }
    } catch {
      // Adapter failure or malformed post-dispatch evidence cannot prove absence.
    }
    return result({
      kind: "PlatformDecisionV1",
      operationId,
      action,
      status: "indeterminate",
      terminalObserved: false,
      outcomeDigest: null,
    });
  }

  async applyShellUpdate(input) {
    input = record(input, "input");
    const packageDigest = digest(input.packageDigest, "packageDigest");
    const predecessorDigest = digest(
      input.predecessorDigest,
      "predecessorDigest",
    );
    const evidenceDigest = digest(input.evidenceDigest, "evidenceDigest");
    const selectedBy = stableId(input.selectedBy, "selectedBy");
    const generatorPrincipal = stableId(
      input.generatorPrincipal,
      "generatorPrincipal",
    );
    const platform = stableId(input.platform, "platform");
    const architecture = stableId(input.architecture, "architecture");
    if (selectedBy === generatorPrincipal) {
      throw new TypeError("shell update cannot be selected by its generator");
    }
    const binding = JSON.stringify([
      predecessorDigest,
      evidenceDigest,
      selectedBy,
      generatorPrincipal,
      platform,
      architecture,
    ]);
    const prior = this.#updates.get(packageDigest);
    if (prior) {
      if (prior.binding !== binding) {
        throw new TypeError("update identity was reused with changed binding");
      }
      return prior.promise;
    }
    this.#requireSession();
    if (this.#pendingUpdate) {
      throw new TypeError("shell update is already in progress");
    }
    if (this.#updates.size >= 128) {
      throw new TypeError("shell update capacity exhausted");
    }
    const operation = { binding, dispatched: false, rollbackStarted: false };
    const session = this.#session;
    this.#updates.set(packageDigest, operation);
    this.#pendingUpdate = operation;
    operation.promise = Promise.resolve()
      .then(() => this.#executeShellUpdate(input, operation, session))
      .catch(async (error) => {
        if (!operation.dispatched) {
          this.#updates.delete(packageDigest);
          throw error;
        }
        if (!operation.rollbackStarted) {
          operation.rollbackStarted = true;
          try {
            await this.#updater.rollback({ predecessorDigest });
          } catch {}
        }
        return result({
          kind: "UpdateDispositionV1",
          packageDigest,
          predecessorDigest,
          status: "quarantined",
          terminalObserved: false,
        });
      })
      .finally(() => {
        this.#pendingUpdate = null;
      });
    return operation.promise;
  }

  async #executeShellUpdate(input, operation, session) {
    const { packageDigest, predecessorDigest, evidenceDigest } = input;
    if (this.#session !== session) {
      throw new TypeError("shell update session changed before apply");
    }
    const verification = record(
      await this.#updater.verify({
        packageDigest,
        predecessorDigest,
        evidenceDigest,
        platform: input.platform,
        architecture: input.architecture,
        backendProtocolVersion: session.protocolVersion,
      }),
      "update verification",
    );
    if (this.#session !== session) {
      throw new TypeError("shell update session changed before apply");
    }
    if (verification.accepted !== true) {
      throw new TypeError("shell update verification failed");
    }
    operation.dispatched = true;
    ++this.#connectionEpoch;
    this.#session = null;
    this.#view = null;
    const observed = record(
      await this.#updater.apply({
        packageDigest,
        predecessorDigest,
        restartRequired: true,
      }),
      "update observation",
    );
    if (observed.terminalObserved !== true || observed.restarted !== true) {
      operation.rollbackStarted = true;
      await this.#updater.rollback({ predecessorDigest });
      return result({
        kind: "UpdateDispositionV1",
        packageDigest,
        predecessorDigest,
        status: "quarantined",
        terminalObserved: observed.terminalObserved === true,
      });
    }
    return result({
      kind: "UpdateDispositionV1",
      packageDigest,
      predecessorDigest,
      status: "succeeded",
      terminalObserved: true,
    });
  }

  async close() {
    ++this.#connectionEpoch;
    if (!this.#session) {
      return;
    }
    const session = this.#session;
    this.#session = null;
    this.#view = null;
    await this.#backend.close({ sessionId: session.sessionId });
  }

  #requireSession() {
    if (!this.#session) {
      throw new TypeError("native shell is not connected");
    }
  }

  #requireView() {
    this.#requireSession();
    if (!this.#view) {
      throw new TypeError("platform request requires a coherent runtime view");
    }
  }
}
