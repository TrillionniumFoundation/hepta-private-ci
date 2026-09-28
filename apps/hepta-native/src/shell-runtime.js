const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const MAX_PLATFORM_OPERATIONS = 1024;
const PLATFORM_INPUT_KEYS = [
  "operationId", "action", "resource", "displayedRevision",
  "finalPayloadDigest", "grantPayloadDigest",
];
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

function platformInput(input) {
  record(input, "input");
  const descriptors = Object.getOwnPropertyDescriptors(input);
  const keys = Reflect.ownKeys(descriptors);
  if (keys.length !== PLATFORM_INPUT_KEYS.length ||
      PLATFORM_INPUT_KEYS.some((key) => !Object.hasOwn(descriptors, key)) ||
      keys.some((key) => typeof key !== "string" ||
        !Object.hasOwn(descriptors[key], "value") || !descriptors[key].enumerable)) {
    throw new TypeError("platform input must contain exact own data fields");
  }
  return Object.freeze(Object.fromEntries(keys.map((key) => [key, descriptors[key].value])));
}

export class NativeShellRuntime {
  #backend;
  #platform;
  #updater;
  #session = null;
  #view = null;
  #operations = new Map();
  #connectionVersion = 0;

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
    const connectionVersion = ++this.#connectionVersion;
    this.#session = null;
    this.#view = null;
    const observed = record(
      await this.#backend.connect({ endpointId, manifestDigest, protocolVersion }),
      "backend connection",
    );
    if (connectionVersion !== this.#connectionVersion) {
      throw new TypeError("connection was superseded");
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
    const request = platformInput(input);
    const operationId = stableId(request.operationId, "operationId");
    if (!PLATFORM_ACTIONS.has(request.action)) {
      throw new TypeError("platform action is not registered");
    }
    const resource = stableId(request.resource, "resource reference");
    if (request.displayedRevision !== this.#view.revision) {
      throw new TypeError("platform request was confirmed against a stale view");
    }
    const finalPayloadDigest = digest(request.finalPayloadDigest, "finalPayloadDigest");
    if (finalPayloadDigest !== digest(request.grantPayloadDigest, "grantPayloadDigest")) {
      throw new TypeError("grant does not bind final platform payload");
    }
    const session = this.#session;
    const view = this.#view;
    const binding = JSON.stringify([
      session.sessionId, session.generation, view.generation, view.revision,
      view.digest, request.action, resource, finalPayloadDigest,
    ]);
    const prior = this.#operations.get(operationId);
    if (prior) {
      if (prior.binding !== binding) {
        throw new TypeError("operation identity was reused with changed semantics");
      }
      return prior.promise;
    }
    if (this.#operations.size >= MAX_PLATFORM_OPERATIONS) {
      throw new TypeError("platform operation capacity exceeded");
    }
    // Reserve before any asynchronous permission call. Do not evict unknown work.
    const entry = { binding, promise: null };
    this.#operations.set(operationId, entry);
    entry.promise = Promise.resolve().then(async () => {
      const permission = record(await this.#platform.permission({
        action: request.action, resource,
      }), "platform permission");
      const common = {
        kind: "PlatformDecisionV1", operationId, action: request.action,
        sessionId: session.sessionId, sessionGeneration: session.generation,
      };
      if (permission.allowed !== true) {
        return result({ ...common, status: "rejected", terminalObserved: true,
          outcomeDigest: digest(permission.outcomeDigest, "outcomeDigest") });
      }
      // A reconnect, close or new view while permission was pending cannot
      // authorize dispatch using the predecessor observation or new session.
      if (this.#session !== session || this.#view !== view) {
        throw new TypeError("platform context changed before dispatch");
      }
      const indeterminate = result({ ...common, status: "indeterminate",
        terminalObserved: false, outcomeDigest: null });
      try {
        const observed = record(await this.#platform.invoke({
          sessionId: session.sessionId, sessionGeneration: session.generation,
          operationId, action: request.action, resource, finalPayloadDigest,
        }), "platform observation");
        if (observed.terminalObserved !== true) return indeterminate;
        if (observed.status !== "succeeded" && observed.status !== "failed") {
          return indeterminate;
        }
        return result({ ...common, status: observed.status, terminalObserved: true,
          outcomeDigest: digest(observed.outcomeDigest, "outcomeDigest") });
      } catch {
        // Once invoke was entered, exceptions/malformed replies prove neither
        // non-application nor safe retry. Retain the identity and uncertainty.
        return indeterminate;
      }
    }).catch((error) => {
      // Only a proven pre-invoke failure may release the local reservation.
      if (this.#operations.get(operationId) === entry) this.#operations.delete(operationId);
      throw error;
    });
    return entry.promise;
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
    const session = this.#session;
    ++this.#connectionVersion;
    this.#session = null;
    this.#view = null;
    if (session) await this.#backend.close({ sessionId: session.sessionId });
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
