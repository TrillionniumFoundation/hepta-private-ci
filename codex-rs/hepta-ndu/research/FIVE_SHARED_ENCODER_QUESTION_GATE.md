# Shared Encoder, small question-conditioned Head: fixed development experiment

Date: 2026-10-14. Parent46fdc53a0faa0ddec5c264e14b1102cc60e651c6, PR#1697.
This is an additive frozen-feature diagnostic. It does not replace Reader/Group
ownership, admit a Reader, consume external reviewer grades or claim to complete
any of the five independent efficacy experiments.

## Why this is the next low-resource comparison

The previous Reader relevance study now has a completed recovery (run38518485794,
source61e909b2). Reused repeat-empty and nonempty-aligned plus restarted reversed
all still emit zero prescribed refusals on the three available SELECT donor
inputs. More pretrained decoder training is not presumed the cheapest remedy.
This experiment directly tests whether one actual frozen Encoder and a small
post-Encoder gate can distinguish the already fixed matched/mismatched question
pairs, before granting any runtime role to such a gate.

The original archived Encoder is loaded by the existing strict LocalEncoder,
including actual saved-tensor checks. No Laya classifier is removed. This is not
a421M Laya comparison or a new large-model download. Original model artifact
11586991191 and inventories remain the exact pins. The entire original archive
includes Reader bytes and is still acquired/staged; no Reader model is loaded
or invoked. That acquisition/staging cost is not hidden.

## Representation and parameter budget

Questions/options and full evidence bundles are encoded SEPARATELY. Evidence
text includes the already registered source timestamps, full bodies, order and
neutral citation IDs. No source is shortened; token preflight for ALL feature
inputs precedes Encoder construction. Over-cap material blocks the experiment,
without an easier donor or question replacement. Model maximum is512 tokens.

Features are frozen mean pools from the real archived Encoder, normalized per
vector, not by statistics fitted on SELECT. The cache key binds representation,
partition, source-family scope, component role and exact text. Cross-family
bundles are explicitly supplied by the inherited protocol; sharing a weight
owner does not authorize mixing a private cache. Batches do not mix cache scopes.
Within the experiment, each unique component is encoded once. Reusing an evidence
vector for different questions is actual reuse, not a claim that differing
joint question/evidence Encoder outputs can be cached as identical.

For width d and rank r, the gate is

s(q,e)=u.q+v.e+b+w.[tanh(Pq)*sigmoid(Re)].

It has2dr+r+2d+1 parameters:6,921 at d384/r8; the affine q/e control has769,
and evidence-only385. These are parameter-formula budgets until actual runtime
counts are reported. This is a per-Cell Head, not an Encoder copy. No posterior
calibration, NDU utility or probability of a correct final answer is implied.

## Fixed treatments and training

Use five arms at THREE fixed seeds20261014/15/16:
- frozen zero-readout gate;
- trained affine question/evidence Head;
- trained evidence-only Head (same source pair cannot be distinguished);
- trained low-rank question/evidence gate;
- same gate trained with reversed weak pair direction.

All trainable arms receive256 full-batch AdamW updates, lr0.003, weight_decay0.01,
gradient norm1.0. No SELECT early stopping, learning-rate search, threshold
selection, extra examples or best seed. Seed repetition is not new independent
tasks. Each model is safely saved and reloaded; shared features and Encoder
weights must remain unchanged. Frozen/reversed/aligned gates start identically.

TRAIN pairing is EXACTLY the13 available supplementary pairs out of14 original
questions from cancelled artifact11872208169, not newly selected from responses.
SELECT pairing is EXACTLY3 available out of4 recipients from artifact11863981474
and the existing select_question_relevance.build_plan. Public-plan projection
removes all answer strings. Generation outputs from the old trials do not select
training rows or labels. Cross-family swaps remain weak labels: entity matching,
topic cues and donor reuse can be shortcuts. This is a small already-exposed
DEVELOPMENT probe, not an independent relevance or semantic test.

Both missing pairs stay in planned denominators with no fabricated feature or
zero-effect imputation. Inference sees only two feature tensors. Raw logits
seal before label-based summaries. Report pair ranking and BOTH threshold
signs (matched>0,mismatched<0) separately; positive ranking alone is not selective
abstention. Zero ties do not pass. Neither proxy proves the eventual answer is
correct; no Reader call is skipped in production by this experiment.

## Cost and scope

One pretrained Encoder instance, zero decoder invocations and zero pretrained
parameter updates. Distinct Heads really have independent parameter objects.
Record exact feature rows/reuses, actual Encoder dispatches, Head optimizer
updates, safe checkpoint bytes and process timings. Parameters/bytes cannot be
converted into FLOPs, joules or equivalent task quality. The repeated seeds and
baselines cost actual optimization work. Whole-process time includes downloads,
loading and validation outside the narrower fit timing. No persistent-service
or multi-device memory benchmark is claimed, and no equal-TCO comparison with
the prior LoRA study is established.

Tests cover immutable inputs, full sources, source/family isolation, missing
pairs, unique-component encoding, explicit token caps, zero/invalid features,
state/evidence interactions, actual tiny optimizer changes, reversed direction,
safe reload and non-authoritative readout. At initial publication local Python
and container were unavailable; no local test pass or pretrained result is
claimed. Hosted tests must pass before the real archived Encoder study starts.

Files: shared_question_gate.py, shared_question_gate_trial.py,
test_shared_question_gate.py; workflow hepta-shared-question-gate.yml.
No existing training, projection, recovery or followthrough implementation is
changed. Recovery results and this new representation comparison remain separate.
