# control.runtime current implementation

> Generated from `MATURITY.json`. Do not hand-edit state claims in this file.

## Current claim boundary

The branch contains a deterministic deny-all planner, bounded public guards, an owner-local durable store candidate, an execution coordinator over owner-supplied ports, and a bounded read-only Agentd context caller. Source composition, exact-source execution, target-host qualification, independent acceptance and activation are separate facts. No named global-planner production caller, independently admitted production writer, production effect executor or production reconciler is established by this document.

| Subsystem | Current state | Product composition |
|---|---|---:|
| Planner kernel | `source_candidate_implemented` | no |
| Public planner guard | `source_candidate_implemented` | no |
| Planner store | `source_candidate_implemented_unqualified` | no |
| Planner execution coordinator | `source_candidate_implemented_not_product_composed` | no |
| Agentd read-only context caller | `source_composed_candidate_request_integrity_v2` | yes, bounded read-only source path; not activation |
| Global planner caller | `not_composed` | no |
| Organ host | `source_candidate_implemented` | no |
| Embodiment reference | `source_candidate_implemented_reference_only` | no |
| Authority consumer | `typed_port_and_validation_source_candidate_no_named_product_consumer` | no |
| Effect executor | `typed_port_and_signed_terminal_validation_source_candidate_no_named_product_executor` | no |
| Terminal reconciliation | `typed_port_and_signed_receipt_validation_source_candidate_no_named_product_reconciler` | no |

## Durable store controls and limits

`PlannerStoreV1` preserves bounded bodies and their content checksums in a versioned image, with an exclusive writer lock, atomic whole-image replacement, file/directory sync, poisoned indeterminate handles and reopen validation. Whole-image replacement is not append-log last-complete-frame recovery. Stored body coverage is not semantic decoding. An `external_anchor_digest` is an evidence reference, not an independently verified non-regressing anchor. Production composition still requires the semantic owner codec, independent durable anchor and target-host crash/restore qualification.

## Request-integrity controls

The candidate Agentd path retains request/query/retrieval/ranker binding, a final-use delivery seal and a monotonic process-generation lease. Public planner checks reject extra owners, duplicate payloads, oversized raw collections and effect-bearing abstention. Owner age and clock monotonicity are rechecked at preparation, finalization and grant-request construction. Journal raw append and reopen use the same decision/selection/revocation state machine; valid hashes do not excuse illegal history. These are source-level statements until exact-candidate tests pass.

## Execution closure and signature boundary

`PlannerExecutionCoordinatorV1` records intent before owner-port calls, binds requests/grants/payloads, prevents redispatch of recorded requests and discovers reconciliation work after restart. A `signature_digest` in an owner-port projection is not a cryptographic signature verification. Actual authority, executor and reconciler adapters must independently authenticate complete signed bodies, pin identities and recheck current revocation. Those named production integrations and terminal-result channels remain open; planner output remains deny-all.

## Qualification and governance

Use `.github/workflows/hepta-control-runtime-exact.yml` for isolated NDU, control-plane and Agentd source-head/synthetic-merge checks. Evidence must bind source, integration base, executed tree, run ID and run attempt, with every command exit code and output digest. Missing, skipped, queued or failed commands are not passes; a historical same-SHA artifact without matching run-attempt provenance is insufficient. The workflow does not itself install a branch-protection requirement. Independent semantic review, operator acceptance, activation, real canary promotion and release remain false pending independent evidence.
