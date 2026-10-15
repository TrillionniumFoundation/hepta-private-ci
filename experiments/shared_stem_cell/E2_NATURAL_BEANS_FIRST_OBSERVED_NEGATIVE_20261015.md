# E2 Beans natural-photo physical run: three-ZIP independent preliminary audit

**Research only / SHADOW_ONLY / DENY_ALL / NO Stem promotion.**

## Source and observed Jobs

The original GitHub Actions [run 38680856403](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38680856403) is source HEAD `927bf53b184c3947db17a129834046c5f03add04` (PR #2189). The original **source authoring** and **DINOv2-small + Granite 97M model-fit-and-seal** jobs completed successfully. At this report's inspection, the final **independent-retrospective-natural-outcomes** job had *not* completed, so its fourth original artifact was unavailable. This file does not imply full successful Actions run or four-ZIP acceptance.

The following three real Actions ZIP files were obtained, hashed byte-for-byte against GitHub-reported SHA-256 digests, and checked using the already authored strict original source/producer/withheld validation contracts:

| Original role | Artifact ID | Exact original ZIP SHA-256 |
|---|---:|---|
| source, including 60 real leaf photographs and 36 TRAIN labels | 11948574238 | `49ee4b855879e8ad463fb3f0ffb21e30b332fb24d1626360aa8f382d16ef82ad` |
| real pretrained DINO+Granite / fitted Bridge / label-blind predictions | 11949168280 | `92536c949e16ee0722357ccb1d881f371707df3c26424cd93dd2bfc96e49511e` |
| withheld TEST targets (only opened in independent readout) | 11948269689 | `946101fe7e57a151ce5ae9ec314fc6e01b7244aeac48f49034ee0a581e09c67d` |

**No weights, photographs or model tokens are committed to this PR**; the original GitHub artifacts remain the independently retrievable evidence. SHA-256 proves exact artifact byte identity, **not** independent publisher, source-author, model runtime or ground-truth owner attestation.

## Physical result independently reconstructed (24 real Beans TEST photographs)

| Arm | Correct / 24 | Meaning |
|---|---:|---|
| Original fitted DINO+Granite cross-modal Bridge | **20** | Original TRAIN-only cross-modal projection and frozen text label centroids |
| Original frozen DINO visual prototypes | **20** | No trainable cross-modal projection |
| Original unaligned | **8** | Pretrained features without fitted cross-modal alignment |
| Original train-target-rotated Bridge | **2** | Negative control |
| **New frozen DINO visual Ridge (1,155 params)** | **20** | TRAIN-only, zero new pretrained Forward, independent SVD parity |

The original fitted Bridge and the visual Ridge produce **identical predicted class labels on all 24 images**, not merely matching aggregate counts. Relative to the frozen DINO prototypes, fitted Bridge and visual Ridge each rescue one case and harm one case (19 both correct, 3 both wrong). The exact unadjusted McNemar two-sided p-value is **1.0**. At 20/24, a Wilson 95% descriptive interval is approximately **[0.641, 0.933]** per arm; this is not a model-selection power or confidence certificate.

The vision-only Ridge checkpoint is computed only from 36 TRAIN images, with immutable alpha=0.1. The independent review reruns this model using a numerically distinct thin-SVD implementation, with maximum absolute weight difference **1.2212453270876722e-15**, and checks all 24 pre-target sealed predictions. Model SHA-256 `07bdbaf99b402525ff8d31f1e1ccef7929a1095f3e0ebb6b41756f792a735897`; prediction SHA-256 `2571d19cc83cd5ea8fb94bafc79e8a4c8f47c5003708e7afc27c6efadc69f5e8`.

## Scientific conclusion and missing evidence

**This is a negative result for the claim that fitting the cross-modal Bridge improves this specific image-classification task over simpler frozen DINO or trained lightweight DINO Head controls.** It does *not* show that cross-modal alignment is useless for genuinely cross-modal queries, evidence grounding, text-conditioned retrieval or other distributions.

The 24 Beans TEST images use retrospectively public labels and *synthetic ordinal observations*, not three actual future chronological groups, nor independent farms/plants. The three arms are not identical in trainable parameter budget or total compute cost; no hardware p95/p99, joules, NDU, no-change signed baseline, OCR/text/native multimodal five-arm outcome or negative transfer qualification is provided. The inference receipts are self-reported and **do not authenticate actual publisher or host**.

The only justified next investment is an **equal-compute/parameter controlled naturally cross-modal task** with real text-conditioned decisions and independent future-source adjudication; further parameterizing this Beans-only Bridge without such evidence is not recommended. The selected Stem, inference owners, V1 Q24, Writer, WAL, FinalUse and production `main` are left unchanged.

## Exact local replay

Use the three source ZIP SHA values above, the sealed visual Ridge files, and run `e2_beans_three_archive_observation.py` with explicit `--source-zip`, `--producer-zip`, `--withheld-zip`, each paired `--*-sha256`, plus `--model`, `--model-sha256`, `--predictions`, `--predictions-sha256`, and create-only `--output`.

The submitted `qualification/e2-original-beans/ACTUAL_THREE_ARCHIVE_PRELIMINARY_20261015.json` is the exact canonical readout. This is **not** a replacement for the required four-original-ZIP reviewer in #2211, or native exact-head `blocking-ci`. `four_original_archives_full_audit_passed=false`, `stem_selected=false`, `production_accepted=false`, `authority=DENY_ALL` are invariants.
