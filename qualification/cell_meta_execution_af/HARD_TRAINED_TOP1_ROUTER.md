# Train-time sparse Top-1 Cell routing — controlled research, no authority

**Status: DRAFT / DENY_ALL.** This is an additive CPU experiment layered on the
existing A–F conformance gate, original physical synthetic Router (#2090),
retrospective Granite 97M panel (#2110), and post-training hard-Top1 trial (#2120).
It does **not** modify or introduce a Neuron/Agentd/Worker, NDU Selector,
Cell Split executor, CNS route, signed Final-use, CAS, checkpoint, provider,
model installation, or serving endpoint. It cannot authorize deployment.

## Scientific question and preregistered arms

The old #2120 experiment **hard-routed frozen weights learned through a soft
mixture**; it did not show training-time sparse MoE. Here four fresh and
separately optimized FP32 CPU arms are trained on exactly the same original
pair/source/seed, with **one chosen Head per input row** in every gradient
update and every final Head evaluation:

| Arm | Policy during joint training | When does a child exist? |
| --- | --- | --- |
| `no_change` | one old Head | never |
| `fixed_router` | frozen affine gate, hard Top-1, zero gate updates | after the first old-task stage |
| `learned_router` | sample one route from learned Bernoulli gate, REINFORCE + entropy; hard Top-1 | after first stage |
| `adaptive_split` | use exactly the preceding learning policy if the **training-only** excess new Brier >0.08 | conditional; otherwise remain one old Head |

Each run uses the frozen 24 old-task SGD updates, then 24 old+new updates
(or the exact predecessor's registered 2..100 steps for local fault fixtures),
three exact seeds `41,47,53`, learning rate `0.35`, REINFORCE scale `0.4`,
entropy scale `0.002`. Gate sampling uses a separate seeded CPU generator
`seed XOR 0x45CC`. A fixed, previously selected route feature is retained;
its sign defines the frozen Router. No hyperparameter/threshold/seed is
selected by inspecting validation or test scores. Predictions are sealed
before the scored labels are consumed.

The learned policy uses **only the actually chosen Head**: sampled route
`a~Bernoulli(sigmoid(gate(x)))`, BCE loss from that Head, and the
score-function `((BCE_detached - frozen_parent_train_loss) * log P(a|x))`
plus a small entropy regularizer. This is an exploratory, high-variance
policy-gradient baseline; it is **not** a reliable general optimal router.
A fixed pre-Stage2 parent loss is used as a choice-independent baseline.

## Resource accounting and comparability

For `N_old` old fitting rows, `N_new` new fitting rows, `N_eval` final
scored rows, and `S` steps per stage:

- *Main optimizer Head work:* `S*N_old + S*(N_old+N_new)` **per arm**.
- *Scored Head work:* `N_eval` **per arm**. The producer partitions actual
  CPU tensor rows by chosen expert before each Head matmul.
- *Training router work:* `S*(N_old+N_new)` only if split. Learned arms
  additionally incur Bernoulli samples and gate gradient computation.
- *Scored router work:* `N_eval` only if split.
- *Extra diagnostic Head work:* `2*(N_old+N_new)` for old/new Brier and frozen
  parent baseline, **plus `2*N_old`** for each actual split parity check.
- *Extra diagnostic Router work:* `N_old` for split parity.

These auxiliary forwards are now explicitly accounted, not silently declared
free. All four arms have the same *main train/scoring Head row budget*, but
**not equal full compute, time, energy, communication, evaluation/search,
optimizer-state or migration cost**. The original frozen soft arm performs
different work. CPU time is a process observation, not comparable hardware
latency, and no target-host p95/p99 is established.

The independent stdlib-only verifier checks a complete FP32 Head/gate inventory,
pre-split parent and child bytes, training-only excess Brier, frozen initialization,
all training-step packed route ID bitsets and Head usage, fixed-route invariance,
optimizer/sample counters, post-training Top-1 selection and retrospective
Brier/NLL/accuracy. A hash identifies bytes but does not authenticate a model,
physical worker, GPU trace, original signer or an independent observer.

## Reuse of actual Granite research inputs

The existing exact-source GitHub workflow uses fixed upstream
`ibm-granite/granite-embedding-97m-multilingual-r2` revision
`835ad14087e140460703cf0fae09f97d469d65c2` and reviewed Encoder adapter
`e05f939f65fb76f6bdbf7470eef7e63b77284dcd`. It reconstructs the SHA-locked
224-row AG News panel and encodes Q24 384D features **once**, projecting to the
same declared 64D coordinates for all original and new controls.
It does not add an extra model load/encode per Head. The hard-trained stage
starts only after the existing source → pretrained model → panel → old soft fit
→ post-hoc Top-1 → both existing independent audits succeed. Failed physical
weight download/model forward is retained as failure, never replaced by
synthetic features or a historical result.

**The original AG News panel is retrospective and cross-sectional.**
`future_1`/`future_2` here are *two fixed retrospective test subsets*, NOT
observed future windows; `ood` is an unused same-source calibration slice,
NOT OOD. Artificial `step` ordering is not observation chronology. It is an
English-only binary subset, not evidence of general reasoning, multimodal
learning, deployment no-change or independently witnessed NDU benefit.

## Reproduction

```sh
# Source-only numeric and adversarial tests (requires CPU Torch):
PYTHONPATH=. python -m unittest -v \
  qualification.cell_meta_execution_af.physical_router_hard_tests

# Actual hard training only after the original soft and Top-1 reports exist:
PYTHONPATH=. python qualification/cell_meta_execution_af/physical_router_hard_train.py \
  --panel /tmp/41-trial-panel.json \
  --soft-report /tmp/41-trial-report.json \
  --posthoc-report /tmp/41-top1-report.json \
  --out /tmp/41-hard-train-report.json
PYTHONPATH=. python qualification/cell_meta_execution_af/physical_router_hard_review.py \
  --panel /tmp/41-trial-panel.json \
  --soft-report /tmp/41-trial-report.json \
  --posthoc-report /tmp/41-top1-report.json \
  --hard-report /tmp/41-hard-train-report.json
```

The original files are create-only; refusing to overwrite previous reports is
intentional. Unit tests that feed synthetic vectors prove numerical/mechanism
properties only, not a pretrained model/label source or prospective result.

## Negative-result policy and remaining independent gates

The retained six toy task panels show that the original **fixed routing remains
better than learned/adaptive routing on conditional toy tasks**. Do not optimize
away the negative controls, postselect seeds, change the frozen split threshold,
repeat one trajectory as independent data, or report a significant winner.

Before scientific selection: obtain real source-family-disjoint future episodes,
pre-outcome frozen inference receipts, the true deployed no-change counterfactual,
independent outcome custody, registered NDU resource/cost profiles, false-OOD
acceptance/retention, full cost and confidence intervals with familywise testing.
Before any physical Cell Split: original signed CAS / migration / bootstrap /
CNS cutover / generation fence receipts, replay/WAL recovery, independent
Final-use and current production CI/security gates. This PR never grants
those permissions: `production_admission=BLOCKED`, `authority_posture=DENY_ALL`.
