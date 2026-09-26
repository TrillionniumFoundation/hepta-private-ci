# control.runtime current implementation

> Generated from `MATURITY.json`. Do not hand-edit state claims in this file.

## Current claim boundary

`control.runtime` has a deterministic deny-all planner kernel, strict public input guards, a crash-bounded `PlannerStoreV1` source candidate, and one authenticated bounded read-only Agentd context caller. It does **not** yet have a named global-planner product caller, production writer, independently admitted authority consumer, effect executor, terminal reconciler, activation, canary promotion, or release.

| Subsystem | Current state | Product composition |
|---|---|---:|
| Planner kernel | `source_candidate_implemented` | no |
| Public planner guard | `source_candidate_implemented` | no |
| Planner store | `source_candidate_implemented_unqualified` | no |
| Agentd read-only context caller | `source_composed_candidate` | yes, bounded read-only scope |
| Global planner caller | `not_composed` | no |
| Organ host | `source_candidate_implemented` | no |
| Embodiment reference | `source_candidate_implemented_reference_only` | no |
| Authority consumer | `not_composed` | no |
| Effect executor | `not_composed` | no |
| Terminal reconciliation | `not_composed` | no |

## Durable store controls

The source candidate implements a versioned self-validating image, exclusive writer lock, exact canonical bodies, typed evidence parent links, temp write, file and directory `fsync`, atomic replacement, indeterminate poisoning, crash failpoints, legacy digest-only migration, bounded retention compaction, monotonic backup restore, and externally anchored checkpoints. It remains unqualified and uncomposed until current exact-head and target-host evidence passes.

## Remaining request-integrity work

The existing Agentd read-only caller must still bind and revalidate the planner receipt at final use, derive observations from a canonical authenticated read instead of a caller-supplied scalar count, bind request/query/retrieval/ranker identity, and use a declared monotonic lease domain.

## Qualification and governance

All current candidate checks are pending for the exact Git candidate. Independent semantic review, operator acceptance, activation, canary promotion and release remain externally governed and false. A branch name, this generated file, or an `IMPLEMENTATION_MAP.json` source-base field is not an exact-source receipt.
