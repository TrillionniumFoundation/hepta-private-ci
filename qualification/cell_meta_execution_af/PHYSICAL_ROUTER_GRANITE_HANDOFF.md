# Hepta Meta — exact public-source Granite feature bridge (research/DENY_ALL)

This additive increment stacks on the **unchanged** actual four-arm PyTorch Router
trial in PR #2090, itself stacked on A–F shadow PR #1796. It does not create a
Neuron/NDU/Selector/CellSplit owner, selected artifact, original CAS effect,
Final-use grant, CNS route, production model invocation path or release gate.

## Source and actual execution

1. Fetch exact public dataset `szhuggingface/ag_news@98c532231d96ae10e176a909192ecac548949288`, two SHA-pinned parquet files. Rebuild and SHA-check the **original** 224-row source panel
   `2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4` using frozen research source checkout `f8d168a7689eb3624d97c44751791badd069e521`.
2. Stage **real** `ibm-granite/granite-embedding-97m-multilingual-r2@835ad14087e140460703cf0fae09f97d469d65c2`, rehash every downloaded allowed local file against upstream LFS SHA-256 when available, and refuse missing model tensor shards/config/tokenizer. Offline-only inference calls the existing `FrozenCompactStem` from byte-pinned reviewed checkout `e05f939f65fb76f6bdbf7470eef7e63b77284dcd` with **joint** State+Question+Options and declared CLS+L2+Q24 representation; no remote Python execution, pickle, silent token truncation or model substitution. All 224 source rows require a real feature output. The claims about actual model calls remain self-reported until an independent trusted runtime/host attests them.
3. Validate 224 exact label-free 384D signed-Q24 feature rows, scope/source/case IDs, pretrained revision, model-file inventory hash and 512-token ceiling. Derive **one** shared feature table and reuse it across all four arms and three registered seeds: `41, 47, 53`. Do not reload/re-encode once per Cell.
4. Fixed, non-fitted 384→64 contiguous-six Q24 mean projection. It is intentionally **lossy**; any relative trial performance describes the projected 64D feature path only and does not certify an optimal Granite Stem. The original model weights, raw source texts and token IDs are never included in published research artifacts.
5. Invoke exactly the existing PyTorch four-arm trial (`no_change / fixed_router / learned_router / adaptive_split`, 24+24 SGD steps) and its independent FP32 numeric replay. A second, pure-stdlib reviewer independently reconstructs all 224 labels and 64D projected vectors from the frozen original source and Q24 feature table. It does not import Torch, the converter or the trainer.

## The chronology and OOD limitation is **not optional**

The original 224 records contain 128 train, 32 calibration and 64 test, not calendar-based forward observations. We bind:

| Downstream protocol slot | Real public-source rows | Number |
|---|---|---:|
| `old_train` | first 64 original train | 64 |
| `new_train` | remaining 64 original train | 64 |
| `old_retention` | first 16 original calibration | 16 |
| `future_1` | first 32 original test | 32 |
| `future_2` | remaining 32 original test | 32 |
| `ood` | remaining 16 original calibration | 16 |

The `step` values are **artificial ordering labels** to fit the predecessor
simulation interface, not observation timestamps. Both `future_1` and `future_2`
are **retrospective test slices**, not prospective future windows. `ood` is a
same-source calibration **placeholder**, not an independently sourced OOD test.
The independent reviewer rejects any receipt that turns those claims into true.
None of these results can satisfy NDU prospective improvement, negative transfer
from unseen task families, unbiased out-of-distribution calibration or production
selection. The cross-sectional public original was already studied in historical
runs, so this experiment cannot be predeclared as never-seen independent science.

## Resource and numeric evidence boundary

Physical research instrumentation includes real pre-trained model calls and
runtime-observed wall time, an exact 224-row tensor path, Head training and CPU
time, actual 64D Head/Router weights, forward-row and optimizer-step counters,
per-arm paired FP32 probabilities and matched case-level cross-sectional scores.

Unlike a completed equal-work scientific experiment, this design still **does
not match total Head forward FLOPs, Stem load time, search/threshold-tuning cost,
migration/recovery, full resident memory, energy or target-host p99** among
all arms. A shared Encoder can save weights and reencoding, but it does not make
Head compute free. A small retrospective Brier difference, a passed checksum or
a convenient split threshold proves no advantage for adaptive Meta Networks.

All outputs are read-only and retain:

```json
{
  "future_window_prospective": false,
  "independent_model_origin_verified": false,
  "real_ood_verified": false,
  "ndu_selection_authorized": false,
  "production_admission": "BLOCKED",
  "authority_posture": "DENY_ALL"
}
```

## Local tests (no pretrained inference)

From repo root with PyTorch 2.10 CPU:

```sh
PYTHONPATH=. OMP_NUM_THREADS=1 python3 -m unittest discover -v \
  -s qualification/cell_meta_execution_af -p 'physical_router_real_tests.py'
```

Those tests use synthetic fixtures and actual small Torch SGD for a numerical
smoke test. The job `real-granite` alone tries the real pinned public Encoder.
Never inherit a green status from an earlier source SHA; judge the latest exact
HEAD and prospective base merge. If downloads, weight staging, original
input lock, model forward or independent replay fail, **preserve failure evidence
and stop**; do not substitute mock Encoder outputs.

Next acceptance requires a prospective outcome dataset with independent signer,
pre-label holdout commitments and relevant OOD groups; real no-change production
counterfactual; fully cost-matched fixed sparse MoE; independent NDU; signed
Artifact CAS + Worker + Supervisor/CNS + Final-use and target-host 64..4096 Cell
measurements. No merge/promotion/physical split is authorized by this handoff.
