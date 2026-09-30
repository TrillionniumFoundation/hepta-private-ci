# `learning.operator` authoritative admission contract

This document defines the current default qualification path. It composes the
existing ledger owner, evaluator, selector, artifact store and Agentd host; it
does not create another authority. Repository qualification can establish
source-bound engineering evidence, while independent scientific acceptance,
promotion, activation and release remain external. **Production activation
remains false.**

## Canonical identity

Callers supply semantic values, not a value plus a caller-authored digest.
`TrainingProfileV1` binds objective, sensor core, dataset generation, minimum
samples per cell, maximum error and runtime limits. `WorldModelProfileV1` binds
objective, dataset generation, minimum support, one-step and multistep
calibration limits, OOD false-acceptance, drift and runtime limits. Both derive
their profile and runtime digests internally.

Raw V1/V2 structural fitters remain available only through the non-default
`qualification-unverified-input` feature. They are compatibility fixtures, not
final-use authority.

## Single-use final-use state progression

| State | Concrete representation | Required property |
|---|---|---|
| Canonical profile | `TrainingProfileV1` / `WorldModelProfileV1` | Complete semantic field set and internally derived identity. |
| Owner-authenticated source | `DatasetSnapshotReceiptV3` plus signed freeze/row evidence | Exact active source set, authority epoch, objective and row semantics. |
| Current capability issue | `FinalUseFenceV1` + `FinalUseWitnessV1` | Ledger head, dataset frontier, generation, authority epoch, stop epoch and absolute deadline all match. |
| Single-use capability | `FinalUseTabularCapabilityV1` / `FinalUseWorldModelCapabilityV1` | Opaque, non-`Clone`, owner-borrowed capability. |
| Current immediately before fit | `fit_*_final_use_v1` | Owner snapshot and ledger membership revalidated; stop, deadline and cancellation checked. |
| Immutable candidate | `FinalUse*CandidateV1` | Artifact/profile/generation identity remains canonical. |
| Current immediately before selection | second owner/currentness verification | A fit cannot be published from a stale generation or revoked source. |
| Independently selected read-only artifact | `OpaquePinnedTabularArtifactV1` / `OpaquePinnedWorldModelV1` | Selection, trust, registry, authority and stop epochs are exact. |

`WorkControlV1` supplies cooperative cancellation to every resource-metered
long loop. `OperatorResourceBudgetV1` supplies absolute operation, resident-byte
and elapsed-time ceilings.

## Default host loop

Agentd exposes `coordinate_learning_operator_shadow_v1`. Its only legal
sequence is:

```text
freeze training → derive → final-use fit → freeze independent future window
→ independent evaluation → independent selection → create-only persistence
→ fresh-process load → shadow observation → currentness/revocation check
→ exact predecessor rollback
```

The coordinator has no publish, canary or activate port. A healthy current
candidate ends as `QualifiedAndRolledBack`; a revoked candidate ends as
`RevokedAndRolledBack`; load, shadow or currentness failures end as
`RejectedAndRolledBack`. Failure to reopen the exact predecessor is terminal.

## Compatibility and product use

`LoadedTabularOperatorV2` remains the validated read-only loader. Product code
receives only an opaque selected artifact, never a raw fit plan, mutable proof
structure or caller-authored digest bundle. Unsupported cells abstain. Registry,
trust or revocation movement invalidates the loaded candidate and requires an
explicit reload.

## Claim boundary

Passing repository qualification means the exact source and deterministic
synthetic merge compiled and passed the declared tests, mutation suite,
coverage threshold and bounded performance matrix. It does not establish
future-window efficacy, target-host acceptance, canary acceptance, promotion,
activation or release; activation remains false.
