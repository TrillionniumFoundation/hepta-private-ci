# Hepta V16 — Real-feature specialist routing versus continued unsplit training

**Research-only; DRAFT / SHADOW_ONLY / DENY_ALL; no main merge or production Cell promotion.**

## Provenance

- Existing research PR #2364 on `research/stem-differentiation-v7-20261015`, frozen prior source head `1d8d2b480fe9e3af23be575b48cec11d0637766c`.
- Original archived `mmBERT-small` features from GitHub artifact `11890616195` of run `38546717991`; original archive SHA-256 `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`.
- Source V14 and V15 were verified with their exact SHA-256 and complete 58-file V15 seal. No new pretrained Encoder execution.
- 64 original TRAIN rows, 32 previously exposed CALIBRATION rows; 32 independent-of-training feature rows remained unscored; no held label read. Original rows and labels are not contained in this output.

## What physically changed

V16 retained the genuine frozen two-Head model from V15 and compared three new router training methods with a stronger, extra-80-update unsplit control. The direct loss gate and expected-loss gate each receive 80 SGD steps on 1,280 original TRAIN-example positions. The joint arm trains both experts and the gate for another 80 SGD steps, physically performing 2,560 expert-row forwards per seed in that stage. The continued control receives the same 80 additional steps but less active compute. This is **equal extra optimizer steps, not equal FLOPs or full-lifecycle cost**. All frozen V15 weights are unchanged.

## Actual CALIBRATION outcome (Brier: lower is better)

| Candidate | Seed 41 | Seed 47 | Seed 53 |
|---|---:|---:|---:|
| frozen | 0.671551 | 0.655443 | 0.659391 |
| continued | 0.595298 | 0.603400 | 0.595785 |
| centroid | 0.630272 | 0.635403 | 0.628882 |
| task | 0.665629 | 0.664531 | 0.662355 |
| loss_gate | 0.577418 | 0.562788 | 0.591583 |
| expected_gate | 0.619814 | 0.623929 | 0.609776 |
| joint_hard | 0.591106 | 0.594689 | 0.594723 |
| joint_soft | 0.598107 | 0.597057 | 0.603121 |
| extra_continued | 0.546142 | 0.544609 | 0.558352 |

Each arm was evaluated on exactly the same 32 already-exposed CAL records. Source-family independence and prospective future retention are not established. The calibration-only conservative selector chose **extra_continued in 3/3 seeds**, NOT a split candidate.

## Diagnostic: fold expert identity (TRAIN only)

| Seed | Out-of-fold teacher preferred head agrees with final experts (64 rows) | If globally flipped |
|---|---:|---:|
| 41 | 25/64 | 39/64 |
| 47 | 22/64 | 42/64 |
| 53 | 23/64 | 41/64 |

This is a descriptive TRAIN-set comparison. Final experts were fitted on all TRAIN rows, so this is **not an independent OOF causal estimate**; it diagnoses a possible expert-label mismatch. A single global flip may not fix the problem for all folds/tasks.

## Real receipt and independent replay

- Two independent OS processes reproduced **all 15/15 new safetensors SHA-256** and **3,264/3,264** output probability rows, with zero divergence.
- A NumPy-only reviewer, with neither Torch nor producer imported, reopened 15 V16 and all 58 existing V15 model files; repeated per-profile CAL and unscored predictions; maximum absolute probability error **9.485461993641309e-08**, no top-class flips. It did not repeat optimizer gradients or authenticate the physical host.
- V16 tests **30/30 pass** normal and **30/30 pass** in `python -O` with the exact actual features mounted, no skips. Combined V14+V15+V16 mechanism tests **46/46 pass** in each mode.
- Second OS process (Linux wait4) user+system CPU about **3.61 s**, whole-child peak RSS **325,208 KiB**. This is not an equal-arm cost, 4,096 Cell throughput, GPU or p99 result. V15/Encoder preparation and independent review are additional work.

## Important limitations

- The task-loss gate is trained against final experts that have already seen all TRAIN labels; it is a **TRAIN-only in-sample router**. Its improvements cannot be called cross-fitted independent learning.
- The expected-loss gate tends to select the same constant best expert, so a good score need not reflect input-conditioned specialist dispatch. Constant-head controls are retained.
- Any soft mixture uses **both** experts at inference, unlike hard Top-1; count both physical computes.
- The new joint-training arm uses an extra expert×2 training forward path; comparing it to a continued model only equalizes optimizer steps, not FLOPs or energy.
- Historical CAL has already been exposed; no new untouched outcomes, true independent retention, security/Final-use, signed split lifecycle, target-device scale or large-model-equivalence claims.

## Reproduction

Unzip `hepta_v16_executable_source_20261016.zip`, place the three `.py` files beside the existing exact V14/V15 modules, provision the original V15 completed inputs and model bundle privately, and follow `README.txt`. The `.zip` SHA-256 is `3d2d038509ca11d0fefbc53f7f0681e635c3c2ff1c366d03a93c4a746b357bec`.

## Recommended next gate

Retain no-change/unsplit deployment. To justify autonomous split, first establish stable expert identities by independent train-only alignment, then preregister routing on a genuinely unseen source-family/time panel, with equal-total training/FLOPs/peak RSS/p99 and independent retention. No current V16 candidate is production qualified.
