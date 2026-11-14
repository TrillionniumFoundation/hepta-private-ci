# P0 four-Stem physical evidence: independently recomputed 128-case cross-sectional score

**Research / shadow / DENY_ALL. Not a production model selector or genuine prospective-time learning experiment.** This independent consumer does not import the Granite/mmBERT model/trainer, original scorer, original label selection code or any model weights. It reuses the original immutable public AG News val2 128-case labels from a separately archived Actions artifact and recomputes the probabilities from sealed successful new Granite/mmBERT pretrained model reports.

## Pinned provenance / exact host runs

* Pre-existing Gemma2/Laya421 physical reference: [run 38541658096](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38541658096), artifact **11886761368**, immutable ZIP SHA-256 `e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d`.
* Newly completed Granite 97M/mmBERT-small paired physical experiment: [run 38570704386](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38570704386), artifact **11908591037**, ZIP SHA-256 `d8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa`.
* Immutable new cross-sectional panel canonical SHA-256 `8090d3b006364f3da780cea7f1bb91827e8024776e175aa99f5636597bfa644a`, 64 world + 64 sports. The scorer retrieves test labels only from the *historical Actions archive*, not from the new physical model reports. The full 352 source-only rows are **not** included in the newer ZIP and cannot be independently reassembled from that archive alone.
* Both new physical arms report 352 encoder forwards and 384-dimensional Q24 outputs with 40-step actual head updates. Current exact actual checkout SHA is inside the newer ZIP; the zip is originally hosted, not an authenticated external signer.

## Actual independent recomputation (new 128-source cohort)

| Arm | Correct | Accuracy | Brier ↓ |
|---|---:|---:|---:|
| Granite 97M frozen gated | 64/128 | 50% | 0.250020 |
| Granite 97M trained gated | **122/128** | **95.3125%** | **0.039888** |
| Granite 97M trained linear | 119/128 | 92.96875% | 0.114110 |
| mmBERT-small frozen gated | 64/128 | 50% | 0.250021 |
| mmBERT-small trained gated | 73/128 | 57.03125% | 0.249856 |
| mmBERT-small trained linear | 70/128 | 54.6875% | 0.249876 |
| Historical Gemma2 trained Head (different profile) | 120/128 | 93.75% | 0.248814 before post hoc logit scale |
| Historical Laya421 frozen baseline (different profile) | 124/128 | 96.875% | 0.020127 |

Granite vs mmBERT trained-gated: 53 unique wins / 4 unique losses, exploratory **uncorrected** two-sided exact McNemar p≈5.91e-12 (conditional on the paired fixed 128 rows). Granite vs historical Gemma trained: 3/1 unique wins/losses, p=.625. Granite vs historical Laya421: 1/3, p=.625. Case correlations, multiple testing and source-family shift are not controlled by those exploratory numbers.

The new Granite process reports 37.16s complete process CPU, 4.26s model-load wall, 1,096 MiB Linux process peak RSS, 43.45/56.35/68.20ms observed single-Encoder-forward p50/p95/p99 over 128 val2 samples. mmBERT reports 55.90s process CPU, 6.62s model-load wall, 1,102 MiB RSS, 66.13/83.42/106.54ms p50/p95/p99. These are **single-input model forward** statistics, not end-to-end p99 of 4,096 Cells or two batches of equally costed Heads; no GPU/energy records. Previous Gemma/Laya inferred per-source batch allocations are not directly comparable to single-input p99.

## Negative evidence and strict qualification

* Only a **same-public-family cross-sectional** new panel, not a true future-time/independent-natural-source retention study. Source/label signer and foundation pretraining contamination exclusion unverified. Training budgets, Readout/Head parameterization and full lifecycle compute differ from historical Laya/Gemma arms.
* `pre-score-seals.sha256` binds original archived reported predictions. It cannot prove which model weights were loaded or who generated the source labels. The independent numeric evaluator cannot re-run original model weights from the ZIP alone.
* Missing 64 original-test labels and the 160 train/cal original input rows in the new ZIP mean only val2 128-row predictions can be independently re-scored from the two fixed archives. The successful original scorer's test-64 summary is still useful observational context, **not** independently certified by this component.
* No global optimum Stem, no live signed inference/control Q24 receipt and Neuron checkpoint/witness, no multimodal natural-task gain, no 4,096 full Encoder+Head physical frontier, no P5 continuous-FBSDE utility, and no production FinalUse. `p0_accepted=false`, `p1_accepted=false`, `production_accepted=false`, `authority=DENY_ALL` remain locked.
* `blocking-ci` on #1923 has actual failures: a Torch-dependent P0 test imported in the NumPy-only lane, formatting defects in three YAML files, cargo-deny advisories and Bazel failures; any one green research job cannot waive these controls.

## Reproduce

```sh
export HEPTA_P0_HISTORICAL_ZIP=/approved/archived/11886761368.zip
export HEPTA_P0_PHYSICAL_ZIP=/approved/archived/11908591037.zip
python3 -m unittest discover -s qualification/p0-four-stem-replay -p 'test_*.py' -v
python3 -O -m unittest discover -s qualification/p0-four-stem-replay -p 'test_*.py' -v
python3 qualification/p0-four-stem-replay/independent_replay.py \
  --historical "$HEPTA_P0_HISTORICAL_ZIP" --physical "$HEPTA_P0_PHYSICAL_ZIP" \
  --output /new/sanitized-audit.json
```

The new CI downloads the exact two existing Actions artifacts read-only and uploads only the sanitized numeric audit and test logs (not duplicate raw public text, private weights or source records). Reuse the established P0 research branches; no second model loader or model-selection owner.
