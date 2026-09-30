# knowledge.graph durable-writer selection — 2026-09-27

Fixed comparison base: `a126987b84737dbc2ee2592442a314117bddb4a2`.
Candidate branch: `work/kg-abc-execution-20260927` (PR #1110).

## Decision

Retain the bounded complete canonical rebuild in `CognitiveStore::refresh_scope_projection_tx` as the durable product writer. Do not promote `apply_incremental_delta` to the SQLite mutation path in this candidate.

## Evidence and rationale

- Full and incremental kernel paths share canonicalization and are checked for semantic equivalence; the incremental path remains an independent oracle/reference capability.
- `revision_facts_v1` already removes per-generation full physical node/edge duplication. This storage improvement does not imply that incremental computation is selected.
- Complete rebuild keeps source-cut observation, predecessor publication, semantic receipt insertion and current-pointer CAS in one auditable transaction. Crash/reopen and deletion tests target that exact boundary.
- The hosted-CI workload measures the selected writer, indexed product reads, contention, reopen, storage and memory. It is a regression profile, not evidence from a preselected production CPU and storage device.
- No exact target-host A/B comparison currently demonstrates that a durable localized writer has a material benefit after accounting for recovery, correction, deletion, support-lineage and publication-chain costs.

## Promotion gate

A later promotion requires a separately reviewed durable incremental transaction design; identical generation and publication digests for the same complete source cuts; correction, final-support deletion, crash-window and anti-resurrection parity; bounded recovery and reconciliation; and measurements on a named target CPU/storage profile using predeclared latency, memory and storage budgets. The comparison must include preparation, validation, index maintenance and fallback costs, not only an in-memory delta microbenchmark.

This decision grants no independent acceptance, activation, merge, promotion or release authority.
