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

## NO-GO beyond mechanics

Missing: independent source/type precommit, authenticated pretrained Encoder
forward, source-first Reader adequacy, genuine prospective future calendar
windows, independent task/citation adjudication, equal end-to-end system cost,
whole-lifecycle source revocation/retraining, independent NDU winner selection,
exact-head blocking-ci and owner-reviewed CNS/Control publication. `main`
remains unchanged. Keep this child PR Draft and production_accepted=false.
