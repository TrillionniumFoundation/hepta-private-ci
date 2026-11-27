# HCSN P1: 12-new-seed paired 8-arm confirmation (2026-10-31)

**RESEARCH_ONLY / DENY_ALL / NO_GO.** Stacked on Draft #4500 exact parent HEAD `47e8501c3d6a7f08fdd9595c70a2904bf6274688`. Research-only: no production permissions, previous metrics, trained weights, protected main, or CI workflow changed.

## Pre-run frozen registration and sample-size defect

`CONFIRMATION_PROTOCOL_12SEEDS_20261031.json` was committed at `665a9cb583bf717786ee696956091cceef177140` **before the first confirmation training**. Its 12 new seeds `100..111` are disjoint from pilot `0..4`, and its fixed training budget is 120 updates, batch 48, 512 train examples, 384 ID/OOD test examples, 561 trainable parameters, shared frozen scalar encoder, trainable width 20, paired initializations and signed local slope +1.

Eight registered arms (ordinary, Call, Risk, Margin, three two-channel pairs, all three), two fixed tasks (Selective Copy, Key-Value Overwrite), 12 seeds = **192 complete trained cases**. The Holm family is exactly **14** paired two-sided exact sign-flip tests, with `alpha=0.05`. In the original five-seed pilot the smallest attainable two-sided paired signflip p is `2/2^5=0.0625`, already greater than `0.05` even without multiplicity correction; it was mathematically incapable of crossing the registered significance gate. Twelve seeds make a small enough p *possible* but not guaranteed.

## Executed training and entire failure record

All four planned batches **48/48 each, 192/192 total**, completed using the preexisting pilot `p1_factorial.py` exact Git blob `eb81a440d0cd583b9f296788742c3c5be120e965`, with `p1_confirm12.py` executing the frozen seed/update/initialization matrix. Python 3.13.5 / PyTorch CPU single-thread, local reconstructed HX support rather than exact byte-identical upstream `hx.py`; no full repository CI. No mid-run parameter selection or invalid-run discard.

Per-batch raw JSON SHA256: `360fa2d2d868e4c3389bdef376dba34e478f22e9967201c01e56cfc9f7dc7afb`, `3734b096444d433d7967d3235e71fa5203018c124a7807f2b76697c174e0bf73`, `4c70bdac85cdda205f3c96a4ded10078a12be0d9de139ae8fda6328321755b26`, `076e39339645c1af8f35461ea942a028791a9fc8cf18fe88891c047aa7eef014`. Full 192-training 155,392-byte JSON SHA256: **`2fd6989c10dae901da735a05694e2e25698dfe3ad124884d1ec7ab10a561d7ef`**. Full raw training JSON and all four batches are retained in a separately provided lossless archive; the GitHub PR contains the **lossless per-seed ID/OOD correct-count matrix**, **not** full model weights/logits or every optimizer checkpoint. Do not falsely describe this GitHub compact matrix as the full raw output.

## Independently recounted efficacy and CPU

The primary runner originally formed signflip from float32 accuracies; near-tied differences can change the counted exact tail at integer resolution. A subsequent read-only independent count audit used **integer correct counts out of exactly 384 test positions** for each seed and then recomputed all `2^12=4096` paired sign assignments for each of 14 tests. It did not modify any training job, model checkpoint, seed, input, alpha or hypothesis family. Canonical compact uncompressed JSON SHA256: **`176f92cb09a898a075e8f560fc27a2de02335082faec510092713dfad61093e8`**; gzip/base64 evidence in `P1_CONFIRM_COMPACT_12SEEDS_20261031.json.gz.b64`, independently audited with `p1_confirm_exact_count_audit.py`.

| Heldout OOD task | Ordinary | Full all-three | Mean paired gain | Two-sided exact p | Holm-adjusted p |
| --- | ---: | ---: | ---: | ---: | ---: |
| Selective Copy, T28 | 83.7891% | 90.7335% | +6.9444 pp | 49/256 = 0.191406 | **1.0** |
| Key–Value Overwrite, T28 | 81.2500% | 82.5304% | +1.2804 pp | 23/512 = 0.044922 | **69/128 = 0.539063** |

The seven remaining arms (including negative values) stay in the compact matrix. For overwrite, Risk-only has uncorrected p `9/2048` and adjusted p `63/1024=0.06152`, while Risk+Margin has `5/1024`, adjusted `65/1024=0.06348`; **both miss** the familywise 0.05 threshold, and their effects are below the +2 pp practical floor. No arm is selected as post-hoc winner.

Mean *recorded optimizer/pilot CPU* seconds per model: Copy ordinary `0.204711`, all-three `0.262782` (about +28.4%); overwrite ordinary `0.205857`, all-three `0.200600`. Financial basis/table creation, full host power, GPU energy and end-to-end deployment costs were not equivalently metered. **Same updates ≠ full-cost fairness.**

### Independent local reproducibility

```sh
python -m unittest -v experiments.hcsn_p1_mechanism.test_p1_confirm_exact_count_audit
python -m experiments.hcsn_p1_mechanism.p1_confirm_exact_count_audit \
  experiments/hcsn_p1_mechanism/P1_CONFIRM_COMPACT_12SEEDS_20261031.json.gz.b64
# Expensive original training replay, one group at a time:
python -m experiments.hcsn_p1_mechanism.p1_confirm12 --group 0 --out-dir /tmp/p1confirm
python -m experiments.hcsn_p1_mechanism.p1_confirm12 --group 1 --out-dir /tmp/p1confirm
python -m experiments.hcsn_p1_mechanism.p1_confirm12 --group 2 --out-dir /tmp/p1confirm
python -m experiments.hcsn_p1_mechanism.p1_confirm12 --group 3 --out-dir /tmp/p1confirm
python -m experiments.hcsn_p1_mechanism.p1_confirm12 --combine --out-dir /tmp/p1confirm
```

Four new audit regression methods **4/4 locally PASS**, including structural completeness, five-seed mathematical infeasibility, missing/truncated matrices, tampered counts/p-values/Holm refusal. New audit source and tested test logic were read back as exact Git blobs; the test import and evidence filename are appropriately adapted for repository paths, with the resulting new test blob separately verified. The executed runner source matches the published Git blob byte-for-byte. Source and compact artifact integrity are verifiable via Git blob and SHA256 without importing a neural model.

## Strict admission outcome

**Registered P1 gate FAILS**: Full HCSN is not significant on either task after 14-test Holm adjustment; Overwrite is below +2pp, actual whole-platform cost matching and real dynamic physical-time HCSN causal separation are still unproven. These negative results **do not imply a universal impossibility theorem** for the architecture, only a failure within the frozen, bounded benchmark.

P0 original coupled financial obstacle/global precision OPEN. P2 true physical FIRE memory, long OOD and durable host restore OPEN. P3 four real paired encoders OPEN. P4 Rust/GPU/Joules 64/256/1024/4096 OPEN. P5 hybrid equality-cost advantage BLOCKED. `production_activation=false`, `all_scientific_blockers_closed=false`. Keep Draft, unmerged.
