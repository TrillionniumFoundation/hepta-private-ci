import { browserOperationFromComputerActionV1 } from "./computer-action.js";
import { BrowserProfileHost as HardenedBrowserProfileHost } from "./runtime-host.js";

// Stable owner-boundary facade. Keep the public operation symbols here so the
// repository implementation map remains an exact source anchor while the
// hardened state machine is decomposed into smaller internal modules.
export class BrowserProfileHost extends HardenedBrowserProfileHost {
  #binaryResolver;
  #binaryActuatorId;

  constructor(options) {
    super(options);
    this.#binaryResolver = options.binaryResolver ?? null;
    this.#binaryActuatorId = options.binaryActuatorId ?? "browser-servo";
    if (
      this.#binaryResolver !== null &&
      (typeof this.#binaryResolver !== "object" ||
        typeof this.#binaryResolver.resolve !== "function")
    ) {
      throw new TypeError("binaryResolver.resolve must be a function");
    }
  }

  async openProfile(input) {
    return super.openProfile(input);
  }

  async admitEffectGrant(input) {
    return super.admitEffectGrant(input);
  }

  async observePage(input) {
    return super.observePage(input);
  }

  async navigateOrAct(input) {
    return super.navigateOrAct(input);
  }

  async navigateOrActBinary(input) {
    if (input !== null && typeof input === "object" && "resolver" in input) {
      throw new TypeError("binary browser resolver is host-owned");
    }
    const resolver = this.#binaryResolver;
    if (
      resolver === null ||
      typeof resolver !== "object" ||
      typeof resolver.resolve !== "function"
    ) {
      throw new TypeError("binary browser reference resolver is unavailable");
    }
    const page = await super.binaryActionContext(input);
    const operation = await browserOperationFromComputerActionV1({
      ...input,
      ...page,
      actuatorId: this.#binaryActuatorId,
      resolver,
    });
    return super.navigateOrAct(operation);
  }

  async reconcileOperation(input) {
    return super.reconcileOperation(input);
  }

  async reconcilePersistedOperation(input) {
    return super.reconcilePersistedOperation(input);
  }

  async closeProfile(input) {
    return super.closeProfile(input);
  }
}
