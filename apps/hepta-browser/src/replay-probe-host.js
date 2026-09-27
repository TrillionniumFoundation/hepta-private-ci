function requireHost(host) {
  if (host === null || typeof host !== "object") {
    throw new TypeError("replay probe host requires an object capability");
  }
  for (const method of [
    "openProfile",
    "admitEffectGrant",
    "observePage",
    "navigateOrAct",
    "reconcileOperation",
    "reconcilePersistedOperation",
    "closeProfile",
  ]) {
    if (typeof host[method] !== "function") {
      throw new TypeError(`replay probe host.${method} is required`);
    }
  }
  return host;
}

/**
 * Keeps the public seven-RPC surface unchanged while giving Agentd one explicit
 * read-only replay probe. A `reconcile_operation` carrying `replayOnly:true`
 * is routed through BrowserProfileHost.navigateOrAct: an existing immutable
 * operation returns its original receipt before authority; a missing operation
 * reaches admitNewOperation, which rejects the probe without dispatch.
 */
export class ReplayProbeBrowserHost {
  #host;

  constructor(host) {
    this.#host = requireHost(host);
  }

  openProfile(input) {
    return this.#host.openProfile(input);
  }

  admitEffectGrant(input) {
    return this.#host.admitEffectGrant(input);
  }

  observePage(input) {
    return this.#host.observePage(input);
  }

  navigateOrAct(input) {
    return this.#host.navigateOrAct(input);
  }

  reconcileOperation(input) {
    if (input?.replayOnly === true) {
      return this.#host.navigateOrAct(input);
    }
    return this.#host.reconcileOperation(input);
  }

  reconcilePersistedOperation(input) {
    return this.#host.reconcilePersistedOperation(input);
  }

  closeProfile(input) {
    return this.#host.closeProfile(input);
  }
}
