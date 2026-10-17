# Hepta V18 — source-first uncertainty and signed future-evidence admission

**2026-10-16 · DRAFT / SHADOW_ONLY / DENY_ALL.** No selected model, real Cell Split, learning control, CAS/CNS/FinalUse authority, or `main` modification. V18 uses original archived V17 model and data identity; no new original pretraining, task labels, future calendar window, independent source publisher or target-host 4096-Cell experiment has been created.

## Source and frozen comparator

V17 original frozen feature archive is `11890616195` from GitHub Actions run `38546717991`, original ZIP SHA-256 `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`, model `jhu-clsp/mmBERT-small` @ `abc32620dd4f6ab06f5fbe905dc25f310618e09f`. This V18 audit rereads V15, V16, V17 and independently invokes the Torch-free V17 saved-tensor auditor to revalidate **82 original saved model/normalizer tensors** and exact source/feature/label lineage. The input contains 64 old TRAIN, 32 previously exposed CALIBRATION and 32 unscored HOLDOUT cases. The audit scores only the 32 known CAL labels; never opens the 32 held labels. The frozen no-change research comparator is V16 **extra-trained unsplit single Head**, not a deployed A0.

## Independent case-unit reanalysis

Across seeds `41,47,53`, the same 32 CAL cases were reused. V18 averages each original case's outcome across the three seeds **before** resampling, so no 96-independent-case pseudoreplication. It uses 4096 deterministic original-case bootstrap resamples, reports raw and 12-contrast Bonferroni-tail descriptive ranges, and publishes only aggregates (never labels, source texts, per-case feature vectors, Head tensors or raw scores). All source-family independence, actual prospective inference and statistical-significance claims remain **false**, because family roots are not independently authenticated and prior tuning repeatedly exposed this same CAL panel. These ranges are *not* inferential confidence intervals for future utility.

A positive `gain` means candidate Brier was smaller than the extra-trained unsplit baseline:

| Original candidate | Historical mean Brier gain | Multiplicity-adjusted descriptive 95% resampling range |
|---|---:|---:|
| V17 geometry-aligned router | **−0.111474** | [−0.199445, −0.036423] |
| V17 logit-reference aligned router | **−0.111474** | [−0.199445, −0.036423] |
| V17 unaligned OOF router | −0.121814 | [−0.203297, −0.053507] |
| V16 final-loss router | −0.027562 | [−0.055975, −0.000919] |
| V15 continued unsplit (before extra updates) | −0.048460 | [−0.074309, −0.024400] |
| **Infeasible after-label oracle over two frozen Heads** | **+0.016075** | [−0.014412, +0.053368] |

The oracle uses *true CAL answers after inference*, so it is not a deployable policy. This numerical ceiling is only for the two existing saved experts on the same exposed CAL panel, **not** a mathematical upper bound on possible future routing algorithms or all Cell designs. Do not interpret negative resampling ranges as a causal generalization result.

The actual independently audited V17 researcher decision remains **no split / retain extra-trained unsplit** for 3/3 seeds. No retrospective promotion is permitted.

## Prospective signed-source intake (new research-only code)

`v18_future_source_intake.py` now explicitly refuses to call these 32 reused CAL cases a future evaluation. With the available materials, the actual create-only output is **`HOLD_MISSING_NEW_INDEPENDENT_WINDOWS`**; it reports zero signed new source roots and no independently measured future utility or negative transfer. It never grants production/scientific promotion.

A future operator may provision an immutable research-frozen V17 source identity, a complete exclusion roster of all 128 archived source rows, plus an original-source packet and evaluator packet **independently signed with Ed25519**. The verifier checks exact canonical signatures against *externally pinned, distinct* public keys, two genuinely postfreeze time windows, ≥100 independent family roots per window, no reused old root/case, original-case paired losses, and a complete numeric CPU/RSS/p99/energy/recovery cost census. It will reject missing material, duplicated cases or roots, reused families, spoofed timestamps, changed-and-resigned raw evidence that reuses known source roots, fake costs and wrong signatures.

Even a structurally and cryptographically consistent test receipt is only **`SIGNATURES_AND_NUMERIC_CONTRACTS_CONSISTENT_NOT_AUTHORIZED`**: neither public key identity nor source veracity can be established solely by user-supplied strings; provenance, independence, model publisher trust, actual host execution, post-release future outcomes, independent retention, NDU and original signers still require separate custody checks. It never returns `GO`, `production_authorized=true` or a selected model. Unit tests use ephemeral signed synthetic *contracts*, never pretend these are real future observations. No private keys or private data are included in public source.

## Tested original source and reproducibility

- Physically reran the original-input, V15, V16 and V17 read-only review: **82/82 original tensor files validated**, 32 distinct original case records, three correlated seeds and 12 historical comparisons.
- V18 source bootstrap and separate signed-intake code compile and run in regular Python and `python -O`.
- V14+V15+V16+V17+V18 combined suite: **157/157 PASS** in regular and optimized Python; zero skips with exact original material mounted. The V18 source-only slices can run in CI without private archive: `test_v18_source_first_uncertainty.Mechanism` and `test_v18_future_source_intake.Gate`.
- Original code, source identities, numeric comparisons and test/receipt results are in `STEM_V18_SOURCE_FIRST_20261016.json` and `STEM_V18_FUTURE_SOURCE_HOLD_20261016.json`. Source-independent hosted exact-SHA, full repo Rust+Clippy+fmt/cargo-deny, independent Evaluator and full lifecycle production checks must finish for their own SHA; no earlier green inheritance.

### Run with original immutable predecessor material

```bash
cd qualification/stem-cell-v1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export HEPTA_V18_INPUTS=/private/v14-input
export HEPTA_V18_V15=/private/v15
export HEPTA_V18_V16=/private/v16
export HEPTA_V18_V17=/private/v17
python -m unittest -q test_v18_source_first_uncertainty test_v18_future_source_intake
python -O -m unittest -q test_v18_source_first_uncertainty test_v18_future_source_intake
python v18_source_first_uncertainty.py --inputs "$HEPTA_V18_INPUTS" \
  --v15 "$HEPTA_V18_V15" --v16 "$HEPTA_V18_V16" --v17 "$HEPTA_V18_V17" \
  --output /private/create-only-v18-original-clustered.json
python v18_future_source_intake.py \
  --retrospective /private/create-only-v18-original-clustered.json \
  --out /private/create-only-v18-HOLD.json
```

## Strict continuation gate / decision

| Candidate | Future utility gain | Independent negative transfer | Per-arm peak RSS | p99 | 4096 Cell throughput | Conclusion / no-change reference |
|---|---|---|---|---|---|---|
| V16 extra-continued unsplit | Not measured | Not measured | Not measured | Not measured | Not measured | Frozen research no-change comparator, not deployed A0 |
| V17 expert-alignment split | Not measured | Not measured | Not measured | Not measured | Not measured | Historical CAL behind unsplit, reject for production |
| V18 signed-source intake | **No actual signed windows provided** | **No authenticated retention window** | Not measured | Not measured | Not measured | `HOLD`; zero permission for automatic split/merge/promotion |

**Decision: NO MODEL PROMOTION; no automatic new Cell and no unsupported giant-model-on-device claim.** Next meaningful external scientific input is a truly independent new-source evaluator, with frozen no-change and candidate, separate old task retention, full-life resource accounting, authentic signing keys/real source custody, and actual host metrics. Until such original evidence exists, further tuned outcomes on the same old 32 CAL samples should not decide the architecture.
