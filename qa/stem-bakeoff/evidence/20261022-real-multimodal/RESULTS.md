# Real multimodal private-Head experiment — 2026-10-22

The preregistered **gated** Head passed the source-pairing research screen on
real COCO images and human captions. This establishes a small, reproducible
learning loop over one frozen shared Encoder. It does not establish production
admission, superior gating, general semantic reasoning, stateful policy learning,
or target-device performance.

The actual training/evaluation ran from **05:11:44 to 05:14:31 UTC**. Its source
was `b280c643703277a72263de9bda9ffd46b8bd8dbf`; the complete source-file hashes are
embedded in the plan. Native CI repairs composed afterward do not alter those
research source files.

## Data and the locked comparison

- 384 original COCO val2017 photographs, each with an official human caption,
  original source URL, license, image digest and caption digest.
- Original-image splits: train 128, development 64, calibration 64, test 128.
- Each two-image block contributes two original positive pairs and two crossed
  negative pairs. Row counts are 256 / 128 / 128 / 256.
- Image and caption endpoints, exact image/pixel duplicates and near-duplicate
  images are checked across splits. The test has 64 distinct pair blocks.
- Each image and each caption occurs equally often with each label. Therefore a
  single-modality classifier has exactly balanced conflicting labels for each
  observed input. Its 50% accuracy is an intentional diagnostic of this pairing
  task, not a natural distribution estimate for all unimodal tasks.
- Text-only, image-only and text+image use the same frozen physical Encoder,
  feature width, train/development/calibration rows, optimizer grid and thread
  budget. Equal Encoder FLOPs are **not** claimed.
- The fixed feature transform is `[text, image, product, absolute difference,
cosine]`. The linear control is linear over this already interacting feature
  space. Each modality arm has both a linear and a gated private Head.
- Development raw NLL chooses among 200 / 1,000 / 3,000 optimizer steps.
  Calibration NLL alone selects temperature. The test cannot choose the model,
  threshold or primary reporting mode. All six selected Heads used 3,000 steps.

The task label means **original source pairing**, not a human-certified claim
that a crossed caption is semantically false. The cohort does not authenticate
all real-world entity independence or exclude foundation pretraining exposure.

## Held-out result

Confidence threshold is fixed at **0.70**. Accuracy and balanced accuracy are
equal on this balanced 256-row test. Risk is the error fraction among accepted
rows; it is undefined when no row is accepted.

| Arm          | Head           | Correct / 256 | Accuracy | Positive recall | Coverage | Accepted errors | Selective risk |     NLL |
| ------------ | -------------- | ------------: | -------: | --------------: | -------: | --------------: | -------------: | ------: |
| Text only    | Gated          |           128 |   50.00% |          50.78% |    0.00% |           0 / 0 |      Undefined | 0.69315 |
| Image only   | Gated          |           128 |   50.00% |          57.81% |    0.00% |           0 / 0 |      Undefined | 0.69315 |
| Text + image | Gated, primary |           251 |   98.05% |          97.66% |   99.61% |         5 / 255 |          1.96% | 0.16712 |
| Text + image | Linear control |           250 |   97.66% |          97.66% |   98.44% |         4 / 252 |          1.59% | 0.06053 |

The primary confusion matrix is TN=126, FP=2, FN=3, TP=125. Its balanced-accuracy
gain over either unimodal arm is **48.05 percentage points**, with a one-sided
95% pair-block bootstrap lower bound of **46.48 points**. Its selective-risk
upper bound from the same block bootstrap is **3.57%**. These are empirical
resampling diagnostics from 64 blocks, not authenticated population guarantees.

All preregistered research conditions passed: minimum sample/block counts,
balanced accuracy, positive recall, coverage, accepted count, selective risk,
bootstrap risk upper bound, joint gain, and each intervention's effect.

### What this says about gating

Gating adds **one correct row**, or 0.39 percentage points, over the linear
control. The paired bootstrap gain lower bound is **zero**. Its test NLL is
worse, despite slightly higher coverage. This run does not establish a reliable
advantage for the gated architecture. Keep the linear control as a serious
deployment candidate and test gating on a new preregistered task/cohort before
increasing its complexity.

The selected gated temperature is 0.25. Calibration was selected only on its own
split, on which the gated Head got 128/128 correct. Independent recomputation
shows test NLL worsening from 0.05582 before temperature scaling to 0.16712 after
it. The test result is retained without post-test temperature tuning.

## Minority and modality interventions

The fixed minority diagnostic retains all 128 negative rows and 32 positives
selected by the preregistered hash rule. The positive fraction is 20%; always
predicting the majority gives 80% accuracy. The frozen primary Head achieves
158/160 correct, **99.22% balanced accuracy**, **32/32 positive recall**,
159/160 coverage and 2/159 selective errors. This is a correlated subset of the
test, not another independent dataset. Its zero observed positive misses do not
prove zero population risk.

| Input to the same frozen gated Head                | Accuracy | Positive recall | Confidence coverage | Interpretation                                                     |
| -------------------------------------------------- | -------: | --------------: | ------------------: | ------------------------------------------------------------------ |
| Correct pairs                                      |   98.05% |          97.66% |              99.61% | Primary result                                                     |
| Image missing                                      |   50.00% |           0.00% |             100.00% | High-confidence negative predictions; no safe fallback established |
| Text missing                                       |   50.00% |           0.00% |             100.00% | High-confidence negative predictions; no safe fallback established |
| Images swapped within blocks, original labels kept |    1.95% |           1.56% |              99.61% | Pair sensitivity diagnostic                                        |
| Same swapped inputs, source-pair labels corrected  |   98.05% |          97.66% |              99.61% | Same input multiset consistency, not an independent replication    |

The missing-modality drop has a one-sided 95% paired bootstrap lower bound of
46.48 percentage points. The original-label swap drop is 96.09 points, with
lower bound 92.97 points. Swapping does not create an independently labeled
semantic test: here it reverses the source-pair labels by construction.

**The learned confidence threshold must not act as a missing-modality gate.**
Both missing-modality cases accept every row while making 128 errors. Any later
serving path must require the modalities for which its Head was validated or
route to an independently validated alternative. This experiment remains
`SHADOW_ONLY`, `DENY_ALL`, with production activation disabled.

A later, separate [presence-contract check](../20261022-presence-guard/README.md)
adds an explicit required-text/image research entry point. On these same saved
Heads it rejects all missing rows before a forward and preserves complete-row
predictions exactly. This input-contract regression does not alter the original
experiment or demonstrate native serving integration or missing-input robustness.

## Actual resource measurements

| Resource                                      |           Observed value | Scope                                                   |
| --------------------------------------------- | -----------------------: | ------------------------------------------------------- |
| Physical Encoder owners                       |                        1 | One loaded EG2 text/image owner                         |
| Loaded Encoder parameters                     |              438,760,448 | Measured loaded tensors, not the checkpoint name        |
| Encoder resident tensor bytes                 |            1,755,045,092 | Approximately 1.63 GiB; excludes process overhead       |
| Trainable Encoder parameters                  |                        0 | Actual tensor digest identical before/after encoding    |
| Model / vision forward calls                  |                384 / 192 | 192 caption batches and 192 image batches, batch size 2 |
| Feature bank tensors                          |          2,359,296 bytes | 384 text + 384 image vectors, each width 768            |
| Bank construction wall time                   |         1,739.18 seconds | Actual CPU encoding and integrity checks                |
| Bank process peak RSS                         |      3,299,008,512 bytes | Process lifetime peak                                   |
| Gated private Head trainable parameters       |                   33,814 | Task/gate/adapter only                                  |
| Linear private Head trainable parameters      |                    6,148 | Task classifier only                                    |
| Each Head resident parameters / bytes         |         52,258 / 209,032 | Full architecture, including untrained outputs          |
| All selection, evaluation and artifact checks |           166.54 seconds | Six selected Heads, all candidates included             |
| Head process peak RSS                         |        393,981,952 bytes | Separate process, Encoder not loaded                    |
| Primary Head API p50 / p95 / p99              | 0.548 / 0.772 / 1.005 ms | 1,000 batch-one calls after 20 warmups                  |

Head timings include identity hashing and feature copying, and exclude Encoder
forwards, queueing and target-device work. Raw latency samples are retained.
The environment has an eight-CPU quota, 8 GiB memory limit, no CUDA, and no energy
instrument. The run used four Torch threads. No energy or target-device claim is
made.

4096 such Head tensors would total **856,195,072 bytes** by arithmetic, plus the
single shared Encoder. This run did not allocate 4096 Heads or train 4096 distinct
tasks. The six actual trained artifacts and their exact weights are retained.

## Evidence and replay

- [summary.json](summary.json): compact machine-readable result and limitations.
- [report.json](report.json): complete generated report, all checks, intervals and
  the externally retained hashes for 77 experiment artifacts.
- [primary-predictions.json](primary-predictions.json): all 256 primary rows,
  including source/group/block IDs, labels, logits, probabilities and acceptance.
- [review-receipt.json](review-receipt.json): the exact workflow completion and
  artifact-index verifier applied locally to this run.
- [replay-receipt.json](replay-receipt.json): restoration and exact replay of all
  20 ledgers from six saved Heads and the frozen bank.
- [AUDIT.md](AUDIT.md) and [audit.json](audit.json): independent source, prediction,
  metric and interval checks, with the material interpretation limits.
- [independent-audit-replay.json](independent-audit-replay.json): the published
  standalone audit script reproduces every substantive original audit field.
- [archive-manifest.json](archive-manifest.json): every archive part and all 91
  member hashes and byte sizes.

The archive retains full research output, six tensor artifacts, 20 prediction
ledgers, all frozen features, forward receipts, source manifests, split rows and
the training log. Eleven parts keep every Git blob below the repository's
500 KiB limit. Original photos and model weights are reconstructed through the
pinned cohort/model builders; they are not duplicated in this evidence archive.

From the repository root, using the pinned research Python environment:

```bash
python qa/stem-bakeoff/multimodal_evidence.py \
  --directory qa/stem-bakeoff/evidence/20261022-real-multimodal \
  --manifest-sha256 2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e \
  --output /tmp/hepta-multimodal-review \
  --replay-heads
```

The output must be a new directory. Byte restoration needs only the Python
standard library; `--replay-heads` additionally needs the pinned NumPy/Torch
runtime. Replay checks the complete original plan and source identities, fixed
six-Head/twenty-ledger inventory, exact predictions and reported metrics. It
does not download the Encoder or repeat image encoding. The independent audit
also checks the original photos and source annotation data available during this
run; those checks have a different scope from archive replay.

`qa/stem-bakeoff/audit_multimodal_v1.py` performs that independent audit with
NumPy, PIL and Torch functional operations. It does not import the experiment
implementation. Its `--repo`, `--cohorts`, `--bank`, `--results` and `--output`
arguments relocate this exact retained experiment, whose report digest is
explicitly pinned. It requires the original photos and caption annotation JSON;
it does not require the Encoder checkpoint or additional training.

## Remaining closure conditions

| Item                                                   | Current result                                               | Required next evidence                                                                  |
| ------------------------------------------------------ | ------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| Real paired multimodal research loop                   | Passed the fixed research screen                             | New harder/independent task before broader semantic claims                              |
| Effective task learning and paired confidence coverage | Passed on this held-out cohort                               | Independent domain validation before production qualification                           |
| Gated benefit over linear                              | Not established                                              | Positive preregistered paired gain on new data, including calibration quality           |
| Missing-modality serving                               | Raw failure retained; separate research guard verified       | Enforce the validated contract in the actual serving path or validate a fallback        |
| Native trained-Head integration                        | Research artifacts retained; native equivalence not verified | Real driver, compatible artifact execution and numerical/identity parity                |
| Stateful/full policy learning                          | Not trained                                                  | Actual episodes, state transitions, actions, rewards/targets and independent evaluation |
| Target-device performance                              | Not measured                                                 | Named target hardware, real load, queue-inclusive p95/p99 and measured energy           |
| Final composed CI                                      | Pending applicable exact-source checks                       | Terminal success for the final source and required base/merge combinations              |
| Native dependency and Windows repairs                  | Full local dependency policy passed; source repairs composed | Real Bazel lock generation and original compiled/native checks on the combined source   |

The experiment cannot supply missing real episode data, target hardware or
pending CI outcomes. The corresponding qualification flags remain false.
