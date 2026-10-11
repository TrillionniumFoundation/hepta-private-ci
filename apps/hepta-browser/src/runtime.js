import { BrowserProfileHost as HardenedBrowserProfileHost } from "./runtime-host.js";

// Stable owner-boundary facade. Keep the public operation symbols here so the
// repository implementation map remains an exact source anchor while the
// hardened state machine is decomposed into smaller internal modules.
export class BrowserProfileHost extends HardenedBrowserProfileHost {
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
