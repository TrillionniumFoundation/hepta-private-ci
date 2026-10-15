# P0 V7 — independent original-target Head optimizer replay (Draft, DENY_ALL)

**Exact additive parent:** Hepta P0 V6 Draft #2167 at
`0d9ed802787ee15b6e1663b4fe32d94c135bf8cc`.
No change to `main`, selected weights, inference Worker, original authority,
Evidence WAL, NDU, CNS, CAS/FinalUse or externally acting skill runtime.

## Actual scientific question

A complete cached-feature + saved-Head inference replay (V5) shows that saved
weights can reproduce *held prediction probabilities*. A second cold pretrained
Encoder forward on 12 predeclared inputs per model (V6) checks a small part of
the original frozen representation. Neither shows that the archived **trained**
Head actually resulted from the declared **original human-label 40-step SGD**.

V7 uses the V5 feature/safetensors evidence, V6 source-limited cold feature
receipt, original TRAIN/calibration material and the exact saved Head tensor
files. A **separate CPU-only CI job**, never given held labels or pretrained
checkpoint weights, independently initializes two small linear Heads using the
same registered seed, optimizes them on different admitted feature views with
identical original-target labels, and checks the archived final weights and
calibration temperatures. It does *not* import the original `fit_head` or
`fit_question_only` optimizer; the question/evidence task pairing is independently
reconstructed and cross-checked. Its first SGD step is additionally checked
against an independent NumPy cross-entropy gradient calculation, while all
40 actual updates are performed by new Torch SGD instances.

| Arm | Evidence training | Question-only training |
| --- | --- | --- |
| Encoder | One shared pinned frozen Encoder/feature file | Same Encoder, different question-only input |
| Head | `2*d+2`, d=384/384/256 | Same geometry and identical original initialized bytes |
| Training | 40 full-batch steps, lr=.1, original human TRAIN labels | Same 40 steps, labels, optimizer and source candidates |
| Calibration | Original human CAL only; fixed temperature grid | Same, independently recomputed |
| Test labels | **Unavailable** in this job | **Unavailable** in this job |

Original V5 and V6 source receipts must be present and valid; the job is a
**hard prerequisite** before separate score-only owner opens held labels.
No alternative pretrained checkpoint or other model owner is introduced.

## Source-first fail-closed protocol

- Require complete exact original fit/blind case identity, `DENY_ALL` prior
  V5/V6 receipts for all three encoder candidates, and the original V5 feature
  and four-Head safetensors byte/hash, tensor-shape and held-probability audits.
- Reconstruct TRAIN and CAL rows from original human labels only, with one
  independent pair-matching implementation (not the producing trainer helper).
  Reject changed source groups, duplicate pairs, unexpected result labels,
  changed sample counts/ordering or any mismatched seed, learning rate and
  initial frozen Head.
- Exact independent initial Torch RNG match is mandatory. Registered 40-step
  FP32-SGD final-state tolerance is `3e-5` maximum absolute component error
  across CPU instruction differences. The first-step independent analytic
  gradient is checked against the same tolerance; CAL temperature must be in
  the original candidate grid and within `2e-4` calibration CE of the minimum.
- Reproduce both *learned and frozen* Head lineages for each of Granite R2 97M,
  mmBERT-small and EmbeddingGemma 2 text. Report actual numerical error,
  training losses, work and CPU/RSS. A missing/failed original model or one
  of its two Heads rejects the complete three-model V7 report.
- It does not retrain Laya. Laya 421M stays a separate native frozen baseline
  and original four-model human-label scoring remains mandatory.
- The separate V7 result is write-once and uploaded independently with the
  source-bound P0 workflow. All authority flags remain false.

## Deliberate negative control — an observation V5/V6 can miss

The focused synthetic regression changes **one unprobed TRAIN-only frozen
feature row**, then updates its safetensors SHA and original manifest.
The V5 held-probability replay still succeeds because no held row was altered.
The V6 fixed 12-case cold sample likewise does not include that row. V7
recomputes the complete TRAIN SGD and **rejects** because the alleged trained
weight trajectory no longer matches the frozen source inputs. This is a
falsifiable mechanism/failure result on explicitly SYNTHETIC features; no actual
pretrained-model result or external independent source attestation follows.

## Reproduce locally

```bash
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_independent_training_replay_v7.py' -v
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_*.py' -q
PYTHONPATH=experiments/shared_stem_cell python -O -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_*.py' -q
```

An actual physical V7 replay must come from the exact hosted P0 workflow
`hepta-p0-multirc-semantic-four.yml`, after the successful real pretrained
source/Head/Encoder stages; local tests use original-sized but synthetic
features and genuinely run CPU Torch SGD. No downloaded pretrained weights or
human future evaluation scores are present in the local fixtures.

**Explicit exclusions:** no new real Granite/mmBERT/Gemma/Laya scores, no
full-feature cold provenance (V6 checks 12 per model), no optimizer execution
attestation, no signed model or human-label origin, no prospective future1/2/3,
OOD transfer certification, equal-quality total deployment cost, GPU/energy/p99,
NDU/FBSDE efficacy, multimodal generation, 4096-Cell production memory/WAL,
Compiled Skill Cell efficacy, automatic merge, Stem promotion or FinalUse grant.
An exact-head test/CI pass cannot silently remove these independent barriers.

## Development-failure disclosure

During local refactoring to remove dependence on the producing trainer's
question-pair helper, an intermediate test invocation failed with a Python
`NameError` (`matched_pairs` still referenced after its import was removed).
The reference was replaced with an independently reconstructed, checked
original/no-evidence pairing. The failed invocation was observed in the local
tool output but its raw stderr was not saved as a separate immutable file;
therefore it must **not** be described as an archived error artifact.
The final 230-test standard and optimized inventories were rerun end to end;
only those final successful complete invocations are reported as pass receipts.
