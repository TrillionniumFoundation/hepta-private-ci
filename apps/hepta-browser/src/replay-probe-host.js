import { REPLAY_PROBE_ABSENCE_CODE } from "./runtime-contract.js";

export const REPLAY_PROBE_RESULT_KIND =
  "hepta.browser.replay-probe-result.v1";

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
 * is routed through BrowserProfileHost.navigateOrAct. Existing immutable
 * operations return a versioned present envelope before authority. Only the
 * exact owner-issued absence code becomes a versioned absent envelope; every
 * semantic conflict, protocol failure and unknown error remains a rejection.
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

  async reconcileOperation(input) {
    if (input?.replayOnly !== true) {
      return this.#host.reconcileOperation(input);
    }
    try {
      const receipt = await this.#host.navigateOrAct(input);
      return Object.freeze({
        kind: REPLAY_PROBE_RESULT_KIND,
        status: "present",
        receipt,
      });
    } catch (error) {
      if (error?.code !== REPLAY_PROBE_ABSENCE_CODE) throw error;
      return Object.freeze({
        kind: REPLAY_PROBE_RESULT_KIND,
        status: "absent",
        absenceCode: REPLAY_PROBE_ABSENCE_CODE,
      });
    }
  }

  reconcilePersistedOperation(input) {
    return this.#host.reconcilePersistedOperation(input);
  }

  closeProfile(input) {
    return this.#host.closeProfile(input);
  }
}
