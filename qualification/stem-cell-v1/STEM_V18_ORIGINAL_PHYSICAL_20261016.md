# V18: original mmBERT feature-backed Head investment — negative research

**2026-10-16 · DRAFT / RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL.** No main merge, model selection, CellSplit, NDU, Worker effect, FinalUse or CAS/CNS change. This is an additive continuation of PR #2481, itself stacked on #2364.

## Source identity and actual physical execution

- Original GitHub Actions run: [38546717991](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38546717991), artifact **11890616195** (original ZIP SHA256 \`0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7\`).
- Original real \`jhu-clsp/mmBERT-small\` (source revision \`abc32620dd4f6ab06f5fbe905dc25f310618e09f\`) **cached pretrained FP32** 128×384 features; exact original safetensors \`e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490\`; original dataset \`50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c\`.
- Existing V14 source preparer creates a byte-exact TRAIN/CAL-only input (canonical SHA \`d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a\`); **64 TRAIN**, **32 previously exposed CALIBRATION**, **32 unscored BLIND**, from the same AG News dataset family. Holdout labels are contained in the original public ZIP but **removed from the prepared training packet**. This is logical separation; it is **not independent source/label custody**.
- Actual local CPU/torch physical training: a common 80-step 1,540-parameter linear no-change reference, then each of four candidates receives **80 further actual SGD/Adam steps** with the same 16-row training schedule. Linear additive readout 1,540 extra scalars; gated output residual 1,925; continued single 1,540; two-expert unsupervised TRAIN-only centroid route 3,080. All candidates **exactly equal no-change outputs before continuation**. No pretrained encoder forward in this continuation.
- Two independent local process invocations (regular and \`python -O\`) physically reproduced **all 15/15 raw per-arm inference SHA across 3 seeds**, including original 32 unscored blind predictions. Separate NumPy reviewer (does not import the producer/Torch) reopened original publisher labels for TRAIN/CAL only, checked source SHA, re-scored **15/15** raw logits, Brier and accuracy; **7/7 original-backed mutation tests** passed per mode. Physical gradient independent rederivation, model issuer signatures and future utility remain unverified.
- 11/11 source-only zero-delta and fail-closed tests pass in each of regular and \`-O\`. Exact new HEAD hosted CI has to finish; a locally executed source test does not qualify all CI.

## Actual historical 32-case CAL results (multiclass Brier, lower is better)

| Arm | Seed 41 | Seed 47 | Seed 53 |
| --- | ---: | ---: | ---: |
| **no_change** | **0.437980** | 0.434068 | **0.437576** |
| linear additive residual | 0.498554 | 0.442697 | 0.478153 |
| gated output residual | 0.492714 | 0.468585 | 0.484659 |
| continued single | 0.554359 | 0.437740 | 0.544364 |
| split router | 0.465996 | **0.427346** | 0.476711 |

No-change gets **24/32 classification accuracy in all three seeds**. None of the learned arms improves that accuracy; split-router in seed47 has a lower Brier but accuracy **23/32** and worse outcomes in the other seeds. All 64 TRAIN examples are essentially perfectly fitted, so adding more local learning from the same source is not a demonstrated generalization remedy. One historical seed/metric contrast does not establish significance, independent task improvement, or net specialization benefit.

## Resource and security boundaries

These CPU measurements cover only local Head training/inference, not original pretrained model acquisition, encoder pretraining, original encoding, Reader, audit, signatures, GPU energy, a deployed service, 4,096 concurrent Cells or recoverable WAL. The first Torch/optimizer warmup is included in its run and makes short elapsed-time comparisons noisy. The study does not measure future utility, production RSS, target-host p99 or NDU uplift. Historic CAL cases have been viewed repeatedly; they can never be relabelled as prospective heldout. Private per-case logits, source text, publisher labels, TRAIN/CAL features and generated model weights **are not committed**.

No change to production owners or authorization semantics. Both the model runner and independent numerical reviewer **always produce non-authorizing outcomes**; they do not issue cryptographic signatures, permissions or CellSplit approval.

## Reproduce using the SHA-fixed original artifact

With \`original.zip\` downloaded directly from GitHub Actions artifact 11890616195 and hash-verified:

\`\`\`bash
cd qualification/stem-cell-v1
python stem_counterfactual_split_v14.py prepare \
  --archive /private/original.zip --out /private/v18-inputs --labels-out /private/held-gold.json
rm /private/held-gold.json
python v18_original_feature_paired.py --inputs /private/v18-inputs \
  --output /private/v18-scores.json --private-logits /private/v18-logits.json
python v18_original_independent_review.py --archive /private/original.zip \
  --report /private/v18-scores.json --private-logits /private/v18-logits.json \
  --output /private/v18-independent.json
HEPTA_V18_ORIGINAL_ZIP=/private/original.zip \
HEPTA_V18_ORIGINAL_REPORT=/private/v18-scores.json \
HEPTA_V18_ORIGINAL_PRIVATE_LOGITS=/private/v18-logits.json \
python -m unittest -q test_v18_original_independent_review
python -m unittest -q test_v18_original_feature_paired
\`\`\`

The new read-only, artifact-pinned \`hepta-stem-v18-original-physical.yml\` GitHub workflow also performs separate regular and optimized processes, rejects mismatched output identity and **never uploads raw/private original data**.

## Next qualification priorities

**Do not promote or auto-split.** Obtain new independent source families, an actually independent label/outcome owner, prospective future windows and matched full lifecycle costs. First test whether strong cheap no-change/linear models generalize, then allocate incremental training to a Cell only if its *net future utility* survives negative-transfer limits. Only after that run whole-stack 64/256/1024/4096-Cell target-host CPU/RSS/GPU, queue age, p95/p99, WAL/recovery and owner-specific FinalUse.


## Follow-up: independently scored paired harms and exact-SHA qualification repair

A fresh ordinary + `python -O` execution of the original five-arm physical Head producer, with the same fixed original 128x384 original mmBERT feature file, reproduced all **15/15** CAL/train/blind raw-output SHA identities and independent original NumPy scorer outcomes. These are **the same historical 32 CAL cases** across three repeated seeds; this adds no new observations, independent families or forward calls.

The added `v18_paired_damage.py` runs *after* the independent original ZIP/label/logit reviewer has verified the complete material. It computes rescue/harm on the **same actual original CAL identities**, rather than comparing only aggregate accuracies:

| Candidate | Seed 41 rescues / harms | Seed 47 rescues / harms | Seed 53 rescues / harms |
| --- | --- | --- | --- |
| continued single | 0 / 1 | 1 / 1 | 0 / 1 |
| linear output residual | 0 / 1 | 1 / 1 | 0 / 1 |
| gated output residual | 0 / 1 | 1 / 1 | 0 / 1 |
| two-Head split router | **0 / 2** | **1 / 2** | **0 / 2** |

Even split Seed 47's favorable **-0.006722** historical multiclass Brier difference versus no-change accompanies *net one additional incorrect case*, and is smaller than the exploratory 0.01 absolute decision threshold. Thus no split candidate passes even a weak descriptive historical quality screen. The per-arm actual short CPU Head training spans exclude Encoder/Reader/data loading/optimizer cold-start parity, evaluator service, GPU and target-host lifecycle; these figures must **not** be recast as complete TCO.

The exact-original ZIP, complete 15-arm physical prediction hashes and all 12 paired harm profiles were rechecked in two separate original-weights-cached-feature CPU runs. New **10/10** pure arithmetic/malformed-input tests pass per Python mode (20 executed). Earlier **11/11** Head zero-output mechanism cases and **7/7** original archive-backed reviewer attacks pass per mode, with independent numerical scoring. This is local CPU model research, **not hosted complete CI**, hardware/operator signatures or prospective NDU utility.

**Actual P0 repair:** The original read-only physical workflow's SHA check previously contained a misquoted shell filename. It now uses a real quoted `printf '%s  %s\\n' ... | sha256sum -c -` construction, preserving complete SHA verification. It now runs the paired damage auditor, validates numerical agreement between ordinary/`-O` runs, and uses a `pull_request` event so the workflow result can be evaluated on the exact PR head. The untrusted-input V18 source-only auditor now **refuses unattested `future` cohorts**, rather than allowing a synthetically labeled row to appear in a "future gain" tally. Its tests cover future-label spoofing.

**Authority and uncertainty remain unchanged:** no genuinely new source families, no independent prospective observer/calendar window, no signed model/source custody, no matched full lifecycle cost or 4096-Cell target-host recovery measurements; all gates remain `DENY_ALL`. No original V14–V17 source, production model, Worker, Control/CNS, NDU, final-use or main mutation is made by these research-only files. Hosted exact-new-HEAD CI, architecture and global blocking-ci results are separately required.
