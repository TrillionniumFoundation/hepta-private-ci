# P0.7 — Two original pretrained Encoder feature-necessity audits

**Research-only / DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO / NO_MODEL_SELECTION / NO_MAIN_MERGE / NO_FINALUSE / NO_PHYSICAL_SPLIT.**

## Scope and provenance

This is a **non-activating** P0.6.1 descendant using two **different** pre-trained encoders and classification tasks. There is **no single shared pretrained Stem across these two cohorts**. The result must not be pooled to claim cross-publisher Stem transfer. No new pretrained forward, LoRA training, GPU execution, GUI effect, tool-call bypass, OS effect or NDU/FBSDE natural-task gain is performed.

| Separate historical frozen material | Train | Held | Dimension/classes | Source/physical evidence |
| --- | ---: | ---: | --- | --- |
| mmBERT-small / AG News | 64 | 32 | 384D / 4 | Original archived pretrained source run `38546717991`, full ZIP SHA256 `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`; 16 recorded original batched forward calls |
| ModernBERT / BANKING77 | 64 | 32 | 768D / 2 | Original archived pretrained source run `38930339541`; full frozen-features ZIP SHA256 `3d8d6b7bed80f1f5efb1a17fd1df94208bef4239e5bbbbcd29e63262fb6e025d`; 96 recorded original forward rows |

Both publisher panels have been exposed in prior research. Source IDs and original model receipts are SHA-bound, but **original publisher signatures and independently custodied future labels are absent**. The AG News archive co-resides with historical held labels before source filtering; staging redacts them from the producer, but it is not genuine independent blind custody.

## Intervention, frozen before held labels

1. Match each original model's numerical feature row to its source ID, route, split, and original pinned source bytes. Keep **TRAIN-only** labels. Refuse held label fields.
2. L2-normalize each feature to 4; compute per-class means from the same 64 TRAIN examples only. Select a prototype temperature from the fixed 8-value grid `0.125..16` using **64×8 training leave-one-out** log-loss evaluations. This is a **paid** baseline: zero SGD **does not** mean zero computation. The grid maximum of `16` is selected in both tasks; do not misstate it as an interior optimum.
3. Privately, before the reviewer opens historical held labels, persist predictions for original correct source→case mapping, a zero-feature control, 31 *label-blind* one-position-through-31 cyclic derangements, 11 derangements **within each Cell routing stratum**, a feature-dimension mismatch control, and an identity-preserving common coordinate permutation. The latter is a positive numerical-invariance control.
4. Seal the complete prediction payload to its source SHA, train-only artifact and immutable private journal. In a separate process, independently replay each numerical ablation with a scalar `math.fsum` calculation, verify both original source material streams and all source rows, and **only then** read historically exposed AG News and BANKING77 held labels. Never upload raw features, original text, per-case IDs, logits or labels.
5. Produce the aggregate metrics below. Remain unconditional `HOLD_NO_GO`, regardless of test results.

## Original physically executed local review

| Historical cohort | Correct aligned /32 | Correct with zeroed held features | Cyclic deranged correct /32 (min–median–max) | Within-route deranged correct /32 (min–median–max) | Within-route permutations matching/exceeding aligned |
| --- | ---: | ---: | ---: | ---: | ---: |
| AG News / mmBERT | **28** | 8 | 3–8–12 | 3–8–10 | **0/11** |
| BANKING77 / ModernBERT | **22** | 16 | 8–16–24 | 12–16–20 | **0/11** |

**Brier** (sum across class dimensions) is `0.4091985446` for AG News and `0.3893825687` for BANKING77. The BANKING77 two-class sum-Brier is twice the binary-probability Brier, so direct comparison with prior `split=0.2390` binary-Brier is incorrect without harmonizing the definition.

The BANKING77 global cyclic control is **not** uniformly below aligned: 7/31 global cyclic shifts match or exceed the aligned 22/32. That weakens any simplistic “all shuffles failed” claim. In the stricter **within-Cell-route** derangement, 0/11 matched the aligned classifier on either cohort. These permutations are correlated, historical, and may be order-sensitive; their add-one fractions are diagnostics **not** confirmatory p-values or causal identification. Never treat a shuffled correctness difference alone as conclusive semantic reasoning.

The independent original text overlap audit found **zero** exact normalized train→held duplicate texts and **zero** held cases with maximum train token-Jaccard ≥0.80 in either corpus; this limited check does not rule out conceptual paraphrases, model pretraining contamination, or wider publisher leakage.

Retrospective non-budget-matched references: original AG News Gated `22/32`; original BANKING77 Split `20/32`. Neither contrast is a prospective equal-budget proof. Although the same *prototype rule* runs over both frozen feature sets, **different encoders, source domains, labels and configurations prevent any shared-Stem generalization claim**.

## Code and exact execution

- `p07_feature_necessity.py`: strict source adapter, private create-only fsynced source/prelabel/seal, trained-prototype controls, postseal independent reviewer; no effect capability.
- `test_p07_feature_necessity.py`: source-only, numeric, identity, recovery/tamper, original-GitHub-ZIP and authenticated late-label tests.
- `evidence/HEPTA_P07_DUAL_ORIGINAL_20261017.json`: **anonymous summary only**; source fields and historical test controls explicitly hold `DENY_ALL`.
- `.github/workflows/hepta-cell-fabric-p07-feature-necessity.yml`: exact-head source-only CI and a same-repository pinned original-archive job. The latter downloads AG News, BANKING77 frozen features and label-free public source **before prelabel**; obtains BANKING77 target and trial ZIPs **after prelabel seal**. GitHub API credentials are not forwarded to archive redirect locations. All prior Architecture, `v8-canary` and global `blocking-ci` gates are unchanged.

Local replay with original ZIPs in the research workspace:

```sh
cd qualification/neural-cell-fabric-p0
export AGNEWS_ORIGINAL_ARCHIVE=/absolute/path/to/hepta-agnews-mmb-pretrained-original.zip
export HDCF_ORIGINAL_ARCHIVE_DIR=/absolute/path/to/original-bank-zip-directory
export HEPTA_P07_AGNEWS="$AGNEWS_ORIGINAL_ARCHIVE"
export HEPTA_P07_BANK_DIR="$HDCF_ORIGINAL_ARCHIVE_DIR"
python3 -m unittest discover -q
python3 -O -m unittest discover -q
```

**Next required P0.8:** freeze the model/source, arms and hyperparameter costs *before acquiring new data*; secure independently issued human gold from genuinely new sources or future calendar windows; keep the final evaluator from reading candidate predictions before original labels are sealed. Compare same Stem and same task with Shared, Split, zero-feature, centroid, stronger reader and abstain controls. Register old-task retention and actual complete lifecycle cost. Only independent prospective positive benefit can authorize a future snapshot candidate; original worker, Final-use and model promotion remain unchanged.
