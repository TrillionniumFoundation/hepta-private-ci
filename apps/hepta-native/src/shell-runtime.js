const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const PLATFORM_ACTIONS = new Set([
  "open_path",
  "reveal_path",
  "copy_text",
  "notify",
]);
const MAX_OPERATIONS = 1024;
const PLATFORM_BINDING_FIELDS = Object.freeze([
  "sessionId",
  "sessionGeneration",
  "endpointId",
  "manifestDigest",
  "protocolVersion",
  "viewGeneration",
  "displayedRevision",
  "viewDigest",
  "operationId",
  "action",
  "resource",
  "finalPayloadDigest",
  "grantPayloadDigest",
]);
const UPDATE_BINDING_FIELDS = Object.freeze([
  "sessionId",
  "sessionGeneration",
  "endpointId",
  "manifestDigest",
  "protocolVersion",
  "operationId",
  "packageDigest",
  "predecessorDigest",
  "evidenceDigest",
  "selectedBy",
  "generatorPrincipal",
  "platform",
  "architecture",
]);

function record(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
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
  if (typeof value !== "string" || !DIGEST.test(value) || value === ZERO_DIGEST) {
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

function sameBinding(left, right, fields) {
  return fields.every((field) => left[field] === right[field]);
}

export class NativeShellRuntime {
  #backend;
  #platform;
  #updater;
  #session = null;
  #view = null;
  #operations = new Map();
  #updates = new Map();

  constructor({ backend, platform, updater }) {
    for (const [name, value, methods] of [
      ["backend", backend, ["connect", "request", "close"]],
      ["platform", platform, ["permission", "invoke"]],
      ["updater", updater, ["verify", "apply", "rollback"]],
    ]) {
      record(value, name);
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
    record(manifest, "manifest");
    if (this.#session) {
      throw new TypeError("native shell is already connected");
    }
    const endpointId = stableId(manifest.endpointId, "endpointId");
    const manifestDigest = digest(manifest.manifestDigest, "manifestDigest");
    const protocolVersion = positive(manifest.protocolVersion, "protocolVersion");
    const observed = record(
      await this.#backend.connect({ endpointId, manifestDigest, protocolVersion }),
      "backend connection",
    );
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
    record(view, "view");
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
      if (generation === this.#view.generation && revision <= this.#view.revision) {
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
      sessionGeneration: this.#session.generation,
      ...this.#view,
      stale: false,
    });
  }

  async requestPlatformCapability(input) {
    this.#requireView();
    record(input, "input");
    const operationId = stableId(input.operationId, "operationId");
    const action = stableId(input.action, "action");
    if (!PLATFORM_ACTIONS.has(action)) {
      throw new TypeError("platform action is not registered");
    }
    const resource = stableId(input.resource, "resource");
    const displayedRevision = positive(input.displayedRevision, "displayedRevision");
    if (displayedRevision !== this.#view.revision) {
      throw new TypeError("platform request was confirmed against a stale view");
    }
    const finalPayloadDigest = digest(input.finalPayloadDigest, "finalPayloadDigest");
    const grantPayloadDigest = digest(input.grantPayloadDigest, "grantPayloadDigest");
    if (finalPayloadDigest !== grantPayloadDigest) {
      throw new TypeError("grant does not bind final platform payload");
    }
    const binding = Object.freeze({
      sessionId: this.#session.sessionId,
      sessionGeneration: this.#session.generation,
      endpointId: this.#session.endpointId,
      manifestDigest: this.#session.manifestDigest,
      protocolVersion: this.#session.protocolVersion,
      viewGeneration: this.#view.generation,
      displayedRevision,
      viewDigest: this.#view.digest,
      operationId,
      action,
      resource,
      finalPayloadDigest,
      grantPayloadDigest,
    });
    const prior = this.#operations.get(operationId);
    if (prior) {
      if (!sameBinding(prior.binding, binding, PLATFORM_BINDING_FIELDS)) {
        throw new TypeError("operation identity was reused with changed semantics");
      }
      return prior.receipt;
    }
    if (this.#operations.size >= MAX_OPERATIONS) {
      throw new TypeError("native operation capacity is exhausted");
    }

    const permission = record(
      await this.#platform.permission({
        sessionId: binding.sessionId,
        sessionGeneration: binding.sessionGeneration,
        viewGeneration: binding.viewGeneration,
        displayedRevision,
        action,
        resource,
        finalPayloadDigest,
      }),
      "platform permission",
    );
    let receipt;
    if (permission.allowed !== true) {
      receipt = result({
        kind: "PlatformDecisionV1",
        ...binding,
        status: "rejected",
        terminalObserved: true,
        outcomeDigest: digest(permission.outcomeDigest, "outcomeDigest"),
      });
      this.#operations.set(operationId, { binding, receipt });
      return receipt;
    }

    const observed = record(
      await this.#platform.invoke(binding),
      "platform observation",
    );
    if (observed.terminalObserved !== true) {
      receipt = result({
        kind: "PlatformDecisionV1",
        ...binding,
        status: "indeterminate",
        terminalObserved: false,
        outcomeDigest: null,
      });
    } else {
      if (observed.status !== "succeeded" && observed.status !== "failed") {
        throw new TypeError("terminal platform status is not registered");
      }
      receipt = result({
        kind: "PlatformDecisionV1",
        ...binding,
        status: observed.status,
        terminalObserved: true,
        outcomeDigest: digest(observed.outcomeDigest, "outcomeDigest"),
      });
    }
    this.#operations.set(operationId, { binding, receipt });
    return receipt;
  }

  async applyShellUpdate(input) {
    this.#requireSession();
    record(input, "input");
    const operationId = stableId(input.operationId, "operationId");
    const packageDigest = digest(input.packageDigest, "packageDigest");
    const predecessorDigest = digest(input.predecessorDigest, "predecessorDigest");
    const evidenceDigest = digest(input.evidenceDigest, "evidenceDigest");
    const selectedBy = stableId(input.selectedBy, "selectedBy");
    const generatorPrincipal = stableId(input.generatorPrincipal, "generatorPrincipal");
    const platform = stableId(input.platform, "platform");
    const architecture = stableId(input.architecture, "architecture");
    if (selectedBy === generatorPrincipal) {
      throw new TypeError("shell update cannot be selected by its generator");
    }
    const binding = Object.freeze({
      sessionId: this.#session.sessionId,
      sessionGeneration: this.#session.generation,
      endpointId: this.#session.endpointId,
      manifestDigest: this.#session.manifestDigest,
      protocolVersion: this.#session.protocolVersion,
      operationId,
      packageDigest,
      predecessorDigest,
      evidenceDigest,
      selectedBy,
      generatorPrincipal,
      platform,
      architecture,
    });
    const prior = this.#updates.get(operationId);
    if (prior) {
      if (!sameBinding(prior.binding, binding, UPDATE_BINDING_FIELDS)) {
        throw new TypeError("update operation identity was reused with changed semantics");
      }
      return prior.receipt;
    }
    if (this.#updates.size >= MAX_OPERATIONS) {
      throw new TypeError("native update capacity is exhausted");
    }

    const verification = record(
      await this.#updater.verify({
        packageDigest,
        predecessorDigest,
        evidenceDigest,
        selectedBy,
        platform,
        architecture,
        backendProtocolVersion: this.#session.protocolVersion,
      }),
      "update verification",
    );
    if (
      verification.accepted !== true ||
      verification.packageDigest !== packageDigest ||
      verification.predecessorDigest !== predecessorDigest ||
      verification.evidenceDigest !== evidenceDigest
    ) {
      throw new TypeError("shell update verification failed or drifted");
    }

    let observed;
    try {
      observed = record(
        await this.#updater.apply({
          operationId,
          packageDigest,
          predecessorDigest,
          restartRequired: true,
        }),
        "update observation",
      );
    } catch (error) {
      return this.#rollbackUpdate(binding, `apply threw: ${String(error)}`);
    }
    if (
      observed.terminalObserved !== true ||
      observed.restarted !== true ||
      observed.packageDigest !== packageDigest
    ) {
      return this.#rollbackUpdate(binding, "apply was not terminally observed");
    }
    const receipt = result({
      kind: "UpdateDispositionV1",
      ...binding,
      status: "succeeded",
      terminalObserved: true,
      rollbackTerminalObserved: false,
    });
    this.#updates.set(operationId, { binding, receipt });
    return receipt;
  }

  async close() {
    if (!this.#session) {
      return;
    }
    await this.#backend.close({
      sessionId: this.#session.sessionId,
      sessionGeneration: this.#session.generation,
    });
    this.#session = null;
    this.#view = null;
  }

  async #rollbackUpdate(binding, reason) {
    let rollback;
    try {
      rollback = record(
        await this.#updater.rollback({
          operationId: binding.operationId,
          predecessorDigest: binding.predecessorDigest,
          failedPackageDigest: binding.packageDigest,
          reason,
        }),
        "rollback observation",
      );
    } catch (error) {
      throw new TypeError(`shell rollback was not observed: ${String(error)}`);
    }
    if (
      rollback.terminalObserved !== true ||
      rollback.restored !== true ||
      rollback.predecessorDigest !== binding.predecessorDigest
    ) {
      throw new TypeError("shell rollback was not terminally observed");
    }
    const receipt = result({
      kind: "UpdateDispositionV1",
      ...binding,
      status: "quarantined",
      terminalObserved: true,
      rollbackTerminalObserved: true,
    });
    this.#updates.set(binding.operationId, { binding, receipt });
    return receipt;
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
