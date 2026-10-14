# E2 typed MemoryCell physical matched-budget test (SHADOW)

Research child of #1777. This is an additive diagnostic under existing HNMF,
Neuron, Learning Artifacts and Plasticity owners. It does not authorize a new
Memory OS, graph mutation, source writer, model selection or deployment.

## Precise hypothesis

Given one immutable FeatureMatrix (same frozen Stem/Tokenizer/preprocessing),
TRAIN-only binary evidence-relevance labels and a **precommitted** case-to-HNMF
functional-type inventory, do two type-trained Heads achieve more future-time
relevance/decision utility than two identically initialized and sized Heads
trained on the entire TRAIN set? Both two-Head arms train the same number of
physical optimizer steps, minibatch examples and FP32 parameters, and both
use one type-routed Head per inference. A single trained shared Head and a
never-trained frozen Head are descriptive, lower-cost controls; a swapped-type
route is a negative control. Type is metadata, not a gold-derived discriminator.

`type_inventory_digest` and `prediction_sha256` are integrity bindings, not
independent signatures. Before genuine evaluation, an external preregistration
owner must pin the type manifest and source/task population before any future
labels are revealed; a scorer external to the producer must open original
labels and verify authentic outcomes. The current synthetic tests do neither.

The experiment reuses `amcn_learning.FeatureMatrix` and
`experiments.shared_stem_cell.execution.Head/fit` rather than another model
loader or optimizer. It only trains detached CPU FP32 Heads. It makes no claim
that relevance scoring, even if improved, proves exact knowledge has been
stored in model weights; verified source-based Reader answers remain a distinct
next experiment.

## Actual experiment steps

1. Register seven allowed HNMF types; pick exactly two for the initial trial.
2. Verify exact frozen feature, scope/generation, source-family isolation,
   full case/type inventory and TRAIN-only labels. Both types require
   independent roots and positive/negative TRAIN examples.
3. Train paired `untyped_equal_budget` and `typed_equal_budget` Heads, each
   with two independent actual PyTorch AdamW optimizers. Assert equality of
   parameter bytes, optimizer steps and examples processed; retain the frozen
   original. Infer every non-TRAIN case in every arm (no per-arm omissions).
4. Seal output digests before scoring, then use `amcn_typed_score` with separate
   exact heldout labels to score all SELECT, FUTURE_A/B and RETENTION cases.
5. Record accuracy, Brier and paired source-family win/loss/tie. No
   unverified confidence interval or artificial future-window acceptance.
6. Independently compare against strong hybrid RAG and *original* Reader
   completions under matched budgets before claiming useful memory gain.

Training-only tensor fixtures demonstrate **real optimizer parameter changes**
with synthetic inputs, not real Encoder memory performance. `backend_profile`
identifies fixture vs externally supplied local-HF feature receipt; a SHA is
never an issuer signature. No effect/action permission is carried by any Cell.

Run with the existing AMCN dependencies and:

```bash
PYTHONPATH=.:qualification/amcn-v1 python3 -m unittest discover \
  -s qualification/amcn-v1 -p 'test_amcn_typed_*.py' -v
```

## Training-source withdrawal experiment

`amcn_typed_lineage.py` binds each actual Head tensor SHA to complete
TRAIN SourceWitness revision/digest records from the original AMCN
revocation contracts. Its four detached candidates differentiate the
shared-bank all-source dependency from the typed-head local-source
dependency. `test_amcn_typed_lineage.py` proves a revoked source
quarantines both unspecialized Heads but not an unrelated typed Head.
This is a **shadow revocation census**, not actual model unlearning,
authenticated source-issuer evidence, storage durability or
published Artifact selection. Missing witnesses fail closed.

## NO-GO beyond mechanics

Missing: independent source/type precommit, authenticated pretrained Encoder
forward, source-first Reader adequacy, genuine prospective future calendar
windows, independent task/citation adjudication, equal end-to-end system cost,
whole-lifecycle source revocation/retraining, independent NDU winner selection,
exact-head blocking-ci and owner-reviewed CNS/Control publication. `main`
remains unchanged. Keep this child PR Draft and production_accepted=false.

## Original LoCoMo negative result (2026-10-14, local-only)

Original publicly published source artifact: GitHub Actions artifact 11586991191,
ZIP SHA256 `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`,
LoCoMo source JSON SHA256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
The actual source archive was downloaded and byte-verified locally. It contains
10 conversation families and 1,986 published questions. A **source-first,
question-text-only** retrospective experiment selected 92 questions across
temporal/episodic and non-temporal/semantic heuristic types, built 1,472
top-16 question/evidence pairs, trained over 768 TRAIN candidates
(42 publisher-weak positives and 726 negatives), and independently opened
publisher-weak support for the 704 non-TRAIN pairs. Zero-hit source-first
shortlists remained in the denominator.

For this local diagnostic, features came from deterministic **96D hashed lexical
overlap**, not the archived pretrained Encoder. The candidate Heads really
executed PyTorch optimizer updates. Training was isolated from withheld
labels; the original uniform-sampling predictions were sealed before scoring.
A subsequent **post-hoc, exploratory** TRAIN-only binary-balanced sampler
repeated minority TRAIN rows only and used identical two-Head parameters,
optimizer/minibatch budgets and one-Head-per-query inference for typed vs
untyped. Weak publisher support hit@1:

| Historical split | BM25 | Uniform typed/untyped | Balanced typed/untyped | Any weak support in top16 |
| --- | ---: | ---: | ---: | ---: |
| SELECT (16 questions) | 4 | 0/0 | 3/4 | 10 |
| FUTURE_A (8 questions, 1 family) | 2 | 0/0 | 2/2 | 5 |
| FUTURE_B (8 questions, 1 family) | 3 | 0/0 | 3/2 | 7 |
| RETENTION (12 questions, 6 previously exposed families) | 5 | 0/0 | 4/3 | 7 |

This **fails** a convincing typed-memory superiority claim: all original
uniform-trained Heads selected zero annotated Top-1 supports, and the new
balanced variant has mixed gains/losses on tiny retrospective families.
Row-wise relevance accuracy is highly inflated by negatives; query-level
evidence hit and actual Reader answers are required. No strong hybrid RAG,
semantic answer completion, prospective calendar future, independent review,
compression benefit, or real parameter unlearning is established. The reported
future_a/future_b are historical partitions, **not time-forward observations**.

Local dependency-shim suite validates 35 physical training and negative
mechanism cases; this is NOT exact repository/hosted CI. A separate
local source bundle containing the LoCoMo source-first CLI, six safetensors
Head-bank persistence/readback code, 14 source/tamper regressions and
hosted original-archive workflow was prepared, but is **not part of this Git
commit** unless those paths are separately imported and checked at exact SHA.
Do not claim an unmerged local source was executed in GitHub Actions.
