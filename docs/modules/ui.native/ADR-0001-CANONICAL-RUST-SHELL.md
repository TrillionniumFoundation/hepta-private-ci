# ADR-0001: Canonical Rust Native Shell

- Status: Accepted
- Decision date: 2026-09-26
- Owners: `ui-platform`, `accessibility`
- Applies to: `ui.native`
- Canonical source root: `apps/hepta-native`

## Context

The repository previously contained two incompatible generations of `ui.native`:

1. a bounded JavaScript intent prototype in `apps/hepta-native/src/native.js` and
   `apps/hepta-native/src/shell-runtime.js`; and
2. a Rust desktop product implementation with a real window bootstrap,
   authenticated loopback gateway, final-use authority integration, durable
   operation journal, updater, platform adapters, packaging metadata, and
   qualification fixtures.

Keeping both generations active made source identity, capability claims, and
qualification receipts ambiguous. Historical commits also contained native
features that were not necessarily present in the current worktree.

## Decision

The Rust implementation is the sole canonical product implementation.

- The product bootstrap is `apps/hepta-native/src/main.rs::run`.
- The runtime boundary is `apps/hepta-native/src/runtime.rs`.
- The authenticated gateway is `codex-rs/hepta-native-gateway`.
- Final-use authority is owned by `codex-rs/hepta-contracts`.
- Bounded platform state is owned by `codex-rs/hepta-private-state` where the
  operating system requires it.
- JavaScript under `tools/ui-native-projections` is non-product tooling only. It
  generates and verifies documentation projections and qualification evidence;
  it is not a shell runtime and has no platform authority.

The retired JavaScript product entrypoints must not reappear:

- `apps/hepta-native/src/native.js`
- `apps/hepta-native/src/shell-runtime.js`

## Source and evidence identity

Historical implementation is not inherited automatically. A capability exists
only when all of the following are true for the candidate being evaluated:

1. the implementation file is present in the candidate worktree;
2. `apps/hepta-native/CURRENT_SOURCE.json` matches every declared native and
   integration source;
3. `docs/modules/ui.native/IMPLEMENTATION_MAP.json` resolves the operation to a
   current source symbol and test profile;
4. generated API, test, platform, and capability projections reproduce exactly;
5. an exact-head or deterministic synthetic-merge qualification receipt binds
   the source tree, workflow, dependency locks, toolchains, runner image, test
   manifest, artifact digest, and timestamp.

A merge commit, PR description, old receipt, tag, or historical branch is not
capability evidence for a different worktree.

## Product composition

The shell is one native process with one authenticated runtime session
incarnation at a time. Reconnect closes the previous backend session, clears the
presented view, advances the session generation supplied by the backend, and
reconciles durable pending operations.

Multiple windows are not admitted until they share one process-owned journal
and one explicitly linearized session owner. Multiple independent shell
processes are rejected by the product lock. Platform effects are linearized by
operation identity and durable journal state rather than by UI event ordering.

## Capability effects

Every platform effect is bound to:

- endpoint identity;
- session ID and generation;
- subject and operation IDs;
- displayed runtime revision;
- action and canonical payload digest;
- final-use binding digest; and
- signed grant digest.

The journal reserves the operation before dispatch. Terminal state is monotonic.
Exact duplicates return the prior receipt. Changed semantics under the same
operation identity are rejected. `Invoking` and `Indeterminate` records are
reconciled after restart and are never blindly replayed. An unavailable or
uncomposed authority fails closed.

## Updates

The updater is an independent boundary. It verifies signed metadata, expiry and
trust, current/predecessor identity, serializes update transitions, stages
before activation, confirms the installed target and running process, and
retains unresolved activation state across crashes. Rollback is allowed only to
the bound predecessor and must be confirmed. Unresolved or contradictory state
is quarantined.

Production signing keys, Apple notarization, Windows Authenticode, Linux
repository signing, promotion, and release authorization remain external
evidence gates and must never be synthesized by repository tests.

## Compatibility plan

The four former JavaScript intents map to Rust operations as follows:

| Retired intent | Canonical Rust operation |
| --- | --- |
| `connectRuntime` | `NativeShellRuntime::connect_runtime` |
| `renderRuntimeView` | `NativeShellRuntime::refresh_runtime_view` |
| `requestPlatformCapability` | `NativeShellRuntime::request_platform_capability` |
| `applyShellUpdate` | `UpdateManager::verify_and_stage` plus running-process confirmation |

No source-level JavaScript compatibility shim is provided. Callers must compose
the Rust product or the authenticated gateway protocol. Protocol compatibility
is negotiated through the signed endpoint manifest and versioned gateway
contract, not through an unversioned local wrapper.

## Consequences

- Rust toolchain and platform dependencies are required for product work.
- Documentation projections are generated from current source and checked with
  `npm ci`, `npm run lint`, `npm run typecheck`, and `npm test`.
- Repository-controlled qualification may prove source, package, recovery, and
  deterministic behavior.
- Physical accessibility, production signing, installation trust, performance
  acceptance, promotion, and release remain separately recorded gates.
