# MEM-1: frozen task truth, 2026-11-08

This repair builds on `afa0638cc26792772830f1f9ec87bc154a20a430`
(PR #5373). The prior verifier accepted a probe whose answer and `expected`
were both changed from the frozen label 6 to 7. It also accepted an altered
prequential correctness flag. Neither mutation changed the frozen inputs.

The new independent auditor reconstructs the 24-source facts, owner changes,
revocation, scope and source exposure from the frozen MEM-1 v1 protocol. It
checks every query's truth, eligibility and error flags, and rejects malformed
or boolean-valued labels. It runs after the existing exact operation-roster
check. The cost, recovery, candidate-lineage and supplied-binary checks remain
part of the same verifier. Errors are retained and counted, not hidden.

## Observations

| Check | Observed result |
| --- | --- |
| Normal and optimized Python regression suite | 42 passed in each mode on Linux and native macOS |
| Retained dynamic campaign | 35 runs, 10,500 query records reverified |
| Retained stationary campaign | 35 runs, 10,500 query records reverified |
| Original evidence after read-only verification | Both complete file-tree digests unchanged |
| Two previously accepted mutations | Both rejected by the new auditor |
| Native formatting | `just fmt`, Ruff 0.15.13 format/check, whitespace check passed |
| Formatting versus tested code | Python ASTs equal; no local tests rerun after formatting |

The native validation was an exact-byte projection of the affected Python
package and pinned formatter scaffold, not a full workspace build. Linux replay
hashed the retained binary; it did not execute the binary or rerun training.
The native job was `1a1bc345968-138b0-de`. Its memory and control components
completed; a later unrelated VERIFY receipt-filename collision caused the
aggregate job to exit 1. Component receipts and the failed aggregate history
are kept separate rather than representing that job as a global pass.

## Interpretation and next gate

Scientific qualification remains **HOLD**, production adoption **NoUpdate**.
These checks establish truth and accounting consistency of the supplied
synthetic records. They do not authenticate original execution, prove retrieval
guards ran, exclude early access to supervision, or qualify native owners,
crash recovery and successor adoption. Cost accounting remains partial.

The earlier `0.45 versus 1.0` result specifically compares structured replay's
final two-constituent panel with exact-key RAG. It is not the accuracy of every
fast-memory arm and not a comparison against semantic LLM retrieval. No old
scientific result is changed by this repair.

## Reproduce

```sh
python3 -B -m unittest discover -s scripts/memory_cell_mem1 -p 'test_*.py' -v
python3 -B -O -m unittest discover -s scripts/memory_cell_mem1 -p 'test_*.py' -v
python3 scripts/memory_cell_mem1/verify_results.py RETAINED_CAMPAIGN --native RETAINED_BINARY
```

`local-replay/` contains before/after mutation and complete-readback receipts.
`native/` binds the exact tested and formatted source and original command logs.
The original campaign artifacts remain in their existing evidence package.
