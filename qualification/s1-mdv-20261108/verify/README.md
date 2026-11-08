# VERIFY-1: bind decisions, check reports and interruption control flow

Publication parent: `a6b174fa26e0d4f4870266ed0f65d96cb4cb3c02` (PR #5351).
The tested base remains `0c81508e3cb9ea5c949c12a0c01c61c66e8d4df2`.
During publication the upstream branch gained a documentation-only commit.
Complete Git-tree comparison and an independent review confirm that only its
README and INTEGRATION changed; all other 11,218 leaves retain their exact
path, mode, type and blob identities. The derived publication projection keeps
both new documents and every tested source byte. No tests were rerun on the
new publication base; original test and format receipts retain their old base.
See `native/BASE_ADAPTATION.json`, `native/PUBLICATION_VALIDATION.json` and
`independent-review/publication-base-drift-review.json`.
The model extension is first imported byte-for-byte from the retained execution
capsule. That later source publication does not become the historical model
run's execution commit: its `source_commit` remains null. The original run and
independent audit remain bound by the archived source, assets and receipts at
`f25124815a9832af9b00652a4741d794a744df06`.

## Why this producer gate is needed

The earlier inference provenance gate accepted a recorded risk input of zero,
a check cost of -100 and a budget of -1. It tied assessments to model calls and
checks, but did not independently recompute the policy. The separate historical
auditor already checked the original decisions; this patch makes the producer
enforce those obligations on future output too.

The new gate reconstructs risk, declared cost, remaining budget, check/defer and
intervention identity from the frozen plan at every reached frontier. Its
rosters derive from the plan and recorded execution, not hardcoded counts.
It checks optional reports against the goal, checker, frontier and observed
state, and reconstructs effects, reconciliation, interruption and retry order.
Unknown and refuted reports remain valid evidence; they are not converted into
proof. A critic score still cannot grant final acceptance.

## Independent-review corrections

The first patch still accepted an optional report with an empty body, wrong
subject or wrong checked step. It also accepted deleting a final decision,
effect and check after falsely claiming an earlier interruption. Independent
mutation review reproduced both. R2 adds the report and control-flow checks,
with explicit missing-ACK reconciliation semantics and regression coverage.
The first patch and failed review remain retained as development history.

## Verification scope

The isolated model suite passes 33 tests in normal Python and 33 under `-O`.
The retained-readback suite passes 15 tests in each mode, covering the original
108 trajectories, 156 decisions and 1,966 operations. All five consumed input
file hashes remain unchanged. No model inference, training or host effects are
rerun. Those record counts describe the same original experiment, not new
independent cases.

A separate Linux source projection also combines the 48 existing phase1 tests
with the 33 model tests: all 81 pass in normal and optimized modes. Its 13
phase1 Python files were checked against the exact parent Git blobs. This is a
source compatibility check using Python 3.12.14 and NumPy 2.3.5; the existing
CI pins NumPy 2.4.2, so the local result does not claim the full remote CI
environment or its three-OS qualification. See `ci-projection/`.

The native R2 source and command results are recorded in `native/`. It uses a
fresh validation directory, preserving the initial native wrapper's receipt
filename collision and the first-patch review failure. The collision occurred
after its child replay had succeeded and before formatting; it is not a failed
model experiment. The next raw AST gate also stopped correctly: Ruff indented
two function docstrings. Both raw differences remain explicit in the retained
failure and format review. A separate review accepts only those two docstring
whitespace changes after applying `inspect.cleandoc` to legal docstrings; all
other AST fields and ordinary string constants must match. The raw AST result
is false, the docstring-normalized result is true, and source hashes bind both
tested and formatted versions. No tests are rerun after formatting. Validation
covers the affected Python package, not the full workspace.

`local-replay/changes-r2.patch` reconstructs the pre-format tested R2 source
against the mechanical capsule import. The independent format review retains
the complete tested-to-formatted text differences and hashes.

Original source binding correctly differs when a new auditor reads an old
run. The replay tests require that distinction; they do not rewrite old source
identity or turn the complete old summary into a claim of new-code execution.

## Reproduce

```sh
python3 -B -m unittest discover -s experiments/verification_cell_verify1 -t . -p 'test_model_*.py' -v
python3 -B -O -m unittest discover -s experiments/verification_cell_verify1 -t . -p 'test_model_*.py' -v
python3 -B -m experiments.verification_cell_verify1.test_model_decisions \
  --run-dir RETAINED_RUN_V2 --receipt /absolute/new/replay-receipt.json
```

The existing VERIFY workflow discovers all imported model tests and the new
gate tests. Local package projections, native validation and final-head Actions
have separate source identities and are reported separately.

Scientific qualification remains **HOLD**, adoption **NoUpdate**. The seven old
main arms all accepted 4/12 cases with zero accepted errors under mandatory
host readback. This patch does not establish critic superiority, calibrated
population risk, matched physical cost, native ownership or successor adoption.
