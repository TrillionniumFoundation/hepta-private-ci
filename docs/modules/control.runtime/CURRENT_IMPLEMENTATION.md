# control.runtime current implementation

> Generated from `MATURITY.json`. Do not hand-edit state claims in this file.

## Current claim boundary

`control.runtime` has a deterministic deny-all planner kernel, strict public input guards, a crash-bounded `PlannerStoreV1` source candidate, a generic source-level authority/executor/reconciliation coordinator, and one authenticated bounded read-only Agentd context caller. The Agentd caller now uses a canonical authenticated record set, a request/query/retrieval/ranker-bound delivery seal, final-use plan-receipt binding and a monotonic process-generation lease. It does **not** yet have a named global-planner product caller, selected production writer, independently admitted production authority consumer, production effect executor, production reconciler, activation, canary promotion or release.

| Subsystem | Current state | Product composition |
|---|---|---:|
| Planner kernel | `source_candidate_implemented` | no |
| Public planner guard | `source_candidate_implemented` | no |
| Planner store | `source_candidate_implemented_unqualified` | no |
| Planner execution coordinator | `source_candidate_implemented_not_product_composed` | no |
| Agentd read-only context caller | `source_composed_candidate_request_integrity_v2` | yes, bounded read-only scope |
| Global planner caller | `not_composed` | no |
| Organ host | `source_candidate_implemented` | no |
| Embodiment reference | `source_candidate_implemented_reference_only` | no |
| Authority consumer | `typed_port_and_validation_source_candidate_no_named_product_consumer` | no |
| Effect executor | `typed_port_and_signed_terminal_validation_source_candidate_no_named_product_executor` | no |
| Terminal reconciliation | `typed_port_and_signed_receipt_validation_source_candidate_no_named_product_reconciler` | no |

## Durable store controls

The source candidate implements a versioned self-validating image, exclusive writer lock, exact canonical bodies, typed evidence parent links, temp write, file and directory `fsync`, atomic replacement, indeterminate poisoning, crash failpoints, legacy digest-only migration, bounded retention compaction, monotonic backup restore, and externally anchored checkpoints. It remains unqualified and uncomposed until current exact-head and target-host evidence passes.

## Request-integrity controls

The bounded Agentd context path authenticates the exact owner cut and selected record set, binds owner/generation/query/limit/request/retrieval/ranker identity, seals the raw planner receipt, uses a bounded monotonic lease registry, and repeats owner-cut, content, retrieval, ranker and lease validation immediately before final use.

## Execution closure

`PlannerExecutionCoordinatorV1` consumes deny-all grant requests, calls an independent authority port, validates payload- and expiry-bound grants, persists request/grant/terminal evidence, stops on indeterminate outcomes, and accepts only signed reconciliation receipts. These are source contracts and fixtures, not named activated Agentd production ports.

## Qualification and governance

Current exact-head and synthetic-merge checks must pass for the final candidate. Independent semantic review, operator acceptance, activation, canary promotion and release remain externally governed and false. A branch name, generated file, or `IMPLEMENTATION_MAP.json` provenance field is not an exact-source execution receipt.
