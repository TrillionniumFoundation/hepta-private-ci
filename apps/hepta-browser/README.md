# Hepta browser

This root contains the authority-free browser presentation/navigation-intent boundary and the hardened `browser.servo` driver/effect host.

`src/browser.js` normalizes HTTP(S) targets, binds policy and source revisions, and never grants network or effect authority. The legacy object entrypoints remain compatibility surfaces. The additive `Local` JSON entrypoints are versioned private-workspace exports for shadow qualification, not registered module ingress/egress or production callers. They bound encoded envelopes before parsing, require canonical field order, reject duplicate/missing/unknown fields, reject credential/userinfo and control-character URL forms, and cap normalized URLs.

`src/runtime.js` owns the profile/page/effect state machine around an isolated driver contract. A production composition must provide:

- an isolated driver that declares abort-signal, private-control-channel, process, network-policy, profile-isolation and credential-boundary support;
- a final-use authority adapter with `claim` and `withVerifiedUse` semantics;
- a durable browser state store.

The host persists an indeterminate operation intent before entering the driver effect boundary, never automatically redispatches an uncertain operation, permits reconciliation after the original effect deadline/grant expires, binds typed action bytes to `finalPayloadDigest`, serializes one profile's mutations, quarantines observations outside granted origins, and provides bounded terminal-operation compaction.

`src/state-store.js` provides an atomic file-backed state store plus an explicitly opt-in volatile test store. `src/bridge.js` closes a registered `BrowserNavigationIntentV1` into an exact typed navigation operation for the runtime host.

Servo source integration is pinned separately under `third_party/servo-patches`. The real Hepta-owned Servo worker, target-OS sandbox, credential/network enforcement and real WebView/business-effect qualification remain external implementation gates; the JavaScript capability assertions are not independent OS evidence.

Current module hardening and worker ADRs are in `docs/modules/browser.servo/`.
