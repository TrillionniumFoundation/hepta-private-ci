# Hepta V20 — physically replayable, clock-bound prospective material challenge

**2026-10-16 · Draft / SHADOW_ONLY / DENY_ALL.** Extension of PR #2364 on immutable parent source `8b079d609716bc067df253ed04e59e870f74c2a4`, independent from main. This change is a scientific-admission *negative gate*, not a new Cell/AGI claim, live router, NDU selector, model replacement, CAS/CNS/FinalUse owner, or release.

## 1. Why a new check was necessary

The existing V18 `verify_signed` checks 200+ source hashes, at least 100 family roots per future window, two distinct Ed25519 roles, original-frozen identity, paired losses, retention figures and complete **claimed** resource numbers. It explicitly never promotes anything. However **signatures on hashes and numbers do not prove the signer actually observed task data, that the calendar window happened, or that the original frozen model executed those inputs**. Before October 17, 2026 UTC, the research's frozen V18 first-future-window cutoff cannot be met by a genuinely observed post-freeze case. An attacker or fixture can otherwise sign future-dated claims today; older code describes such packets as merely numerically/cryptographically consistent. Do not misinterpret that as a physical future evaluation.

V20 provides a separately versioned source-material challenge. It uses unmodified V18 signatures and NO-GO verdict as a prerequisite, then adds actual source bytes, independent saved-model numeric replay, strict signing roles and observation-clock causality. It does not change historical V18/V19 files or silently revise published numeric results.

## 2. Source/compute/evaluation custody contracts

Three distinct *externally pinned* Ed25519 public keys are required: **source issuer**, **executor**, **label evaluator**. The original V18 signed source/outcome packets remain intact. V20 additionally requires:

- Source-signed complete material for every case: original task text, actual root/family identifiers, UTC timestamp, predeclared future1/future2 window and finite 384-element FP32 feature data. The canonical case digest is **derived from the original signed text, root, family, window and time**; it is not an arbitrary rehashable ID. SHA-256 exclusions inspect the **actual original 128-case AG News ZIP** (`0f3c8c2c...`), including canonical Unicode-NFKC/casefold text collisions, historic raw root IDs and namespace/alias changes.
- Executor-signed full original baseline/candidate probabilities and physically selected Head routes, bound to the exact material/source digest and pinned model-file SHA. **An independent NumPy reference physically reloads the saved V15 normalizer and actual V16 seed-41 extra-trained unsplit Head, two-Head joint model and gate from safetensors**, rejecting tensor drift, wrong shapes, nonfinite values or artificial logits. There are **zero new pretrained Encoder forwards**; the supplied 384-D feature-to-raw-text correspondence is not authenticated and remains a real blocker.
- Evaluator-signed label rows, sealed *after* model predictions, are used to independently recompute each original Brier loss. These must match the previously signed original V18 paired outcomes within bounded literal tolerances (probability 3e-5; loss 4e-5). Old-task retention figures, source-publisher custody, signed reported costs, true family independence, actual Encoder execution and executor-host identity **cannot** be certified just by these matching signatures and therefore remain explicitly false/null.

All three signed stages must obey source-observation ≤ material seal ≤ execution seal ≤ evaluator seal ≤ **actual UTC clock at auditing**. Future1 must chronologically end before future2 begins. The live CLI intentionally has *no* `--now` override; tests inject a later fake clock **only** to exercise positive contract consistency on deliberately synthetic future fixtures. A synthetically signed October 18 or October 25 observation is **rejected on October 16**, not counted as observed evidence.

## 3. Genuine executed work and negative controls

Local host: Python 3.13, NumPy 2.3.5, safetensors 0.7.0, cryptography 46.0.4. The original SHA-pinned AG News archive and physically trained V15/V16 tensors are present in the **isolated analysis environment, not the user's deployment host**.

- **28/28 V20 actual-source-backed tests PASS** in ordinary Python; **28/28** under `python -O`. They include full NumPy re-forward of 200 **synthetic task examples** (not observed future data), real cryptographic Ed25519 verification, genuine saved model weights and the actual original AG News text exclusion list.
- Adversarial tests resign changed-but-fraudulent source text, historic case root alias, duplicate text, reversed future chronology, original-model logits, labels, paired losses and seal order. All fail closed; old saved weight and normalizer byte changes are rejected before evaluation. Case rows can be reordered without altering case-identity join; missing/duplicate cases cannot.
- Existing **V14–V19 186/186** normal suite plus V20: **214/214** in an actual combined normal run (12.505 s, zero skips); all **214/214 optimized** test cases passed across independently executed module slices (the single `python -O` monolithic run exceeded this local invocation's time budget; do not represent it as one full continuous pass). Exact original archive and original model state were supplied. This is local, not the GitHub hosted exact-new-SHA acceptance.
- Source-only V20 tests are separated from original-material tests. The workflow extends the prior V14–V19 exact-HEAD read-only job: PR tests **source-only contracts**; push/dispatch checks the SHA-fixed original GitHub archive and physically reconstructs V15→V16→V17 before exercising V20, then uploads **only sanitized HOLD**, never raw source text, model weights, private labels, source packet bytes or synthetic signer secrets.

## 4. Actual current scientific decision

The original frozen V18 report and no-real-future HOLD were loaded. At `2026-10-16T13:10:35Z` the original-material admission emitted an actual create-only machine-readable receipt:

`decision = HOLD_NO_REAL_SIGNED_POST_FREEZE_MATERIAL`

`required_first_source_date_utc = 2026-10-17T00:00:00Z`

`new_signed_future_roots = 0; independent_future_windows = 0`

`scientific_promotion_authorized = false; production_authorized = false; authority_posture = DENY_ALL`

No original independent source publisher, new human-labeled family, validated new Encoder feature origin, new task prediction, new independent evaluator, future-negative-transfer witness, matched full lifecycle telemetry or 4,096-Cell recovery qualification has been supplied or synthesized. **Even future V20 contract consistency will still return an explicitly nonauthorizing result.** A legitimate future scientific `GO` would need a separate custody/security owner and a truly prospective, untouched study, not just this checker.

## 5. Reproduce the actual current HOLD and regression

```sh
cd qualification/stem-cell-v1
export PYTHONPATH=.
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export HEPTA_V20_INPUTS=/private/original-v14-input
export HEPTA_V20_V15=/private/original-v15-saved
export HEPTA_V20_V16=/private/original-v16-saved
export HEPTA_V20_ARCHIVE=/private/hepta-public-pretrained-38546717991.zip
python -m unittest -v test_v20_original_material_challenge
python -O -m unittest -v test_v20_original_material_challenge
python v20_original_material_challenge.py \
  --retrospective STEM_V18_SOURCE_FIRST_20261016.json \
  --output /private/new-v20-original-source-HOLD.json
```

To validate genuine future evidence *after it exists*, supply all five independently signed V18/V20 packets, all three separately pinned public keys, the exact original V14 snapshot/ZIP and saved frozen V15/V16 models **together**. Partial input or future-dated claims will be rejected. Never commit the external raw packets or private keys.

**Status: NO SOURCE ADMISSION, NO MODEL PROMOTION.** Future study requirements remain original signed material, independent author/custody, physically verified Encoder bytes, untouched future source families, independently adjudicated old-task retention, matched total lifecycle costs and complete target-device recovery/safety CI.
