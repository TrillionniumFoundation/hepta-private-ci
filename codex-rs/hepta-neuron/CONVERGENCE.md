# Neuron candidate content reconciliation (2026-09-25)

Continue existing Neuron PR #1004 on the current product-convergence integration
candidate #990, not a new closure branch. Original dirty worktrees were preserved;
they were not treated as fetched source truth.

## Exact predecessors

- Main: `a126987b84737dbc2ee2592442a314117bddb4a2`.
- Integration: `19426443d91ecd3a28df8d3184a6554350fca0e5`.
- Existing Neuron candidate: `3c80aa8b84a581bba9704992d6b1b59d72e0955f`.
- Integrated binary result-store slice: `c8d9ea1365795d8984c746957a0f3d5b15070ced`.
- Alternate result-store slice: `cfd7595ce`, ancestor of that Neuron candidate.

## Content decisions

Retain the integrated `FileNeuronOperationStore` and `operation_codec.rs` binary
format, full-config header, explicit capacity and completion records. Do not
replace them with the alternate `NeuronOperationStore` merely because it appeared
on the module branch. These candidate sidecars are not interchangeable formats.
A deployment that used the alternate unqualified format must retain its exact
binary/format or supply an explicit reviewed migration. No candidate bytes are
silently rewritten or reinterpreted as the other format.

Absorb the alternate candidate's historical-result query and full native-receipt
verification into the integrated runtime. `query_result` uses exact tick identity
and input digest. Canonical publication verifies the complete stored, completed
receipt. The independent native journal supplies error, saturation and sparsity;
the numerical tick must match the committed checkpoint input binding. Carry the
predecessor native receipt across in-memory V1 segment transitions without changing
on-disk V1 bytes. Preserve integrated store tests and add admission, result metadata
substitution and actual child-process recovery tests.

Retain the current protocol's precise predecessor error. The alternate protocol
hunk duplicated a later existing check and changed error classification; it is
superseded by current owner-plus-projection validation, not a second wire contract.
Keep the updated execution/journal/recovery guides from the integrated candidate;
older claims that segment continuation or the complete sidecar are absent are not
restored from the historical module branch.

Supersede `neuron-agentd-product-bootstrap.yml` and its encoded patch pieces with
explicit reviewed Agentd source. Old workflow run 36112987559 completed with
failure and is not this candidate's execution evidence. The applicator and patch
remain in Git parent history. No branch-writing patch applicator is needed for
this continuation. This is a content reconciliation, not an automatic merge,
release or independent review decision.

## Current boundary

The canonical Agentd library now invokes a long-lived durable Neuron owner through
an opaque shared invocation, with currentness/deadline/cancellation checks and
actual committed-state handoff to intuition. Its qualification feature backend
remains a deterministic test implementation, not a selected production model.

A concrete authenticated startup/input factory, selected feature backend and
deployment of the selected-artifact/calibration/OOD guard remain integration/deployment work.
Versioned V2/DecisionCell durable migration and actual base/organ/cell parameter
consumption remain implementation work. Target-host model measurements,
future-window retention/unlearning, independent review and operator acceptance
remain separate evidence gates. Execution records must bind actual source/merge
commits and retain failed attempts; this document is not a test-pass receipt.

## Concurrent integration advance

During this continuation the integration branch advanced from `19426443...` to
`6ca21fbd539ecadf52684b336215b6a81f14167d`. Its inference-control terminal-capacity,
checkpoint maintenance, native-host tests and lane evidence changes are retained.
There were no Neuron/Agentd source conflicts. Overlapping implementation-map
source-observation identities are regenerated from the reconciled tree instead
of selecting either earlier identity as current proof. This does not transfer
the earlier integration's test results onto the new dependency source.

## This continuation

The current continuation absorbs integration commit
`80891ea44b7e2fdfa347cae6dac055f36503eab5` into the existing Neuron candidate
`4d3e4e13f49596c2d5017b1e38055c26370a11ae`; source merge commit is
`57dd8a9de079041b01771c08aa491272ea0dd6fc`. Rust sources merged without conflicts.
Conflicting generated maps retain the newer integrated owner records, then rebind
only actual changed source. Detailed-design hashes are computed from merged files.

A new red/green regression exposed and repairs witness-capacity failure after
model execution and journal commit. All witness implementations explicitly admit
new anchors before work; completed history remains queryable at capacity.

The concrete Agentd selected-artifact guard now verifies real signed CURRENT,
independent selections, exact model manifest/weights and calibration/OOD summary
bytes tied to a non-circular execution profile. It reuses the existing artifact
owner and its publication lock. It is available through `into_selected_shared`;
it does not provide the still-missing authenticated CLI invocation factory or a
real inference-control feature backend, and does not assert V2 migration, Laya
activation or independently accepted empirical results.

The next integration advance `694eb1b7b4c0f50847ed50be8c54a22e3a81b122`
adds five cognitive result/caller-map changes on top of `80891ea44...`; merge
`b5c20ef1922bcfb627ea76251a60048c04a4aeef` retains them. The fetched source
candidate remains `4d3e4e13...`; independent review refs record both fetched heads
without overwriting an unrelated non-fast-forward local tracking ref.
