# V30 — original Granite text–route–DINO physical feature-cost comparison

2026-10-17 · **DRAFT / SHADOW_ONLY / DENY_ALL**. Additive study on frozen V29
`b60f54d7835a07808e0dd81e3f7f5d3b8ad4c71e`. No selected model,
Neuron runtime, shared-memory/caches, NDU ownership, CAS/CNS, final-use,
Cell split or `main` change.

## Why the earlier result cannot answer full shared-Stem economics

V28 physically ran **only** the frozen DINO image Encoder, with a historical
precomputed text-margin route requesting 21/64 original image features. Original
physical same-host CPU evidence was average ~5.48 s for 64 vs ~1.78 s for 21
image encodes; this is a useful **vision-only** cost reduction, not an end-to-end
Hepta or text+vision speedup. V25/V27 independent retrospective same-source
accuracy remained 17/64 for both text and frozen conditional (5 rescues/5 harms,
McNemar p=1). V29 stripped precomputed image class values from the model-facing
route but retained **historical** text-derived triggering. Thus no deployed
real-time text -> image execution or additional accuracy gain was proven.

## Physical new experiment and exact source identities

The research model process accepts **only** the exact V29 source-only route
`d8a555bef8f95680cd35a16cf3dbe7f8e9ab717fe626e4dc82e6fd61538773a6`,
original publisher source
`a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202`,
and pinned original ScienceQA media. It is not given TEST labels, full original
V27 plan, cached image classes, prediction archive, per-case outputs, or
historical probability vectors.

- Original 192-source-group ScienceQA-IMG publisher revision
  `b9984af01798586705cee1fbdfa80a6dcbef04f1` via reviewed predictor-source-only
  stager commit `751ab11dcb7ff3c20d895c698633e7b2d5ada2b8`.
- Frozen text model: original Granite97
  `ibm-granite/granite-embedding-97m-multilingual-r2` at
  `835ad14087e140460703cf0fae09f97d469d65c2`; one verified shared instance.
- Frozen image model: original DINOv2-small `facebook/dinov2-small` at
  `ed25f3a31f01632728cabb09d1542f84ab7b0056`; one verified shared instance.
- Source-bound original E3 encoder and verification code from
  `b8b2f10fe38506972301e77e3836729a90200673`, with transitive audited
  LocalEncoder imports separately fetched and checked against immutable Git blobs.
  Neither model may silently load random/meta tensors, reinterpret Laya's decision
  Head, or download different weights on error.

**Each ABBA arm** (full64, conditional21, conditional21, full64) begins by
physically encoding the **same 64 questions and four original choices per case**,
320 strings in exactly 20 observed Granite forward batches (max 16 prompts).
It normalizes Granite 384D CLS features exactly as original E3, forms
question/choice dot products, applies the original fixed ×8 softmax, and computes
`top1 - top2 < 0.005` entirely from the fresh text score. The historical V29
`trigger_vision` bit is a fail-closed *post-inference conformance check*, never
training target or model feature; every one of 64 bits must match or the
experiment stops without a positive receipt. The image Encoder then physically
processes either all 64 original test media (8 batches) or only those 21 selected
by the freshly computed text policy (3 batches). Each repeat independently
recomputes text features; no cache silently gives selective arms free text CPU.

Record separate text CPU/wall, image CPU/wall, combined input-to-feature
CPU/wall, true backend batch counts, image media bytes read, physical saved
model manifests/revisions, one-time acquisition/load wall time, separate
TRAIN-only warmup, and *process* high-water RSS. Compare both selected image
features and entire repeated text choice-probability tensors for numeric parity
<=1e-4 (descriptive tolerance, not a semantic accuracy threshold). Published
readout is sanitized aggregate only; it has no prompts, image data, model weights,
source IDs, probability arrays, choices or private labels. GPU bytes and energy
remain explicit NULL.

## Model-side source and label controls

Full original E3 archive is SHA-256 checked, its V27 full plan is sealed, and
V29 reduced route is checked **before original model or media acquisition**.
The archive and full plan are removed before any model run. An independent
fixed SHA source stager writes only source rows, media and TRAIN/CAL fit labels;
those unnecessary fit-label bytes are first verified, **then removed before V30
model launch**. TEST label callback/bytes/hash are absent in predictor-source-only
mode. Publisher HF cache is deleted before the model stage. No job shell sets
`HELD_SHA`; runtime rejects label environment variables or private label folder.

The existing source contract tests remain, plus V30 source-only tests for
route identity, exact 21/64, label/unknown class rejection, missing/mutated
model scores, missing/fabricated backend calls, four text inference repetitions,
selected image parity, and SHA-pinned transitive original Python model loaders.
`test_v30_live_text_vision.py` uses **synthetic controls only** and never pretends
to have executed pretrained weights. Hosted real-model execution is **push-only**
after this source gate succeeds; absence of a completed physical run is
`UNQUALIFIED`, not evidence of an achieved speedup.

## Scientific hard gates and intended interpretation

This experiment may establish the original **feature ingestion** CPU savings
when both text and image pretrained models are live and physically selected,
under one same-host warm-loaded research process. It **cannot** establish full
Hepta run latency or RSS *savings*: training, task/Head selection, task-result
accuracy, NDU selection, CAS/authority, checkpoint/recovery, GPU, energy,
front-end queues, privacy-protected multi-principal serving, negative transfer,
and prospective future-window utility are outside this scope. Process maximum
RSS is not a per-arm resident-delta measurement. In particular even a
successful V30 does not repair the frozen **negative** V25/V27 17/64 accuracy
finding. Do not change `main`, production models, selected Stem, FinalUse,
CNS, or Cell topology based on this study.
