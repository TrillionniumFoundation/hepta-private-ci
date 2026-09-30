# `learning.operator` authoritative admission contract

[`STATUS.json`](STATUS.json) is the canonical machine-readable status source.
This document defines the default admission semantics; it does not independently
assert mutable completion state. Exact candidate and workflow identities live in
the qualification-generated readiness manifest.

The default admission components use the existing ledger owner, evaluator,
selector, artifact store and Agentd host. The generic shadow coordinator is
implemented, but its real owner-port adapters and runtime caller remain
repository integration work. It creates no additional authority.
Repository qualification can establish exact-source engineering and protocol
evidence, while scientific efficacy, target-host capacity, operator acceptance,
canary, promotion, activation and release remain external. **Activation remains
false.**

## Canonical identity

Callers supply semantic values, not a value plus a caller-authored digest.
`TrainingProfileV1` binds objective, sensor core, dataset generation, minimum
samples per cell, maximum error and runtime limits. `WorldModelProfileV1` binds
objective, sensor core, dataset generation, minimum support, one-step and
multistep calibration limits, OOD false acceptance, drift and runtime limits.
Both derive profile and runtime digests internally.

The default crate root exposes an explicit reviewed allowlist. Raw structural
fitters and caller-authored V2 verification inputs are available only through
the non-default `qualification-unverified-input` feature and the
`compatibility` namespace. Independent consumer compilation proves that default
callers cannot import raw fitters, compatibility inputs, publish or activation
ports.

## Sensor-core qualification identity

`build_sensor_core_qualified_v1` returns
`QualifiedSensorCoreBuildReceiptV1`. The receipt exposes
`selection_mode=exact|reduced`, binds the deterministic reduction algorithm
identity and working-set limits, and includes the underlying bounded work
receipt. Qualification verifies this public receipt and executable behavior; it
does not scan private function names.

## Single-use final-use progression

| State | Concrete representation | Required property |
|---|---|---|
| Canonical profile | `TrainingProfileV1` / `WorldModelProfileV1` | Complete semantic field set, sensor representation and internally derived identity. |
| Owner-authenticated source | `DatasetSnapshotReceiptV3` plus signed freeze/row evidence | Exact active source set, authority epoch, objective and row semantics. |
| Current capability issue | `FinalUseFenceV1` + `FinalUseWitnessV1` | Ledger head, dataset frontier, generation, authority epoch, stop epoch and exclusive absolute deadline match; issuance time is retained. |
| Single-use capability | `FinalUseTabularCapabilityV1` / `FinalUseWorldModelCapabilityV1` | Opaque, non-`Clone`, owner-borrowed capability. |
| Current immediately before fit | `fit_*_final_use_v1` | Durable owner and ledger membership revalidated; stop, deadline, clock and cancellation checked. |
| Immutable candidate | `FinalUse*CandidateV1` | Artifact/profile/generation identity remains canonical. |
| Current immediately before handoff | second owner/currentness verification | A stale generation or revoked source cannot be selected or persisted. |
| Independently selected read-only artifact | `OpaquePinnedTabularArtifactV1` / `OpaquePinnedWorldModelV1` | Selection, trust, registry, authority and stop epochs are exact. |
| Immutable payload load | `LoadedTabularOperatorV2` | Full artifact, producer, schema, profile, trust, registry and authority pin verified once. |
| Selected prediction | `SelectedTabularOperatorV1` / `OpaquePinnedWorldModelV1` | Selection time window checked at every prediction; host refreshes live owner witnesses separately. |

The absolute deadline is exclusive: issue, use or handoff observed exactly at
the deadline fails closed. A witness observed before retained capability
issuance is a clock regression. The retained monotonic fit context also checks
issuance time plus real elapsed work and final cancellation; stale supplied
timestamps cannot extend the absolute deadline.

`WorkControlV1` is a cloneable monotonic cancellation token. Synchronous
resource-metered loops explicitly install it. Any worker-thread or blocking-pool
implementation must explicitly propagate and install the same token; ambient
thread-local state is not treated as cross-thread propagation.

## Shadow coordination contract

Agentd exposes `coordinate_learning_operator_shadow_v1`. Its legal sequence,
when a host supplies the corresponding owner ports, is:

```text
freeze training → derive canonical profile → final-use fit
→ freeze independent future window → independent evaluation
→ independent selection → create-only persistence
→ fresh-process LoadedTabularOperatorV2 load → shadow observation
→ currentness/revocation check → exact predecessor rollback
```

The coordinator currently has fixture-port state-machine tests. Signed component
E2E exercises owners and the evaluated ranker separately; a real-port coordinator
E2E and default runtime caller are still required.

The coordinator has no publish, canary or activate port. A healthy current
candidate ends as `QualifiedAndRolledBack`; a revoked candidate ends as
`RevokedAndRolledBack`; load, shadow or currentness failures end as
`RejectedAndRolledBack`. Failure to reopen the exact predecessor is terminal. Unknown persistence and
unverified cleanup retain recovery identity instead of returning a completed
terminal outcome. Cleanup of a verified persisted object remains mandatory after
work expiry; the host clock and receipt expiry are checked around each port.

## Compatibility and product use

Product code receives only an opaque selected artifact and complete V2 pin,
never a raw fit plan, mutable proof structure or caller-authored digest bundle.
Unsupported cells abstain. The host must observe registry, trust, clock, authority, stop or revocation
movement at each final use and invalidate the candidate. Immutable predictors and
static selection tokens cannot observe those later owner events independently.
`LoadedTabularOperatorV2` verifies immutable bytes/pin identity once; selected
wrappers additionally enforce their selection time window, while the evaluated
Agentd ranker obtains current owner witnesses for every use.

Legacy V1 read-only types that remain in the explicit default allowlist are
limited to existing owner-bound adapters; no raw fitter is available by default.
Their removal requires an independently reviewed consumer migration rather than
a wildcard export change.

## Qualification and readiness

The authoritative workflow records each required stage as `passed`, `failed` or
`not_run`. A documentation failure does not suppress independent compile, test,
mutation, coverage or performance diagnostics. The single readiness manifest
binds source head, frozen source, observation head, base, deterministic merge,
GitHub merge, workflow, run attempt, runner, target, lockfile, toolchain,
test-set, implementation-map, documentation, source tree and all artifacts.

Any failed, cancelled, skipped, missing or not-run required stage forces:

```text
mergeReady = false
productionQualified = false
```

Even when every repository stage passes, `productionQualified` remains false
until external scientific, target-host and operational gates are independently
issued. The real post-merge `main` SHA reruns qualification; PR-head evidence is
not reused.
