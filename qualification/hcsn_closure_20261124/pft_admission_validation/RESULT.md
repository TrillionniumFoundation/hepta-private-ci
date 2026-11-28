# Admission validation and capacity: first observation

Protocol: `3559730592d9d3b8fa1f87aa4084e7cebcb2f854`.
Frozen implementation: `24bab56ad9ce7f1158a35b7e2668cb0a0ff68010`.
Baseline source: `4686c861e54179690c4a668a356a4b0ce57639d5` (#7208).

## Measured receiver work and unchanged semantics

One actual new received TCP contribution invoked the complete validator and
NumPy eigvalsh twice on the baseline, once on the candidate. The complete
receipt and contribution digest were equal across these observations.
Fixture production, sender export and snapshot checks were outside this count;
their required integrity validation remains present.

The candidate suite passed 15/15 tests, with zero failures, errors or skips:
the twelve existing ledger/JSON/binary controls and three new controls.
Actual lost-ACK exit 71, same-database restart/replay and numerical assertions
passed. The existing crash hook only forwards the new optional keyword.
Malformed-body and negative-PSD requests remained explicit refusals without
mutation, not unknown delivery. Conflicting bytes, at-cap exact replay with
an obsolete head and six invalid explicit bound types retained their controls.
An uncapped caller was also observed to exceed the cap, as permitted by the
backward-compatible default; the next capped request refused that state.

## Original capacity defect retained

| Observation | Baseline | Candidate |
| --- | --- | --- |
| Complete receiver validation calls | 2 | 1 |
| Receiver eigvalsh calls | 2 | 1 |
| Shared-database clients | accepted / accepted | accepted / refused |
| Final revision at declared capacity one | 2 | 1 |
| Capacity invariant | **false** | true |

The baseline's actual receiver PIDs were 8 and 10;
the candidate's were 59 and 61.
Both pairs exited 0 without forced cleanup. Timing witnesses show both actual
reads/validations preceded A's commit, and B's request overlapped it. A's actual
acknowledged head equaled the independently precomputed head supplied by B.
The baseline retained two accepted rows: `baseline_capacity_passed=false`.
`expected_defect_reproduced=true` means that defect was observed, not that the
old capacity invariant passed.

These are two independent serial receiver processes sharing SQLite. Normal
four-peer experiments use separate databases. The result does not claim two
queued requests in one serial owner expose this race. The new cap is checked
inside the ledger's BEGIN IMMEDIATE and only constrains opted-in append calls;
it is not authenticated global policy against an uncapped external writer.

## Cost and evidence

Baseline outer wall: 0.767153748 seconds. Candidate outer wall: 6.744611040
seconds (candidate inner 6.510167583). Whole scope: 7.518340912 seconds, below
its registered 90-second cap; neither phase timed out. The phases perform
different control sets, so their walls are not a speed comparison. Measured
call reduction alone establishes no total CPU or training acceleration.

`attempt-1.tar.gz` retains 36 files with both exact executed source sets,
full first logs/results, overlapping-process witnesses, both receipts, frozen
protocol/dependencies, supervisor/budget, final source and AST comparison.
Archive: 69,104 bytes; SHA-256 `4e2f434043987965308f2b8b07cea1e7de1e867840e1801360966d98a60b0b48`.
Official just fmt and Ruff 0.15.13 completed afterward. All four changed ASTs
match their executed versions; the three existing modules also remain byte
identical to execution. No experiment was repeated after formatting.
The runtime observation is explicitly marked as post-run and does not assert
complete transitive closure. No original nine-parent replay, historical science
budget, optimizer step, DEV/final data or user trajectory was used.
