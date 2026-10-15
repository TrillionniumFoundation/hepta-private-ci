# System2: complete native execution, rejected all-empty policy

## Frozen generating evidence

This supersedes the initial queued status for run **38139194731**, not the
acceptance gates. Source: `aecde9ee5882879cfb2b34d98c241c44b752ef3e`;
tree: `25acf4de2b0e7fedae546a31276efa3e65be8e1f`.
Artifact **11703482865**, `hepta-system2-fbsde-research`, has ZIP SHA256
`80037375c44927f71e15dea508abb6ac3a2d5ccd03cefe2a5c21beedad37247e`.
The 14,166,767-byte archive contains 52 files; all 51 SHA256SUMS entries verify.

The hosted job finished successfully on 2026-10-11 at 13:20:52 UTC. All 28 new
mechanics tests passed. The complete Python discovery ran **931 tests: 929 passed,
2 explicitly skipped**, not 931 passing tests. The skipped historical-reader and
strict-repeatability integrations lacked their respective staged archives.
The new audit does not relabel those skips or the original answers.

All **768 planned policy executions succeeded**: 32 questions, eight arms, three
checkpoints. Reader controls contain 64 successful executions (32 no-evidence,
32 ordinary retrieval) and 64 unavailable human/critical-premise conditions.
Thus there are **832 successful Reader executions, not 896**. End-to-end native
runner time was 1491.015114732 seconds, including its recorded preparation and
training. The data are previously exposed development corpora.

## Why the current policy candidate is rejected

At EVERY checkpoint, `recurrent`, `tree_critic`, `ndu_deterministic`,
`fbsde_stochastic`, and `wrong_stitch_control` choose empty evidence on all 32
questions. Across their **480 executions**, the exact Reader identity/profile,
query digest, input-token digest, raw answer and generated-token digest equal the
corresponding no-evidence control. This is observed request/output equivalence,
not an inference from similar aggregate scores.

Last-checkpoint recorded diagnostic token-F1 means are:

| Arm | Scored / planned | Empty / planned | Conditional mean |
| --- | ---: | ---: | ---: |
| Frozen retrieval | 26 / 32 | 1 / 32 | 0.09712157078709871 |
| Linear Head | 26 / 32 | 10 / 32 | 0.09389250138155872 |
| Gated Head | 26 / 32 | 10 / 32 | 0.09389250138155872 |
| Each of the five advanced arms | 26 / 32 | 32 / 32 | 0.06262576080389845 |

Six unscored cases per arm remain unknown; they are not imputed as successful
answers. These are recorded diagnostic scores, not independent semantic QA
judgments. Full-planned F1 bounds are [0.0789112763, 0.2664112763] for frozen
retrieval and [0.0508834307, 0.2383834307] for each advanced arm. The final FBSDE
minus retrieval paired bound is [-0.2155278456, 0.1594721544] with six unknown
pairs. No significance claim is supported by these bounds.

There are **32 unique evaluation questions and five recorded source-family
groups**, not 768 independent samples. Checkpoint repetition and shared-family
questions do not increase the independent-family count.

The numerical negative control DOES detect its own faulty continuation: 960 of
1344 evaluated wrong-stitch paths across all checkpoints are nonconverged; their
terminal residual is zero while some interior backward residuals are nonzero.
However, none of those paths is selected. Correct finite-scenario solves and
wrong-boundary detection therefore do not establish a task-level causal benefit.
Avoid interpreting cheaper empty-evidence Reader prompts as FBSDE efficiency.

## Training opportunity defect and next controlled diagnostic

Reconstruction from the pinned sampler source and training dispositions gives
40 admitted rows at the final cut. With `row = rows[step % 40]` and subset size
`step % 4`, each question receives exactly one requested cardinality; **ten
questions are scheduled exclusively on the empty subset**. This is source/schedule
arithmetic, not a recovered observation of subset identities or labels. The
original run did not retain those subset-label traces. The defect is a plausible
contributor, NOT established as the only cause of all-empty decisions.

The new `system2_learning_probe.py` consumes the SAME Continuation, frozen
Features and TrainingCut through the EXISTING native runner. No production
runtime, Encoder copy, Reader, source owner or replacement default policy is
introduced. `--learning-preflight` runs a single `general` Cell at the fixed
16/32/48 train cuts. Each cut starts from fresh identical weights and compares:

1. The unchanged legacy sampler, 96 optimizer updates.
2. A shape-matched random sampler, 96 updates with two subset forwards each.
3. A source-hit/miss paired sampler, 96 updates with two subset forwards each.

The paired sampler visits both weak labels for each visited question and cycles
subset cardinalities by that question's visit count, not its global row index.
The random control uses the same question, proposal pool and pair of cardinalities
at every update, but samples subsets uniformly and uses their actual native
source-membership labels. Paired and random have identical model shapes, forward
counts, transition lengths and optimizer-update counts. Their actual latency is
still measured separately; legacy computation is NOT matched to the other two.
No useful-work padding or FLOP equivalence to a Reader call is claimed.

All admission checks finish before source-support label inspection. A missing
positive in the fixed top-four proposal is retained as no paired opportunity,
not silently relabeled as an unanswerable task. Hit/miss targets describe native
source membership only, not independent entailment or joint-premise sufficiency.

Before and after training, free argmax includes the empty path. A model can still
choose empty; no nonempty choice is forced to manufacture an improvement. Every
training update retains question/feature binding, actual subsets, actual labels,
predictions, loss and attempted work. Training failures quarantine partial weights
and retain their attempted records. These are train diagnostics, not held-out
model selection or Reader correctness.

## Execution boundary and reproduction

The dedicated push workflow now verifies/audits the immutable original archive,
runs ALL discovered MemoryCell tests, then executes four Reader conditions before
the single-Cell preflight. It no longer blindly repeats the rejected eight-arm
matrix. The preflight plan declares **zero policy attempts** and its summary keeps
`full_matrix_completed=false`. It does not relabel training probes as 768 fresh
policy answers. The historical eight-arm implementation remains unchanged and
accessible through the existing runner without the preflight flag.

```sh
export HEPTA_SYSTEM2_ORIGINAL_ARCHIVE=/path/to/original-system2.zip
python scripts/memory_cell/system2_native_receipt.py \
  "$HEPTA_SYSTEM2_ORIGINAL_ARCHIVE" /new/original-native-audit.json
python -m unittest discover -s scripts/memory_cell -p 'test_system2*.py' -v
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/system2_native_trial.py \
  /path/to/memory-inputs /path/to/pinned-ranker /new/preflight \
  --development --learning-preflight
```

Local continuation evidence: **51/51 tests passed**, including the real pinned
original archive audit, under torch 2.10.0+cpu. The new hosted preflight result must
be read from its own exact-head run; neither these local fixtures nor the original
run establishes that the new sampler improves native training or task answers.

Real human sufficient-evidence claims and independent answer judgments are still
missing. No author/model signature is substituted. Reader adequacy, unseen-task
superiority, true multimodal capability and production acceptance remain false.
