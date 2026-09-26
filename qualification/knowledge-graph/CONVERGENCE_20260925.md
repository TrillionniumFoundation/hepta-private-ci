# Knowledge graph convergence execution record — 2026-09-25

## Candidate and claim boundary

Continuation: PR #990, `work/product-convergence-20260923`; no parallel KG rewrite.
Protected pre-existing dirty worktrees were not reset or overwritten.

The independently executed evidence below belongs to source
`834c6fc4f7f92a82fd24fa9adb21b0899ecfaf15`, base
`a126987b84737dbc2ee2592442a314117bddb4a2`, and deterministic merge
`bbe3a106d7fdb5f05621a6d08c5a9e5919fbd295`.
Both source and merge have tree `1d2bb66d3728db3cee542747f2ad12065a4513e5`.
Run: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36146175672
Merge job: 108108229293. Source job: 108108229789.

The subsequent compact-storage product-witness correction in this revision
has four passing independent SQLite fixture tests, but has NOT yet received
a passing real Agentd qualification receipt. Earlier evidence must not be
relabeled as an exact-head receipt for this later revision.

No production acceptance, activation, release, or incremental-writer promotion
is claimed. `productionImplementation` and `productExecutionProved` remain false.

## Implemented changes

- Compare migrated KG tables/indexes/triggers with fresh schema, while retaining
  independent legacy-source preservation and revoked-projection assertions.
- Clone only selected, temporally visible supports; retain exact omissions and
  canonical request/result digests. Work diagnostics are separate from receipts.
  Full-generation validation and complete matching scans remain necessary.
- Repair cancellation/shutdown test resource lifetime via the public durable
  SQLite owner shim; old fences remain rejected, successors use fresh grants.
- Make corruption injection atomic on one connection and retain corruption
  rejection. Remove panic-based constructors from relation integration tests.
- Add exact-clean-SHA target release measurement, workload/host binding, raw
  failure logs, RSS/DB/WAL, query work and concurrent reader/writer sampling.
- Keep independent native CI feedback after failed gates without changing the
  failing conclusion. Update maps and technical navigation without self-acceptance.
- Correct the Agentd product witness: G14 stores immutable revision facts plus
  `revision_facts_v1` witnesses, not complete copies in `kg_nodes/kg_edges`.
  Reconstruct the exact historical cut for every memory in the scope; preserve
  immutable source-citation, complete-count and generation/receipt assertions.

## Independent merge execution at 834c6fc4f7

| Check | Actual result |
|---|---|
| KG kernel | 21 passed |
| Prompt registry | 52 passed |
| Prompt optimizer | 32 passed |
| Memory library including oracle and recovery | 293 passed, 8 explicitly ignored |
| Explicit child-kill crash matrix | 1 passed |
| Default Agentd product E2E | 9 passed, 4 explicitly ignored |
| Qualification-witness Agentd E2E | 8 passed, 1 failed, 4 explicitly ignored |
| Full strict lint including Agentd | Failed with five diagnostics |
| Tracked source preservation | Passed |

Thus all 398 non-ignored native library tests passed in the independent merge
job. This does not turn the witness failure or strict lint failure green.
The source job also completed kernel, prompt, store/recovery and crash steps;
at the observation cut its PERF-LIBRARY step was still running. No completed
source-head performance or product result is inferred from the merge lane.

The witness failure was `current projection rows did not match their generation
receipt`. Its obsolete physical-table assumption is corrected in this revision.
The new SQL fixture independently covers multiple memories, correction, forget,
future-generation exclusion, unexpected physical facts, missing/wrong storage
witnesses and noncurrent request identities. These fixtures do not replace E2E.

Strict-lint diagnostics at the measured candidate remain in Agentd:
`plasticity_learning_producer.rs` retained handle and unused submission methods;
`state.rs` unused plasticity producer entry points;
`cognitive_context.rs::revalidate_with_retrieval_context` (10 arguments);
`plasticity_host.rs::propose_agentd_plasticity_v1` (9 arguments).
No visibility widening, dummy call, or lint allow-list was added to hide these.
The global technical-health observation also reports stale source inventory;
its existing owner gate remains separate and was not weakened.

## Local host measurement: failed qualification, not a latency receipt

A release attempt at source `768687844e8d3eb98dd59b14b55bf88b257dd265`
used the full 256-mutation pilot. It exceeded the existing 60-second nextest
watchdog and produced no accepted final performance receipt. Progress records:
16 writes at 9,818 ms; 32 writes at 30,325 ms. These are elapsed progress samples,
NOT p95/p99 values or a target SLA. The declared full workload was not reduced
and the watchdog was not relaxed to turn this failure into a pass.

Host: authorized Linux desktop, dual Xeon E5-2673 v3, 48 logical CPUs and about
125 GiB RAM. Concurrent work and high I/O pressure were observed. A separate
runtime.codex task reused the Cargo target directory; potentially contaminated
local Agentd results were not accepted as exact-candidate evidence. Only this
KG session's blocked archive process tree was stopped, never the other task.
Independent GitHub merge results above are the stronger evidence.

Local logs and protected worktrees remain at
`/tmp/hepta-kg-converge-20260925-eG8MHI/` on the authorized desktop, including
`logs/target-host.log`, `logs/final-native.log`, `logs/final-strict.log`,
`logs/ci-834-merge-direct.log`, and `logs/archive-blocked.json`.

## Remaining acceptance gates

1. Re-execute the real qualification-witness E2E on this corrected source and
   its current deterministic merge; four SQL tests alone are insufficient.
2. Resolve the actual Agentd strict-lint/product-composition diagnostics without
   silencing missing consumers or loosening the gate; synchronize global inventory.
3. Finish the full target-host release workload on an isolated build/execution
   path and produce complete latency/resource/contention evidence.
4. Retain full rebuild as selected writer. Promote localized incremental writes
   only after independent equivalence and measured end-to-end target benefit.

Current status: implemented and partly execution-qualified; not production accepted.
