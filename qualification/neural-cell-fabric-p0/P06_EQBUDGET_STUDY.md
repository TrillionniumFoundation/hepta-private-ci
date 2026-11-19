# Hepta Neural Cell Fabric P0.6 — genuine historical pretrained equal-touch intervention

**Disposition: RESEARCH_ONLY · DRAFT · SHADOW_ONLY · HOLD_NO_GO · DENY_ALL · NO_MODEL_SELECTION · NO_FINALUSE · NO_PHYSICAL_SPLIT · NO_MAIN_MERGE.**

## Why this experiment is needed

PR #2615's actual ModernBERT/BANKING77 experiment found a Split Head 20/32, **exactly matched by a no-Encoder/no-SGD type-count prior**. PR #2625 found that original learned mmBERT/AG News Gated Head predictions performed 22/32 compared with a type-count prior's 8/32. Those are **different pretrained models, tasks, fit budgets and source groups**. Neither establishes whether the same-model/same-task CellSplit intervention beats a strong cheap control. This P0.6 study closes a narrower same-model comparison and exposes additional **negative** evidence.

## Immutable physical input and exactly what ran

- Original publisher/model material: historical GitHub Actions run `38546717991`, artifact `11890616195`, entire ZIP SHA256 `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`. Five required original inner SHA256s are pinned in sibling `agnews_crossfamily.py` and checked before processing.
- Real original pretrained **mmBERT-small frozen 128 × 384 FP32** feature tensor, SHA256 `e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490`; physical upstream receipt declares **16 original batched pretrained Encoder calls**, not 128 separate calls and **zero new pretrained Encoder forwards** in P0.6.
- One historical original AG News publisher, 64 TRAIN / 32 CAL / 32 HOLDOUT examples, with each case as its own original group; CAL labels/features are not used for fitting or hyperparameter selection. **This is not an independent future cohort:** publisher HOLDOUT answers are historically present in the same original ZIP as pretrained features.
- P0.6 executes **new real CPU FP64 Head SGD** over previously generated original frozen features, for seeds `(101,211,307)`, fixed 512 SGD steps per arm, learning rate 0.05, weight decay 0.0001, train-only row L2 feature normalization to length 4, four classes, and fixed full feature dimension 384. No pretrained weight download, new Encoder fine-tuning, model promotion or external execution is involved.

## Carefully controlled arms

| Arm | Learned scalars resident | Active parameter touches per update | Train procedure | Inference feature access |
|---|---:|---:|---|---|
| `split` | 3,080 | 1,540 | Original 2-type route chooses active classifier | One Head |
| `random_route` | 3,080 | 1,540 | Independent hash route, same Head capacity and steps | One Head |
| `shared_twin` | 3,080 | 1,540 | Two shared Head slots, one updated per step | **Two Heads** (more inference FLOPs) |
| `shared_one` | 1,540 | 1,540 | Fully shared single classifier | One Head (less resident weight) |
| `split_zero` / `split_swap` / `frozen` | No extra fitting | 0 incremental | Exact trained/initial states are reused | Zero feature / swapped Cell / no SGD |
| `type_prior` / `global_prior` | None | 0 SGD | TRAIN-only smoothed class counts | No learned Encoder feature inference after fitting |
| `centroid` | 4×384 class mean values | 0 SGD | TRAIN-only class centroids, fixed temperature 0.25 | Class feature similarity |
| `centroid_train_loo` | 4×384 class means + scalar | 0 SGD | TRAIN-only leave-one-out multinomial log-loss across 8 fixed temperatures | Class feature similarity |

`centroid_train_loo` **does have training/search CPU work** (512 paid train-only calibration predictions) even though it takes zero SGD steps. It is a strong **cheap nonparametric learning baseline**, not a zero-compute model. Shared-twin and Split match active SGD parameters touched, but **NOT their two-vs-one Head forward cost**. The best like-for-like comparison is Split versus random-route (same resident scalars, active head and steps). Head pretraining and network residency are measured separately from the historical frozen Encoder, and no full serving TCO is claimed.

## Real observed local experiment on historical heldout (do not call it a prospective winner)

| Treatment | Seed 101 correct/32 | Seed 211 | Seed 307 |
|---|---:|---:|---:|
| `split` | 13 | 9 | 9 |
| `random_route` | 10 | 13 | 5 |
| `shared_one` | 11 | 16 | 18 |
| `shared_twin` | 8 | 14 | 12 |
| `type_prior` | 8 | 8 | 8 |
| `centroid` fixed 0.25 | **28** | **28** | **28** |
| `centroid_train_loo` | **28** | **28** | **28** |
| Original **historical**, separately trained Gated Head | 22 | 22 | 22 |

On all three seeds, train-only LOO chose temperature **16.0**, the largest **predeclared** candidate. This is an **edge-of-search-grid** result, not evidence the optimal temperature was found. The calibrated centroid's multiclass Brier is `0.4092` (rounded); the historical Gated Head Brier was `0.5925344` and **does not use a matched P0.6 training budget**. The centroid vs archival Gated correct/incorrect discordance is 7/1 (nominal paired exact p=0.0703125), **not** statistically supported superiority after historical reuse and multiple comparisons. Repeating the same 32 HOLDOUT cases under 3 random training seeds is not a 96-case independent evaluation.

Crucially, this is **strong evidence against promoting the current CellSplit route** as a performant reusable specialization strategy, not proof that neural specialization is impossible. First fix cheap controls, richer training/data regimes and legitimate future transfer.

## Prelabel-before-review and independent numerical checks

1. `matched_router_p06.py source` verifies SHA-locked archive, real tensor member and source IDs; writes a private create-only `redacted.json` containing **FIT labels only** and **no CAL/HOLD labels**. The original source custodian nevertheless has a gold-co-resident archive; its original-label independence is explicitly `false`.
2. `matched_router_p06.py producer` receives only the redacted file; physically fits four arms for three seeds; seals every Head weight digest, all 32×11 held predictions per seed, fixed optimizer metadata and nonauthorization to a create-only 0600/fsynced record **before review**.
3. `matched_router_p06.py review` authenticates seal bytes and weights first. Only then does it reopen original publisher archive, **reconstruct original 128 real feature vectors and compare the exact prelabel source bundle**, reexecute all SGD, and use **independently authored NumPy FP64 `matched_router_oracle_p06.py`** to recompute 12 model fits and 672 learned/frozen ablation probability rows (numeric max absolute error <2e-11). Independent oracle **does not** claim exact weight byte equality; different FP64 summation orders may differ at last bits.
4. Late-score 32 archival held labels without publishing IDs, feature tensors, labels, model weight arrays or per-case predictions. Upload only sanitized aggregate JSON with `HOLD_NO_GO` and no authority.

Checks explicitly reject wrong archive source bytes, label leakage, duplicate/unknown IDs, wrong Cell routes, changed feature vectors despite valid shape, stale/mutated predictions, tampered seals, malformed/nonfinite data, and changed fitted-head digest claims. Test execution on synthetic fixtures is never a pretrained model result. Hosted source HEAD and prospective-merge CI must finish before any GitHub CI success claim.

## What would constitute a *new* positive result

1. Completely **new publisher/source-family** with independently controlled, chronologically later test labels not visible during protocol or model selection; preserve strict per-group/episode leakage exclusion and release seal.
2. Same frozen original Encoder, same feature preprocessing, genuine matched candidate budgets and data, common original goal and metric, inclusion of strong centroid/kNN/linear/ridge non-SGD/low-cost controls.
3. Separate models for calibrated predictions, causal task effect, recursive NDU utility and runtime cost. Strict paired independent adjudication, old-task retention, negative transfer and false positives.
4. Real CPU/GPU/VRAM/RSS/p50/p95/p99/energy/recovery and 64/256/1024/4096 simultaneous task workload on the target host; model tuning, evaluation and migration costs counted once.
5. Native UI/OS action effect still requires original Native Worker/Codex spine, independently authenticated fresh UI readback, current Final-use permission, durable intent/reconciliation. Nothing here authorizes direct executable code, GPU side effects, arbitrary memory writes or bypass of MCP for remote effects.

**Absolute status: DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL. Do not merge into `main`, promote a model, activate learned FBSDE/System2 or call this multimodal generation, 10T/100T parity or full Computer Use latency superiority.**
