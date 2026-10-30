# Frozen bounded-delta memory results

Thirty fresh actual training runs are complete. The new mechanism quality gate **fails**; **0/8** prespecified function-family superiority gates pass.

The aggregate strict replay gate is **FAIL**: 11 of 135 conditions fail, confined to full_mass. This failure is retained without changing the frozen numerical tolerance.

The new candidate is a bounded residual-write memory inside the inherited learned key/value, content, boundary and fast/slow graph. Its deterministic orthogonal-filler and overwrite checks test a useful local mechanism; they do not imply learned long-sequence success. No frozen scientific source, seed, optimizer, selection rule or gate was changed after outcomes to improve these results.

## Protocol and retained evidence

The source baseline is `b1934022821f3fdafd509b43cf0c4d7d45852e6e`. The scientific freeze is `b9370f92ad4b1a0ba5ffb2c7eb68e05fdc965112a8994ba87830b1d70e7a4ad0`. All five arms have 6,217 learned parameters and identical initial parameter bytes within each task/seed. Seeds 61, 73 and 89 use the new data base 91,000,000, independently from earlier experiments. Each arm receives 600 Adam updates at batch32 and learning rate 0.003 on the same 8/16/32 curriculum. Each training length has 2,048 examples; validation and each evaluation condition have 512. Minimum validation32 cross entropy selects one of 12 candidates, never test or challenge scores.

All 360 candidate checkpoints, 30 selected checkpoints, 18,000 update records and 135 prediction/label archives are retained under `runs/`. The published lossless `raw_evidence.zip` and per-file SHA256 manifest restore that directory with `restore_evidence.py`; an actual new-directory restore and full hash validation passed before publication. The matrix has 576,000 training-example presentations; this is a tiny synthetic-task experiment, not all-modal model pretraining. `freshness.json` reports exact-input disjointness from the enumerated earlier constructed evaluation cohorts and current validation-length training. The old conditional confirmation cohort was not instantiated.

The original mass-ridge negative result and its unexecuted confirmation remain untouched. This experiment uses fresh paired fixed/mass baselines; those are not replacements for old reported outcomes.

## Main accuracy results

Values are means across the three fixed seeds, in percent. Per-seed values and dispersion are in `summary.json` and `results.json`.

| Arm | Memory128 | Memory512 | Retrieval128 | Retrieval512 |
| --- | ---: | ---: | ---: | ---: |
| full_delta | 99.28 | 46.22 | 100.00 | 87.76 |
| sigmoid_delta | 96.68 | 43.42 | 100.00 | 87.76 |
| c1_delta | 100.00 | 76.37 | 100.00 | 88.22 |
| full_fixed | 100.00 | 100.00 | 100.00 | 97.98 |
| full_mass | 100.00 | 75.26 | 100.00 | 99.41 |

The original conjunctive quality gate is evaluated without relaxation:

| Frozen check | Result |
| --- | --- |
| matrix_complete | PASS |
| numerical_and_replay | FAIL |
| memory128_every_seed | PASS |
| retrieval128_every_seed | PASS |
| memory512_improvement | FAIL |
| retrieval512_nonregression | FAIL |

## Capacity, overwrite and interference challenges

These use retrieval-trained checkpoints. None of these altered task conditions was a training target. The challenge reports do not replace the main gate. Capacity uses eight associations at length512; overwrite uses a later conflicting write to the queried key and labels the newest value at length128; interference increases filler noise from 0.05 to 0.2 at length128.

| Arm | Eight associations512 | Latest-write128 | Noisy filler128 |
| --- | ---: | ---: | ---: |
| full_delta | 84.96 | 92.12 | 56.51 |
| sigmoid_delta | 85.03 | 92.12 | 56.64 |
| c1_delta | 85.09 | 92.12 | 56.97 |
| full_fixed | 95.90 | 52.02 | 99.87 |
| full_mass | 97.66 | 50.26 | 68.23 |

The overwrite gain is a concrete challenge-specific benefit of the tested residual-write mechanism. The same gain also appears with the ordinary function controls, while long-memory, capacity and noisy-filler behavior deteriorate. It neither establishes a uniquely financial advantage nor passes the overall quality gate.

## Fixed function-family comparison

The three delta arms use identical state size, parameter tree, initialization, data and training opportunity. All use the same learned boundary coordinate. They are **not slope matched**: the risk derivative at zero is 0 for FullHX and ordinary C1, and 0.5 for sigmoid(2z). The financial nine-parameter template remains fixed; FullHX risk is the already documented C1 first-hit reinterpretation, not the original debt Put.

Intervals are the prespecified familywise Bonferroni95 paired-seed t intervals over eight comparisons (three seeds, df2). Their nominal coverage assumes approximately normal seed-level paired differences; three seeds give weak distributional evidence. A positive gate requires a lower interval bound above 0 and a mean gain of at least 1 percentage point. Wide intervals and negative gates do not establish equivalence. Zero-width intervals reflect identical observed paired scores in these three seeds, not a known zero population difference.

| Task/length | FullHX minus control | Mean difference pp | Family interval pp | Gate |
| --- | --- | ---: | ---: | --- |
| memory/test128 | sigmoid_delta | 2.60 | [-30.18, 35.39] | FAIL |
| memory/test128 | c1_delta | -0.72 | [-9.73, 8.30] | FAIL |
| memory/test512 | sigmoid_delta | 2.80 | [-27.66, 33.26] | FAIL |
| memory/test512 | c1_delta | -30.14 | [-315.13, 254.84] | FAIL |
| retrieval/test128 | sigmoid_delta | 0.00 | [0.00, 0.00] | FAIL |
| retrieval/test128 | c1_delta | 0.00 | [0.00, 0.00] | FAIL |
| retrieval/test512 | sigmoid_delta | 0.00 | [-1.42, 1.42] | FAIL |
| retrieval/test512 | c1_delta | -0.46 | [-5.02, 4.11] | FAIL |

## Mechanism and replay checks

All 12 local numerical/derivative checks passed before training. Maximum directional error was 5.78e-06. The orthogonal target read stayed exactly 0.999900009999 through 4,096 filler writes; same-key overwrite error was 0.00019997. Zero-write invariance is for reachable states inside the radius8 balls. Projection keeps each column bounded and is nonexpansive for fixed key/value/write; it is not globally C1 and does not guarantee gradients through learned keys.

The deliberate negative probes remain: correlated writes alter the old query, and overcomplete capacity degrades. The 24/32 random-key RMSEs were 0.4437/0.5921. Orthogonal preservation only holds while projection is inactive; an active column projection can alter that read.

Independent NumPy replay covered all 135 selected-checkpoint evaluation conditions. Audit status: **FAIL**. Maximum absolute logit difference was 0.00322; maximum metric difference was 1.44e-05. All 135 accuracies and label arrays match exactly. The failed conditions are full_mass; the stricter absolute-logit tolerance still applies even when the aggregate metrics agree. The audit also gates finite update/candidate/auxiliary values, actual parameter updates, the measured delta radius invariant, all 12 candidates, fixed step logs, validation-only selection, paired initialization and saved hashes. NumPy recurrence code is independent; financial table and dataset definitions are shared.

An additional independent, explicitly post hoc diagnosis examined only the worst exposed mass-ridge case: `memory_full_mass_seed61/test512`, example 318, output 2. The saved JAX FP32 logits reproduced bit for bit. The Gram/cross-statistic differences were 1.49e-08/1.34e-07; the ridge coefficient was 7.31e-05 and condition number 1171.0. On identical matrices, JAX, NumPy and an 80-digit Decimal solve agreed to 4.77e-13. Promoting the same saved-weight recurrence to FP64 reduced independent JAX/NumPy batch logit disagreement to 3.62e-12. This supports accumulated FP32 recurrence differences amplified by the small regularizer for this case. It does not replace any saved prediction, explain every failed case, or turn the failed frozen gate into a pass. See `replay_diagnosis.py` and `replay_diagnosis.json` for the perturbation identity and residual evidence.

## Costs and state

| Arm | Persistent state scalars/example | Logical fixed table bytes | Mean completed-run CPU s | Median warm batch32 logits ms |
| --- | ---: | ---: | ---: | ---: |
| full_delta | 1116 | 131128 | 39.86 | 4.400 |
| sigmoid_delta | 1116 | 131128 | 33.37 | 3.529 |
| c1_delta | 1116 | 0 | 31.41 | 3.408 |
| full_fixed | 1373 | 131128 | 53.91 | 4.737 |
| full_mass | 1373 | 131128 | 54.90 | 4.027 |

State scalar counts are not total memory bytes; parameters, optimizer, transient activations and dtype differences also matter. Table bytes count each arm's operator dependency; the inherited module eagerly loads a shared table even for C1, so the logical zero is not a measured process-residency saving. The delta arm avoids the old final Gram solve. Warm logits timings are for batch32, length32, shared CPU; they exclude compilation/metrics, have no exclusive-machine or GPU/energy interpretation, and are not Transformer/SNN comparisons.

The sum of completed-run scopes is 1280.69 CPU seconds and 1205.18 wall seconds. Independent replay adds 152.77 CPU seconds; exploratory diagnosis adds 10.27. Lossless archiving and an actual new-directory restore/check add 0.79 CPU seconds. Independent diagnosis of the worst mass-ridge replay case adds 11.29 CPU seconds. The measured CPU lower bound is 1455.81 seconds. The measured nonoverlapping wall lower bound, including initial validation and completed admission waits, is 1482.59 seconds. The potentially parallel diagnostic tail uses the larger branch wall duration, rather than adding overlapping intervals. Pretraining validation CPU, data/freshness/startup, summary/rendering/reporting repair and interrupted admission wait are unmeasured, explicitly null in `cost_ledger.json`. These figures must not be labeled full campaign cost. Compilation/optimizer/validation are nested within the completed-run scope and not added twice.

Shared cgroup pressure required the documented cache-aware operational admission amendment after one completed run. The interrupted process was waiting between runs, not updating a model; completed runs were not repeated. Scientific source hashes stayed fixed. `operational_handoff.json` records the brief overlap of the old waiting process and the new continuation.

## Exploratory diagnosis and scope

`diagnostic_plan.json` was written after early results were seen, so this is explicitly post hoc. `diagnosis.json` examines the first 64 test512 examples per run for filler-write activity and learned key overlap. Markers are used only to classify diagnostic tokens, never for model routing. The exposure proxy is not an exact error bound or a proof of a unique cause, and it did not alter models, selection, data or gates.

This package establishes a tested new memory recurrence, retained finite-capacity/interference limits and a reproducible small-task comparison. It does not establish a general trainable financial free boundary, exact continuous-time flow, all-modal encoder superiority, a replacement for Transformer/SNN backbones, or event-hardware energy savings. The new negative gates remain evidence for the next design decision.
