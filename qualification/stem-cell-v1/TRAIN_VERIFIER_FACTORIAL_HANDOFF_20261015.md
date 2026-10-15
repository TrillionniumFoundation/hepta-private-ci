# Hepta Group: 2 × 2 terminal evidence × TRAIN verifier factorial

Date: 2026-10-15. **RESEARCH ONLY / DRAFT / SHADOW / DENY_ALL**.
Frozen parent: PR #2359 `research/group-prefix-terminal-evidence-v1-20261015@8bcfe04182eab73a4d368c2f7d0dd48af02f975b`.

## Motivation and exact intervention

The earlier pretrained Granite97 Group studies did **not** demonstrate
a recurrent or native-NDU reasoning advantage. Prior TRAIN-only Verifier
callbacks also returned guess-dependent correctness/family status. That
status can reveal answer quality during fitting; it is not evidence that
a learned Core can independently compose public premises.

This branch implements a preregistered **2 × 2** intervention:

| Arm | Intermediate TRAIN final-label CE | Guess-dependent TRAIN Verifier callback |
| --- | --- | --- |
| `legacy_oracle` | existing legacy every-step labels | on |
| `legacy_no_verifier` | existing legacy every-step labels | **off** |
| `guarded_oracle` | final labels after all required public fact slots | on |
| `guarded_no_verifier` | final labels after all required public fact slots | **off** |

**Only TRAIN feedback changes.** The exact frozen original pretrained
Encoder weights, data, task source-groups, tokenizer, public inference
verifier, separate validation-fitted frozen critic, eight original
inference/evaluation arms, and production authority all remain unchanged.

### Critical causal-confound correction

The old `fit_model` switched from mean-of-intermediate-steps CE to
final-step-only CE if no TRAIN feedback callback or Attention teacher was
present. An apparent `no verifier` improvement could therefore be a
different answer-loss objective rather than the absent oracle.

`no_verifier_v1` now explicitly keeps the **same stepwise loss schedule**
for the unsupervised Core, even though it never invokes the oracle callback.
The attention Core already runs a stepwise loss; it retains the same
per-operation Attention teacher. Any caller trying to inject a callback
or prefilled status tensor in no-verifier mode is rejected **before**
training execution. The default `legacy_oracle_v1` retains existing
behavior for old callsites.

## Source and accounting

- `group_training.py`: explicit feedback policy and provenance receipts,
  no-callback branch, unchanged Core stepwise objective, actual callback
  counts, strict fixed-operator arithmetic.
- `group_attention_campaign.py`: frozen CLI
  `--training-feedback-policy {legacy_oracle_v1,no_verifier_v1}` plus
  previously introduced `--terminal-guard`.
- `group_attention_campaign_review.py`: rejects policy mismatch,
  invented callback counts, nonzero no-verifier status, changed Core
  stepwise objective, missing terminal evidence, source, checkpoint or
  System2 trace identities.
- `group_feedback_factorial_campaign.py`: performs four *separate full*
  model/Encoder/optimizer/critic/lifecycle runs, charging each cold load
  and evaluation. It does **not** claim that all four runs share one
  paid Encoder call or a real target-host serving session.
- `group_feedback_factorial_review.py`: runs the already-existing full
  independent single-campaign replay **four times**, enforces identical
  public source groups and feature digests, learned Core initialization,
  TRAIN teacher, model artifact revisions, random sampler and optimizer
  schedules, and returns paired rescued/harmed outcomes for direct,
  fixed-depth System2 and native-NDU research arms. Fails closed if one
  model result, policy, sample, cost or original independent audit is missing.

## How to execute when the pinned checkpoint is available

Run one source- and seed-frozen matrix; files are create-only and never
mixed with other research studies:

```bash
python qualification/stem-cell-v1/group_feedback_factorial_campaign.py \
  --snapshot /approved/granite97 \
  --output-root /sealed/hepta-group-2x2-seed41-sgd \
  --seed 41 --training-profile sgd_v1 --steps 120

python -S qualification/stem-cell-v1/group_feedback_factorial_review.py \
  --legacy-oracle /sealed/hepta-group-2x2-seed41-sgd/legacy_oracle \
  --legacy-no-verifier /sealed/hepta-group-2x2-seed41-sgd/legacy_no_verifier \
  --guarded-oracle /sealed/hepta-group-2x2-seed41-sgd/guarded_oracle \
  --guarded-no-verifier /sealed/hepta-group-2x2-seed41-sgd/guarded_no_verifier \
  --output /sealed/hepta-group-2x2-seed41-sgd/external-recheck.json
```

Repeat seeds 41/47/53 and `sgd_v1` / `adam_v1`, preserving each
original cohort partition and checkpoint revision. This is **24 complete
candidate runs**, not a claim of 24 executed experiments. The original
`group_attention_campaign.py` and original reviewer remain callable
without any of the new options.

Numerical CPU mechanism tests:

```bash
PYTHONPATH=qualification/stem-cell-v1 python -m unittest \
  test_group_terminal_evidence test_group_terminal_receipt_review \
  test_group_training_feedback test_group_feedback_policy_review \
  test_group_feedback_factorial_review -v
```

These tests are now included in the preexisting research-only CPU
workflow. Normal source-only tests never substitute pretrained weights,
real model forwards, original independent human labels or held-out
future tasks.

## Exact observed evidence and unperformed work

The new **exact uploaded** `group_feedback_factorial_review.py` and
`test_group_feedback_factorial_review.py` files were reconstructed in
a local Python 3.13 runtime and checked against GitHub's original Git blob
SHA-1: `00ec63fb21ba250c14fb23f5e14495f529d2b2b4` /
`cec12cd3ebc0aaf48286f0a604beae4dc9986ccd`.
Seven isolated original-source cross-run / forgery tests **passed 7/7**
under normal Python and **7/7** under `python -O`.
For the source-only test isolation, the original single-run reviewer
was intentionally mocked, and the JSON read helper substituted with a
local strict reader. These 14 passes prove the *cross-run* audit logic,
**not** complete native campaign replay, pretrained learning, full
Torch fitting, or model performance. Distinct new tests for training and
original-reviewer integration have been authored, but are **not claimed
executed** in the isolated local mirror at the time of this handoff.

No new actual trained Granite97 four-way result, prospective reasoning
gain, measured 4096-Cell serving, NDU dominance, multimodal generation,
Cell production split, global stochastic FBSDE or 10T/100T equivalence
is established by these checks.

## Scientific next gate

Evaluate **direct/no-inference-verifier quality first**, before crediting
System2 or NDU. Compare direct, fixed-depth and NDU *paired* original
task scores and time/CPU, including missing-premise invalid attempts
and negative transfer. Do not choose a winner based on reused public
TEST labels. Independently source/time-disjoint natural tasks,
predeclared utility/cost profile and subsequent independent future
outcomes are mandatory before any candidate promotion.

**NO_MAIN_MERGE · DENY_ALL · NO_SELECTED_STEM · NO_EXTERNAL_EFFECTS.**
