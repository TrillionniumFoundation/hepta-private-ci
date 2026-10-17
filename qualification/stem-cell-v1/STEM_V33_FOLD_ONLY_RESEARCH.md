# V33: fold-disjoint normalization on original mmBERT Cell Heads
Research / DRAFT / DENY_ALL. Parent V32: `00b4f011f98eb7f9d361c5020c7fc914410da86e`. No production routes or main merge.

## Scientific correction
V32 first estimated the mean/std on all 64 original TRAIN examples before its four crossfit folds; the held 16 source features affected the training scaler. This is transductive *unlabeled* feature usage, not label leakage, but not strictly fold-disjoint OOF. V32 historical code and report remain unchanged.

This additive V33 reuses V32's real Head/AdamW fitter and original SHA-locked TRAIN-only 64x384 pretrained mmBERT feature material. Each fold fits the scaler on its **48 non-held TRAIN rows only** (24 Cell0 + 24 Cell1). A wholly independent no-Torch NumPy scorer reconstructs those scaler bytes, saved Head weights, all logits and paired old/new-cell correctness. TRAIN CAL and BLIND labels are not in the learner/reviewer. Source stage may have handled the publisher's full archive before removing it; it is NOT an independently attested custodian.

Original archive ZIP SHA256: `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`. Exact 64-TRAIN stage SHA256: source `69bdb09bb235c9cf490da400e239c5d9fabe8e13327cb255721090ea47d2e096`, features `2530b62d48b593cebeeb783c3ee754f8229b924558340dd09fb7160c6d1e3cc3`.

## Actually executed locally (not hosted CI)
Two separate physical PyTorch CPU fits (each 3 seeds x 4 folds x 3 update streams x 40 = **1,440 optimizer updates**); independent NumPy replay verifies **48 Head states** and **60 source-bound output digests**. Local source + true-original adversarial tests **21/21 ordinary, 21/21 python -O**. The two independently generated sanitized NumPy reports are byte-identical, SHA256 `2ecf2255789bd4c6d9cbb2d0f6035cc3176169bbad9947f1c126bd1fdd2c16be`. That digest is the exact-value hosted acceptance target; job must recompute it from original physical material, not use a fixture fallback.

| Correct/64 | Seed41 | Seed47 | Seed53 |
|---|---:|---:|---:|
| Frozen first-stage old Head | 41 | 41 | 39 |
| Continued single Head | 45 | 42 | 46 |
| Balanced rehearsal | 41 | 43 | 46 |
| Source-gated split | 44 | 42 | 41 |
| Same-two-weight source-blind average | 43 | 46 | 46 |

Two-Head split 127/192 correct vs source-blind same-weight average 135/192; **no consistent split uplift**. Note source-blind average executes both Heads per case while sparse split requires one selected Head: equal resident model scalars does not prove equal serving FLOPs/CPU. Fold normalization uses all 48 non-held rows including Cell1 *unlabeled* features, so do not interpret this as temporally old-only prequential training. No original CAL/BLIND or future source-family learning evidence; no independent NDU net benefit.

## Hard acceptance
No incumbent deployed baseline, held-out future windows, training gradient independent replay, new-task negative transfer, target-host 4096-Cell p95/p99, crash recovery, signer/FinalUse, Artifact CAS, CNS cutover or lifecycle permission. `HOLD_CORRECTED_FOLD_NORMALIZATION_NOT_PROSPECTIVE`. No MODEL PROMOTION, NO CELL SPLIT, NO MAIN MERGE, **DENY_ALL**.
