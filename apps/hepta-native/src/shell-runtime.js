const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
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

export class NativeShellRuntime {
  #backend;
  #platform;
  #updater;
  #session = null;
  #view = null;
  #operations = new Map();

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
      ...this.#view,
      stale: false,
    });
  }

  async requestPlatformCapability(input) {
    this.#requireView();
    record(input, "input");
    const operationId = stableId(input.operationId, "operationId");
    if (!PLATFORM_ACTIONS.has(input.action)) {
      throw new TypeError("platform action is not registered");
    }
    if (input.displayedRevision !== this.#view.revision) {
      throw new TypeError("platform request was confirmed against a stale view");
    }
    const finalPayloadDigest = digest(input.finalPayloadDigest, "finalPayloadDigest");
    const grantPayloadDigest = digest(input.grantPayloadDigest, "grantPayloadDigest");
    if (finalPayloadDigest !== grantPayloadDigest) {
      throw new TypeError("grant does not bind final platform payload");
    }
    const prior = this.#operations.get(operationId);
    if (prior) {
      if (prior.finalPayloadDigest !== finalPayloadDigest) {
        throw new TypeError("operation identity was reused with changed payload");
      }
      return prior.receipt;
    }
    const permission = record(
      await this.#platform.permission({
        action: input.action,
        resource: input.resource,
      }),
      "platform permission",
    );
    if (permission.allowed !== true) {
      return result({
        kind: "PlatformDecisionV1",
        operationId,
        action: input.action,
        status: "rejected",
        terminalObserved: true,
        outcomeDigest: digest(permission.outcomeDigest, "outcomeDigest"),
      });
    }
    const observed = record(
      await this.#platform.invoke({
        sessionId: this.#session.sessionId,
        sessionGeneration: this.#session.generation,
        operationId,
        action: input.action,
        resource: input.resource,
        finalPayloadDigest,
      }),
      "platform observation",
    );
    let receipt;
    if (observed.terminalObserved !== true) {
      receipt = result({
        kind: "PlatformDecisionV1",
        operationId,
        action: input.action,
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
        operationId,
        action: input.action,
        status: observed.status,
        terminalObserved: true,
        outcomeDigest: digest(observed.outcomeDigest, "outcomeDigest"),
      });
    }
    this.#operations.set(operationId, { finalPayloadDigest, receipt });
    return receipt;
  }

  async applyShellUpdate(input) {
    this.#requireSession();
    record(input, "input");
    const packageDigest = digest(input.packageDigest, "packageDigest");
    const predecessorDigest = digest(input.predecessorDigest, "predecessorDigest");
    const evidenceDigest = digest(input.evidenceDigest, "evidenceDigest");
    const selectedBy = stableId(input.selectedBy, "selectedBy");
    if (selectedBy === input.generatorPrincipal) {
      throw new TypeError("shell update cannot be selected by its generator");
    }
    const verification = record(
      await this.#updater.verify({
        packageDigest,
        predecessorDigest,
        evidenceDigest,
        platform: input.platform,
        architecture: input.architecture,
        backendProtocolVersion: this.#session.protocolVersion,
      }),
      "update verification",
    );
    if (verification.accepted !== true) {
      throw new TypeError("shell update verification failed");
    }
    const observed = record(
      await this.#updater.apply({
        packageDigest,
        predecessorDigest,
        restartRequired: true,
      }),
      "update observation",
    );
    if (observed.terminalObserved !== true || observed.restarted !== true) {
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
    if (!this.#session) {
      return;
    }
    await this.#backend.close({ sessionId: this.#session.sessionId });
    this.#session = null;
    this.#view = null;
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
