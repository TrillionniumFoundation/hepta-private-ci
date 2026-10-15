# System2: distinguish train capacity, score origin, and transfer

## Completed content study, not a queued job
Original source `847637f5f1f9057f7d2400acc054727de6cc8cab`, tree
`e1e1e6e2cd66f1e47feb0de676e63cce86491706`, run **38147248105** completed.
Artifact **11706235289**, 5,697,416 bytes, ZIP SHA256
`2d7d1058c724f79298b8ccd28c319629b929a842f2107301c3e1c1adef09bcea`.
All 49 manifest entries (50 files including SHA256SUMS) verified.
Full hosted discovery: **976 passed, 2 skipped, 978 total**. Original native
execution encoded 24 training questions, loaded/called no Reader, and took
53.176662604 seconds including its recorded preparation. Three content-study
cuts completed without failure, and all three remained rejected.

At cuts 16/32/48, admitted rows were 7/14/20; same-size pair opportunities were
3/6/11. Content pair question-macro scores were .333333/.430556/.314394.
Erased controls were .5, and both arms selected empty evidence on every row.
These set-pair scores are NOT Reader accuracy or the singleton metric below.

Saved weights reproduce the selected decisions locally; maximum score drift
against hosted float32 outputs was 5.960464477539063e-8 (declared tolerance 1e-6).
Only tensors/metadata are consumed; replay never executes archived Python.
A score replay is not a fresh training execution or independent observation.

## New bounded replay
Reuse `StemHead(kind="linear")`, `Features`, `TrainingCut` and the existing archive
validator. Only the 384-element readout weight changes. The 770-parameter Head's
null parameters and common readout bias stay frozen. No changes to StemHead's
default implementation, native NDU APIs, old runners or finite-tree solver.

The fixed top-four proposal supplies singleton hit/miss pairs. With
D = x_positive - x_negative and b = 1 - frozen_score_gap, fit
equal-question-weighted squared error plus **0.01 * ||w||^2**.
Compare zero-residual frozen, **96 full-batch SGD updates at 0.03**, exact ridge,
and ridge with residual-input content erased (native frozen logits preserved).
Both fitted methods optimize the SAME convex objective. Ridge uses a bounded
dual solve; final-cut factorization dimension is 35, not a 421M model.
The normal-equation residual checks this objective only, never semantic truth.

Raw and centered inspection share the SAME fitted weights. Centering subtracts
the mean learned residual over the query's permitted top-four proposal:
`score_i = frozen_i + residual_i - mean_proposal(residual)`.
This fixes a score-origin convention without changing evidence ranking.
No label chooses the origin and empty evidence remains an admissible decision.
It is NOT probability calibration and MUST NOT be passed off as an NDU
continuation value. Relative ranking losses do not establish terminal utility.

## Observed local cached-native result
The local source overlay uses CPU torch 2.10.0 and safetensors 0.7.0, with verbatim
repository dataclass and StemHead constructor/forward ports because the full
repository cannot be fetched in this network-isolated runtime. This is real
native-feature refitting, but NOT a full-repository hosted execution. The new CI
uses the complete repository and pinned torch 2.5.1. Source manifests/context
in each result distinguish these environments.

| Training cut | Rows / eligible | Frozen hits | SGD centered hits | Ridge centered hits | Ridge raw empty |
| --- | ---: | ---: | ---: | ---: | ---: |
| 16 | 7 / 3 | 1 | 2 | 3 | 7 |
| 32 | 14 / 6 | 3 | 3 | 6 | 14 |
| 48 | 20 / 11 | 6 | 6 | 11 | 20 |

Ridge singleton positive/negative ranking is 1.0 on the eligible TRAIN questions
at every cut. This shows finite-sample fitting capacity, not generalization.
Before score-origin adjustment those SAME weights choose null on every row.

On leave-one-source-family-out refits of the final TRAIN cut, centered ridge and
frozen each hit **6/20** questions. One new hit is offset by one lost hit in a
different family. Family-macro hit rate is **0.246667 ridge vs 0.28 frozen**;
singleton pair question macro is **0.727273 vs 0.734848**.
All nine no-pair-opportunity questions remain counted. Five recorded source
families are not 35 independent pair observations or 20 independent families.
Therefore the candidate remains `stop_no_cross_family_source_gain`.

The family split is disjoint in both recorded family AND source roots. Training
gets only that fold's rows; held-out labels are used only after fitting/freezing.
Nevertheless these are previously exposed training data and exploratory model
diagnostics, not untouched confirmation or an independent validation cohort.

Before this final controlled replay, loss-only recurrent and paired residual
gradient probes also failed to yield a robust decision gain. Their exploratory
plans and outputs are retained in the conversation evidence package, not hidden
as unsuccessful hyperparameter trials. No family-fold result tunes regularization.

## Execution and boundaries
The workflow retains full MemoryCell regression discovery, static diagnostics
and historical artifact audit. It now downloads the 5.70 MB saved-feature artifact
instead of the combined 376 MB model/data artifact. Dependency installation,
historical regression archives and original encoding are not free TCO.
No new Encoder, Reader, benchmark question or human review is manufactured.

Thirty-two conditions cover three capacity cuts and five held-out-family folds,
four methods each: eight frozen references, eight SGD fits, sixteen direct solves
(including erasure). Failures remain in the condition census. Model state files,
FP32 storage checks, source lineage, timing and objectives are retained.
Local tests: **95 passed**, including twenty additions. Full-repository regression
and the new exact-head hosted replay remain separate evidence. Local Ruff/just
are absent; no Rust source changed and no repository gate is waived.

```sh
export HEPTA_SYSTEM2_CONTENT_ARCHIVE=/path/to/system2-content-38147248105.zip
python -m unittest discover -s scripts/memory_cell -p 'test_system2*.py' -v
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/system2_linear_solver.py \
  "$HEPTA_SYSTEM2_CONTENT_ARCHIVE" /new/replay-output
```

Reader adequacy, source-to-answer entailment, cross-modal transfer, unseen-task
superiority, calibrated FBSDE utility and production acceptance remain unestablished.
The next scientific bottleneck is transfer-quality supervision and an independently
calibrated stop/continue value, not evidence that 384-dimensional features cannot
fit these training contrasts, and not a justification to duplicate large models.
