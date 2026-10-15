# E1 true core Encoder triplet: Granite 97M / mmBERT-small / ModernBERT-base

**Status: Draft, SHADOW, DENY_ALL.** This is an executable but **retrospective** 224-case AG News binary study. The existence of the workflow and Python modules does not prove any hosted model download, tensor verification, accuracy, latency, three-model success, or approved Stem. Claim those only after the latest exact-commit job and independent evidence have completed.

## Distinct from the old Gemma pilot

The existing `hepta-e1-real-public-three.yml` still evaluates Granite/mmBERT/**EmbeddingGemma 2 text**. No Gemma data or predictions may be substituted for ModernBERT. This separate `hepta-e1-core-triad-real-cpu.yml` runs **Granite R2 97M** (384D, CLS, L2), **mmBERT-small 140M** (384D, masked-mean, L2) and **ModernBERT-base 149M** (768D, masked-mean, L2) against one identical original source panel. Different family-specific native poolers are intentionally registered and must not be represented as identical internal architectures.

Fixed model commits: Granite `835ad14087e140460703cf0fae09f97d469d65c2`, mmBERT `0eb3d056ec1d6333cf4e19b0966dfde342a41a3a`, ModernBERT `fa3113d09d6dacfe5528708803dd92a62240237a`. Each runner demands the exact publisher revision, a safetensors checkpoint, tokenizer and configuration. The acquisition compares publisher LFS SHA-256 or original Git blob hash, copies ordinary files into a complete digest manifest and executes through the shared repository's **LocalEncoder**, which checks the materialized tensor state and enforces local-only loading, no remote code and no pickle fallback. Reports describe local checks; **there is no independent owner attestation or signed production authorization**.

## Exact study

- One byte-identical archived **English AG News** panel, canonical SHA256 `2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4`. Train=128, calibration=32, test=64; all labels are retrospectively public. No future outcomes are claimed.
- One reviewed common CPU runtime: Torch 2.10.0, Transformers 4.57.1, Hugging Face Hub 0.36.0; 512-token strict cap without silent truncation and one actual forward per source case. Q24 rounding and complete per-case Feature Bank hashes before and after Head fitting.
- Identical seeded binary linear Heads, 40 full-train SGD steps, learning rate 0.15, frozen original Head controls, and calibration-only temperature selection. Complete private parameter counts are **770, 770, 1,538** (all within the registered 2K ceiling). Equal ceilings and steps do **not** mean equal FLOPs, VRAM or end-to-end training cost; the independent scorer preserves the separate cost observations.
- Source-bound local-model reports and a separate three-report numeric reviewer verify exact case pairing and control identity, calculate 64-case held-out accuracy/Brier and unadjusted McNemar comparisons. The small, retrospective English test **cannot** establish multilingual/code superiority or definitive evidence of a future learning advantage.
- No automatic Stem selection, no original deployed no-change baseline, no independent E0 host baseline, no three future windows, no signed NDU, no physical native Worker admission, and no multimodal or full 4,096 Cell target-host evidence.

## Commands and evidence boundaries

```sh
python -m unittest discover -s experiments/shared_stem_cell -p 'test_e1_core_real_cpu.py' -v
# Real public-weight execution is performed only by the separate pinned GitHub Actions workflow.
```

The synthetic fault tests are contract checks only. The GitHub Actions workflow attempts three **real** CPU weight/forward/SGD executions and emits write-once JSON results and an independent descriptive score. A network/publisher/model/timeout/memory failure stays a failure; no synthetic or cached predictions may substitute. Only original public JSON reports, source identity, runtime pin and failure diagnostics are uploaded; downloaded model weights are excluded from artifacts. The model-weight jobs may be queued/pending or fail; only their exact latest-SHA final job log/receipt can support an empirical claim.

## Remaining E0–E6 owner responsibility

E0: independently freeze the actual **deployed** no-change policy, owner manifest/weights, input/source and resource receipts. E1: supplement this public pilot with matched real Chinese/English/code, source-group-independent prospective tasks and E0 controls. E2: capture actual **Token Matrix** and compare pooled versus learned Token Query at matched **complete** Head budget; 768D pooled-residual training is not a Token Query result. E3: D0–D3 explicit specialization ablation, capacity matched and old-task-retention guarded. E4: actual learner updates/splits with three time-separated future windows, independently labeled utility, negative transfer and NDU versus the frozen no-change. E5: real visual/audio/sensor bridging and task utility, not just projection identity. E6: native 64/256/1,024/4,096 target-host CPU/GPU/RSS/latency/energy, WAL, signatures, Generation Fence, FinalUse, repeated recovery and exact-SHA `blocking-ci` acceptance.

All evaluation, selection and execution owners remain independent. This PR remains **Draft** and must not be merged to production solely because a small public CPU pilot or synthetic contract suite goes green.
