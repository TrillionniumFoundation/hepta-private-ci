# P0 V6 — independent cold pretrained Encoder feature replay

**Research-only / DRAFT / `DENY_ALL`.** Builds on P0 V5 original Head/feature numeric replay, not a replacement for original Neuron, Worker, Evidence, CAS, FinalUse, NDU or model selector. No selected model, production caller, release or `main` change.

## Scientific defect addressed

V5 could prove that archived frozen features and trained Head tensors recomputed the stored probabilities. It did **not** prove that the archived features came from the claimed pinned Granite, mmBERT, or EmbeddingGemma pretrained weights. Re-signing a synthetic feature bank and regenerating predictions could satisfy that narrower observation.

V6 adds a **different CI worker and a genuine cold re-load** of the already registered immutable model/tokenizer revisions. The worker does not receive original held target labels, does not retrain Heads and cannot mint model provenance, authority or output correctness. The source branch still retains original Laya as a different *native frozen no-change* arm. Laya has no comparable trainable 2K-Head tensor replay and is not substituted into this test.

## Frozen intervention, model identity and measurement

| Attribute | V6 requirement |
| --- | --- |
| Three candidate original checkpoints | Granite 97M `835ad14087e140460703cf0fae09f97d469d65c2`, mmBERT-small `0eb3d056ec1d6333cf4e19b0966dfde342a41a3a`, Gemma2 text `914f7f89142e33e77833254d9c9b90c3cef7303b` |
| Material | Exactly original frozen MultiRC fit/blind arrays already pinned in V5, with original immutable source identities |
| Subset selection | Sort by `sha256(protocol : panel : split : original_case_id)`, select **two distinct source groups per train/calibration/test**; re-encode BOTH `original` and `no_evidence` for each pair |
| Physical forwards | Exactly 12 selected case inputs per model, separately loaded from pinned public weights, without a dummy, random or cached-feature fallback |
| Feature comparison | Original stored Q24→FP32 safetensors feature vs second real Q24→FP32 Encoder; predeclared max error **2 Q24 units** per dimension |
| Additional requirements | Original held Head probabilities already pass V5 independent replay; original/cold tokenizer counts equal; all cold request times strictly positive; actual reported CPU model load; current mmBERT full serialized source-weight witness matches original |
| Original held labels | Unavailable to the worker; `no_evidence` has **no new annotated truth** |
| Result | `cold-pretrained-encoder` GitHub job must pass before independent human-label scoring is reached |

Source checkout and model download in the new job use independently re-fetched exact reviewed commits/revisions and reject untrusted serialization, incomplete snapshots and publisher LFS hash mismatch. The job runs on another GitHub hosted Runner; however the model origin is still **not independently signed by a trusted production issuer**. The numerical replay is a model-output *spot check*, not a cryptographic guarantee that every untouched source row was really encoded using those weights. Report even a one-case mismatch, including compiler/device/rounding explanations, as a **failed V6 claim**; do not silently broaden the tolerance or retune sample IDs after seeing predictions.

## Exact code and operation ownership

- `experiments/shared_stem_cell/p0_cold_encoder_replay_v6.py` — deterministic evidence probe; actual CLI only calls the existing pinned `e1_public_triplet_real_cpu.encode_pretrained`. It first checks the complete original V5 safetensors + numeric replay and then re-infers 12 selected original inputs per model.
- `experiments/shared_stem_cell/test_p0_cold_encoder_replay_v6.py` — source/identity/label absence/Q24/paid work/publisher-claim fault suite with genuine FP32 Torch Head fitting **on synthetic features**. A new regression changes a **TRAIN-only archived feature** while updating its SHA: V5 held-prediction replay legitimately misses it; V6 actual-Encoder comparison rejects it. This is the strict additional causal evidence.
- `.github/workflows/hepta-p0-multirc-semantic-four.yml` — adds exactly one new read-only job, `independent-cold-pretrained-encoder`; it depends on original materials, all three real Head runs plus separate V5 numeric replay. The original human-label score job now also requires V6 success. Upload *only* report, small origin/CPU receipts and failed status; never original pretrained weight trees or held labels.

**Source-only local evidence:** 16 new tests, plus unchanged original P0 tests, are executable offline. Nothing in these tests loads actual remote pretrained weights. Real physical P0 performance requires a successful exact-HEAD GitHub job and independent original artifact reading. A queue, a source-only green or an individual Granite-only result is not a P0 four-model result.

## Required controls for scientific inference (still open)

1. Full exact-head physical job successfully loads Granite/mmBERT/Gemma, independently completes Laya and writes all actual prediction/feature/Head artifacts.
2. New V6 cold second-process subset feature replay and original V5 Head numerical replay both succeed; signed model-load admission remains a separate owner obligation.
3. Independent human MultiRC material owner opens labels **after** predictions are sealed, reports hard same-question true/false candidates and qualified source-family uncertainty.
4. Equal-quality, end-to-end Encoder + Reader + training + queue + checkpoint + failure-recovery cost must be verified on target hardware. No energy/GPU/p99/future1–3 data can be inferred from the narrow CPU readout.
5. Existing `blocking-ci`, architecture, source/merge review and original Evidence WAL/CAS/FinalUse must pass before any production effect; V6 does not change or waive them.

A negative or underpowered outcome leaves all model candidates available for future research, with `model_selected=false` and `production_promotion_permitted=false`.

### Run commands

```sh
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover -s experiments/shared_stem_cell -p 'test_p0_cold_encoder_replay_v6.py' -v
PYTHONPATH=experiments/shared_stem_cell python -O -m unittest discover -s experiments/shared_stem_cell -p 'test_p0_cold_encoder_replay_v6.py' -v
```

The authoritative physical invocation is the additional job in the existing P0 workflow. It refuses absent approved pretrained weights, missing source manifests and unknown CPU execution dependencies instead of injecting mock features.
