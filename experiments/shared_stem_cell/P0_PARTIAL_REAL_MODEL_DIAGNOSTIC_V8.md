# P0 V8 — partial original-model observability without weakening the four-arm gate

**Status:** Research / Shadow / `DENY_ALL`. Additive to the frozen original V7
source and existing Hepta model/learning/effect owners. No model selection,
production route, Q24/Neuron/CNS/Control/Evidence WAL, CAS or FinalUse changes.

## Problem verified by source audit

The previous physical-four-models job runs Granite, mmBERT, EmbeddingGemma2 and
Laya in a single model-producing job. It preserves individual failed slots and
uploads partial files on failure; however it intentionally exits nonzero when
**any** of the four models fails. All downstream independent V5/V6/V7 replay
jobs then skip. The successfully written original model artifacts therefore
receive no independently reproduced *per-arm* numeric diagnosis, while the
all-four scientific success rule correctly remains blocked.

## Implemented

A new **independent, strictly read-only** `partial-original-model-diagnostic`
GitHub Actions job runs if and only if original human material creation succeeded,
including when the downstream original model job failed. It downloads only
original `fit.json` and `blind.json` and the existing producer's original
partial-result artifact, *not* the human held labels or pretrained weights.
It runs the unmodified V5 original NumPy/safetensors feature/Head/prediction
replay for **each physically present** Granite/mmBERT/Gemma artifact, in
complete isolation from missing arms. Laya is admitted only for a separate,
source-bound frozen native prediction census; it is not trained or numerically
replayed from invented Laya Head weights.

Each model has one explicit disposition:

- `original_head_numeric_replay_consistent`: original source-bound Head output
  equals the actual saved tensors and frozen feature archive within the V5
  registered tolerance. This is NOT an attestation of the source foundation model.
- `laya_native_identity_only`: original full frozen Laya prediction identity
  and bounded reported costs are structurally consistent, **not** an independent
  Laya-weight re-forward or an equal-training comparison.
- `unavailable`: no completed original result, or an explicit original failed
  execution slot. It remains missing: no fabricated zero quality, guessed
  result, or post-hoc substituted model.
- `invalid`: a physically present source, manifest, prediction, replay, scope,
  lineage, signed-authority claim, or failed/success contradiction was rejected.
  This is a **nonzero CI job failure** after writing a bounded original
  diagnostic; the invalid entry never becomes `unavailable` or a passing arm.

All per-model observations retain `DENY_ALL`. The result *always* sets
`whole_four_model_success=false`, `task_quality_or_stem_ranking_computed=false`,
`independent_real_pretrained_weight_origin_verified=false` and
`production_promotion_permitted=false`. Even if all four outputs are present,
**this job is not the scientific acceptance path**. The original all-or-nothing
physical job, complete V5 Head numeric replay, V6 new-host cold Encoder,
V7 full 40-step SGD replay, human label-owned score and independent full
`blocking-ci`/architecture/FinalUse remain required and unchanged.

The diagnostic's archived SHA values are a bounded observation, not signed
publisher or host attestations. It never opens testing labels, downloads any
foundation weights, chooses a Stem, modifies previous artifacts or computes
semantic accuracy/Brier.

## How to reproduce (synthetic feature exercises only)

```sh
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell \
  -p 'test_p0_partial_pretrained_diagnostic_v8.py' -v
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_*.py' -q
PYTHONPATH=experiments/shared_stem_cell python -O -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_*.py' -q
```

The adversarial suite covers one/three/four simulated physical model slots,
true Torch-trained small Heads on **synthetic** features, a Laya native fixture,
missing and contradictory producer files, forged report and authority fields,
changed predictions despite valid-looking metadata, links to external files,
failed slots, and write-once preservation of invalid evidence.

**Not established**: actual pretrained weights invoked in this development
container, real natural-language accuracy, any physical run whose CI is still
queued, origin signing, independent future windows, equal-quality runtime TCO,
P1–P5 architecture claims, or a production promotion. None may be inferred from
local unit tests or a successful partial-diagnostic job.
