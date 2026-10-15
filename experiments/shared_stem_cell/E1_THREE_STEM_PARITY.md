# E1 three-Encoder matched causal-frontier contract (research only)

**Scope:** Join previously *separately* executed E1 datasets for Granite 97M R2, mmBERT-small and EmbeddingGemma 2 text without equating unmatched real tasks. This file adds **no** pretrained weights or model loader, does not read private data or perform model inference, and cannot accept production model selection.

Upstream qualification owners remain [#1897](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1897) (real-model-capable compact Granite/mmBERT Head-only program, currently without matched physical weights) and [#1775](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1775) (public real EmbeddingGemma 2 and Laya frozen studies). The latter's 128-case AG News val2 is **cross-sectional English news only**, and must **not** be stitched to unrelated Chinese/code or true future cohorts.

## Fixed candidates (published identity candidate only)

| Candidate | Public repository | Model revision proposed for separately vetted snapshots | Feature ABI | Pooling |
| --- | --- | --- | --- | --- |
| Granite R2 | `ibm-granite/granite-embedding-97m-multilingual-r2` | `835ad14087e140460703cf0fae09f97d469d65c2` | 384D | CLS + L2 |
| mmBERT-small | `jhu-clsp/mmBERT-small` | `0eb3d056ec1d6333cf4e19b0966dfde342a41a3a` | 384D | masked-mean + L2 (research readout) |
| EmbeddingGemma 2 text | `google/embeddinggemma-2` | `914f7f89142e33e77833254d9c9b90c3cef7303b` | 256D | official MRL-256 + L2 |

These immutable revisions are **identity candidates**, not approved local manifests, weights, tokenizer provenance or evidence of compatibility with the target inference environment. The planned mmBERT revision is intentionally one exposing a safetensors file; untrusted pickle binaries may not be used as a fallback. Actual model/tokenizer digest checks, license and exact model inference must be independently executed and reviewed.

## E1 protocol

Each candidate has its *own* E1 observation with the existing `e1e5_confirmatory_review.py` schema and the same exact approved dataset SHA, plan SHA and Scope. For every one of **train / calibration / test / future1 / future2 / future3 / OOD**, require independent Chinese, English and code cases, complete `source_group`, source digest, original input identity, modality, `language` and `task_family` mappings. The code rejects future source/time reuse from the underlying reviewer, unregistered poolers and feature width, forged no-change swaps, budget mismatches, and even a missing task family in a single split.

Every E1 study must provide actual train-only Head update receipts, initial frozen Head and immutable no-change predictions. The new triplet interface receives each per-model `study`, separately recorded physical-run SHA, `training` metadata (seed, update steps, optimizer, minibatch identities, Head ceiling **and** actual Head parameters) and `tokens` (every case, model-specific count, no silent truncation, at most 512).

All three model studies must agree on every matched source case, label, source group, Scope, event time and task family; no-change model/Head identity and probabilities must be identical. Training seed/steps/batch/optimizer/learning rate, train-case digest, minibatch-index digest and Head ceiling must match. Actual feature dimension and trainable parameters may differ within the same declared ceiling and must be reported. Identical original strings do not mean identical token counts, FLOPs or resources.

Example (operator-provided, already frozen and locally verified `e1-three-candidate-panel.v1` study):

```sh
python experiments/shared_stem_cell/e1_three_stem_consistency.py \
  --panel /approved/e1-three-candidate-panel.json \
  --output /sealed/e1-three-candidate-parity.json

python -m unittest discover -s experiments/shared_stem_cell \
  -p 'test_e1_three_stem_consistency.py' -v
```

This tool computes matched test/future1/future2/future3/OOD binary accuracy and Brier for every no-change, frozen and learned Head, plus per-language-family coverage, and prints declared Head parameter counts, model-specific token range and **self-reported** resource fields. It does not compute causal NDU confidence intervals or accept a model winner.

**Blocking before E1 scientific acceptance:** real source-licensed Chinese/English/code tasks in three genuinely future chronological windows, externally audited original labels and Reader four-condition sufficiency; exact reviewed model/tokenizer weight files; genuine train-only updates and predictions sealed before future labels; matched no-change baseline physically executed; no-collapse / OOD / old-task forgetting; independent cost/energy/quality evidence and the exact-SHA native Worker/FinalUse/WAL owner, security and `blocking-ci`. Each is outside this advisory validator. `production_promotion_permitted=false` and `authority=DENY_ALL` are unconditional.

**Test scope:** 22 locally passed deterministic, synthetic parity/fault tests, source blob SHA `412962cf4b705985d068e2332b3b1d2f491848bc`, tests SHA `2900ab077a954ebb9986f4b7c9d1bdf7aacd680d`; exact-HEAD hosted CI required separately. These tests do not demonstrate Granite/mmBERT/Gemma physical learning.

## 2026-10-15 core three-Stem parity extension (97M / 140M / 149M)

The previous `hepta.stem-e1-three-candidate-panel.v1` explicitly remains the
**Granite/mmBERT/EmbeddingGemma** research panel. It is NOT the requested
smallest-vs-multilingual-vs-code/general core Encoder comparison.

The separate `hepta.stem-e1-core-granite-mmbert-modernbert.v1` panel requires
exactly Granite R2 **97M** (`835ad14087e140460703cf0fae09f97d469d65c2`,
384D CLS+L2), mmBERT-small **140M**
(`0eb3d056ec1d6333cf4e19b0966dfde342a41a3a`, 384D mean+L2),
and ModernBERT-base **149M**
(`fa3113d09d6dacfe5528708803dd92a62240237a`, 768D mean+L2
as an explicit proposed research readout, **not** an independently validated
deployment ABI). Both panel types use the existing E1 nested observations,
strict same-source/source-group/label/Scope and chronology match, same
training schedule and frozen/no-change controls. The new model revision
identities are exact pins, not cryptographic proof of loaded weights.

The new observational result schema is `hepta.stem-e1-core-triad-parity.v1`.
It refuses Gemma as the third member; no substitution or stitching of the
unmatched existing public AG News Gemma experiment with the 128-example
mmBERT/ModernBERT trial in PR #1835 is permitted. That earlier pair used
different case counts, multi-class labels and optimizer settings than the
224-example binary trial. **It cannot produce a valid three-way comparison
without re-running all three on one frozen source and training protocol.**

This extension adds no weight download, training, physical model forward,
target-host resource attestation, authentic future windows, real NDU or
independent no-change provenance. Its tests are deterministic synthetic
contract/fault tests only; `production_no_change_source_independently_authenticated=false`,
`stem_winner_selected=false`, `production_promotion_permitted=false` and
`authority=DENY_ALL` remain hardcoded. E0 independent deployed baseline,
E2 Token Matrix vs pooled features, E3 D0-D3 specialization, E4 future/negative
transfer, E5 modalities, and E6 signed native 64/256/1024/4096 physical
measurements must be completed before any Stem selection. Any real run
must use the same independently frozen source, pinned model weights,
full lifecycle receipts and a separate blinded evaluator.
