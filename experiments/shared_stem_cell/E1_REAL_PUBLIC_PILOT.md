# E1 public real-weight three-Encoder pilot — execution runbook

**Draft/SHADOW/DENY_ALL.** This is a physically executable English-only cross-sectional pilot, **not** the full E1 bilingual+code future-time candidate qualification. A workflow with zero completed pretrained model runs provides **zero** scientific evidence even if its Python mechanism tests pass.

## Pinned immutable dependencies and data

- Granite R2 `ibm-granite/granite-embedding-97m-multilingual-r2` @ `835ad14087e140460703cf0fae09f97d469d65c2`, official CLS+L2, 384D, 512-token experiment cap.
- mmBERT-small `jhu-clsp/mmBERT-small` @ `0eb3d056ec1d6333cf4e19b0966dfde342a41a3a`, research masked-mean+L2, 384D, 512-token experiment cap.
- `google/embeddinggemma-2` @ `914f7f89142e33e77833254d9c9b90c3cef7303b`, approved separate text-only 256D MRL profile, 512-token matched cap.
- Existing exact source implementations: compact Stem PR #1897 commit `e05f939f65fb76f6bdbf7470eef7e63b77284dcd`; Gemma/public AG News PR #1775 commit `f8d168a7689eb3624d97c44751791badd069e521`. The workflow pins both checkouts and verifies their exact HEAD.
- Existing immutable public AG News source hashes: `cc35afe9d5e7ff01878c9aeba08bb0bdfa16947702789530b216a580a1bc09d5` train and `3171d3aeee227372165bb0f9e84ebf2bfaf5fc870d034f33a5fc568e7995c672` calibration/test. Existing source selector yields 128 train, 32 calibration, 64 test rows. Labels in all files are already public, so this is **retrospective**, not secret-holdout or true future.

## Executable experiment

`.github/workflows/hepta-e1-real-public-three.yml` runs in one pinned read-only hosted environment. It installs pinned CPU Torch and source-facing model libraries, reconstructs public data from exact hashed parquet, verifies safetensors and publisher LFS digests where available, loads each real pretrained Encoder in a separate Python process and uses its registered readout. **No remote code, pickle weights, trainable projection, silent truncation or stub fallback is allowed.** Gemma goes through the original pinned audited text-only local-snapshot Stem owner, not a new implicit multimodal model.

All Head inputs are explicit rounded Q24 vectors; width 384/384/256. Each frozen and independently trained binary linear Head starts with the same seed **within** its Encoder arm. Whole-Head parameters are 770 (384×2+2) or 514 (256×2+2), both within a declared 2K ceiling; these are **not exactly equal parameter counts**. Run **40 complete train-only SGD updates** on the same 128 cases, then choose each Head's temperature from disjoint 32-case calibration data. Test labels have no computational path into optimizer, temperature fit or predictions (synthetic label-flip tests).

The write-once output includes every 224-case token count and feature digest, model source/revision, 96 untouched calibration/test predictions per frozen/learned Head, final real Head tensor digest, observed process CPU/wall/peak RSS and Encoder load/encode/train times. Weight origin signatures, physical Transformer forward counters, target worker batching, energy and complete lifecycle savings are **not** independently certified.

`e1_public_triplet_review.py` is an independent, model-free numeric scorer. It requires all three actual source-identical reports, unchanged train IDs/seed/SGD schedule, full predictor/Head identities and every source case; recomputes accuracy, Brier, and **unadjusted** exact paired McNemar on 64 public test cases. No model winner, confidence-based superiority, lifetime cost claim or production promotion is issued.

## Host-side reproducibility

For code/unit tests (requires local CPU Torch but **not** weights):

```sh
python -m unittest discover -s experiments/shared_stem_cell -p 'test_e1_public_triplet_*.py' -v
```

The hosted workflow itself creates the approved source data, model manifests and output paths. Missing models, network errors, compute timeouts and partially executed arms are preserved as **failures**, not replaced by synthetic data. Only sanitized JSON reports are uploaded, never weights or raw private training assets.

## What still blocks full E1–E5

Independent Chinese/English/code source-group/time-separated tasks and three real future windows; Reader evidence sufficiency; independent no-change *production* arm; 2K/8K/16K baseline-preserving residual learning; real Granite+DINOv2 vs Gemma E3 visual capability; real Whisper/audio/video temporal reversal E4; 64/256/1024/4096 Cell native performance and unclean WAL/FinalUse E5; independently signed NDU and exact-HEAD whole-repository `blocking-ci`. This single public task does not supply any of those.

**Authority is always DENY_ALL.** The trial may not mutate the selected Stem, production Encoder/Worker, Cell Head, Q24 V1 journal, CNS routes, Artifact CAS, or FinalUse.
