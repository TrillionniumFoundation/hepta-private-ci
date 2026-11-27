# E24: true original E16 five-param Reader answer geometry, before human-label scoring

**Research only / DRAFT / DENY_ALL.** Isolated additive child of independently developed eight-arm real original Reader [PR #2309](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2309) at frozen `d48c7b0878eba63143d3a378a8206d708eaca87d`. This adds one read-only original-archive evaluator, ten real-ZIP-backed tests, a sanitized scientific observation and a narrowly extended ORIGINAL E22 source-blind → independent-human workflow. It does not alter the original trained/frozen E16 Head weights, original source, E15/E16 human-score outcomes, probability calibration, E22 scorers, native NDU, Neuron, Artifact CAS, FinalUse or main.

## What the new exact-original-archive replay actually did

Downloaded the **original 33-case pretrained ModernBERT source-blind ZIP** from completed run, artifact `11946621518`, SHA `1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`; and ALL four originally trained E16 held-fold ZIPs:

| Fold | Original artifact ID | Entire original ZIP SHA-256 |
| --- | ---: | --- |
| 0 | 11950242845 | `1ad37a6ce022e8d051467db52a59a9ea2a683aa57f04c9b51867f4c7db136ab9` |
| 1 | 11950188043 | `67dff7033303ddef4fedd06b8b4e7af105b24d154eb4069072c69525bca2991e` |
| 2 | 11949868664 | `990ba455578abe57ac8cb031633d3a73cc1dd488f5a418f20045334f845b9eaa` |
| 3 | 11950201953 | `ff172d1c44f31c134c5793520127a9fd166d9ad26138f88f86ce95191550f934` |

For each fold, E24 separately checks the whole original ZIP SHA, inner `held-prediction.json` SHA, `source-head.txt` exact E16 code SHA, genuine `48` train updates per five-param Head, original 33 candidate IDs/questions/source groups, feature/prelabel source identifiers, all fit/held CPU counters, and negative authorization flags. Re-hashed but changed original model bytes cannot substitute for these exact known external archives.

It **does not access the original MultiRC human label parquet or the independently scored E15/E16 human-score ZIPs**, and performs **zero new pretrained Encoder forwards or Head training updates**.

### Observed original model discrimination, not accuracy

| Actual historically trained E16 Head | Original 5-param Heads | Held original questions with one hard class | Questions with both predicted classes | Per-fold total training updates | Original train CPU summed | Original held CPU summed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| centered_raw_5 | 5 | **8/8** | 0/8 | 192 | 6,559,875 ns | 102,439 ns |
| **centered_scaled_5** | 5 | **2/8** | **6/8** | 192 | 6,503,049 ns | 113,458 ns |

The unscaled Head's largest within-question score spread is approximately `0.00256083` and the scaled Head's largest is approximately `0.31131379`. **Neither Head has exactly invariant floating scores across any entire original question**. Thus a flat hard class is a property of this frozen decision boundary, not evidence that the floating representation is mathematically incapable of carrying answer distinctions.

**This is the critical new finding:** train-only scaling can stop hard-class collapse while holding actual Head parameter count and update steps constant on this retrospective family. The previous **original HUMAN scored** E16 data report `centered_scaled_5=20/33` versus frozen mean-pool `17/33` and unscaled `13/33`, but **ALL three rescued candidate counts relative to frozen come from ONE original passage** (passage deltas `[0,+3,0,0]`). Do not treat those dependent answers as independent gain, verified whole-question success, statistically powered generalization, lower total-cost inference or a new E24 human-score result. These are **existing historical E16 outcomes**, not numbers supplied by the new no-label replay.

The sanitized true original ZIP observation `E24_ORIGINAL_E16_BLIND_GEOMETRY_20261015.json` stores no raw candidates/answers/features/weights and binds the full local diagnostic's SHA-256 `15a4859029af1a97e18042c6f930c63fe2a6ea8eb330246d5acf14cb55ceb4d0`. This SHA is a local reproducibility digest, **not an independently authenticated original model host**.

## Physically executed tests and hosted two-stage reuse

`e24_e16_original_geometry.py` and `test_e24_e16_original_geometry.py` were independently run against all FIVE authentic ZIP files. **10/10 normal and 10/10 `python -O`** tests passed, zero skip/errors, including whole ZIP/inner seals, case/group/cardinality, two-class question census, original train/held CPU, missing/reordered folds, tampered model ZIP, false independent E22 re-signed report, nonfinite/duplicate JSON, unsupported benefit/authority and create-only output. Source code/test Git blobs are independently verified byte-identical to locally executed files:

- E24 source `4c32c55a4bbce8680451e1e68e53c357b16f2ea0`
- E24 tests `69b3408baa7c52b033dbe6db729cda438feff03f`

The *existing E22 eight-arm* GitHub Actions workflow adds E24 tests **in its original label-blind job**, using the same exact E16 archived ZIP environment and E22 original model artifact. After the E22 blind seal, E24 **independently re-opens** all five original ZIPs and compares every `centered_raw_5` and `centered_scaled_5` per-candidate model probability **and the eight model-fit CPU receipts** against E22's separately constructed 33-case blind report. E24 emits a create-only proof and a SHA; the separate original human-score job verifies that E24 proof's SHA and DENY_ALL status before it downloads any held labels. E22 original complete-question scoring and postseal E15/E16 human-score re-training/independent review remain exactly in place.

The E24 extension does **not** claim the newly queued source-HEAD or synthetic-merge Actions jobs passed until their current SHA actually completes.

### Original ZIP-backed reproduction

```sh
cd qualification/shared-stem-system2-architecture
export HEPTA_E24_SOURCE=/actual/original-modernbert-prelabel.zip
export HEPTA_E24_FOLD_0=/actual/e16-held-fold0.zip
export HEPTA_E24_FOLD_1=/actual/e16-held-fold1.zip
export HEPTA_E24_FOLD_2=/actual/e16-held-fold2.zip
export HEPTA_E24_FOLD_3=/actual/e16-held-fold3.zip
python3 -m unittest -v test_e24_e16_original_geometry
python3 -O -m unittest -v test_e24_e16_original_geometry
python3 e24_e16_original_geometry.py \
  --original "$HEPTA_E24_SOURCE" \
  --e16-0 "$HEPTA_E24_FOLD_0" --e16-1 "$HEPTA_E24_FOLD_1" \
  --e16-2 "$HEPTA_E24_FOLD_2" --e16-3 "$HEPTA_E24_FOLD_3" \
  --out /new/create-only/e24-true-original-report.json
```

**Next P0 admission hurdle:** new source/passage groups and evidence-deletion/answer-swap re-encoding with heldout *whole-question*, question-cluster uncertainty, original token/patch Reader signal, complete train+source+feature+worker costs, and native System2-vs-cheap equal-work controls. The old four original passages alone cannot qualify this. Keep `production_accepted=false`, `model_selected=false`, `NDU_System2_reader_sufficiency_admitted=false`, `DENY_ALL`. No large-model equivalence or production promotion.
