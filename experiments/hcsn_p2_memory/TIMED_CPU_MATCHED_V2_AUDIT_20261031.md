# P2 measured-CPU-matched physical FIRE follow-up — 2026-10-31

**RESEARCH_ONLY / DENY_ALL / NO_GO.** Stacked on pilot [#4504](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4504), parent HEAD `d07405a4d4582ca763a517d7828170c49121e498`. The new protocol `TIMED_CPU_MATCHED_V2_PROTOCOL_20261031.json` was committed **before** these v2 runs at `4dc1f71dbbd8efb9c4e90f346c1fe97bcac3a80c`. This protocol was developed **after inspecting the v1 failures**: it is a preregistered *non-blind exploratory follow-up*, not independent blind confirmation.

## Corrected experiment

The preceding #4504 used equal 2,000 optimizer updates but both arms exhausted that cap **before** using the 25-second training-CPU budget. This time the preregistered cap is 8,000, with untouched seeds 2,3,4. Two arms are trained independently from the **identical 5,186-parameter initial weights**, identical physical Brownian FIRE trains, observation and mask datasets, optimizer Adam lr=.006, batch 24 and batch-index seed; the arms differ in whether each FIRE updates content **at its real chronological timestamp** or its count is applied at observation. The timestamp model is a *batched, differentiable PyTorch float32 operator*, not a differentiated Brownian hitting-time sampler.

Every arm includes data preparation plus optimization in **25 process-CPU seconds** and stops immediately after consuming that budget, not a fixed update count. Evaluation CPU is measured separately; 128-actor T16 ID and T32 OOD panels are identically seeded within each pair. This fixes only a narrow *CPU train-budget accounting* deficiency, not all compute, energy, or scientific fairness gates.

## Frozen snapshot: 12 actual trained runs / six valid CPU-budget pairs

| Task / seed | Aggregate ID | Timestamp ID | Aggregate OOD | Timestamp OOD | Optimizer steps (aggregate / timed) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Copy 2 | 98.44% | 97.66% | 100.00% | 58.59% | 4,124 / 2,431 |
| Copy 3 | 100.00% | 96.88% | 97.66% | 86.72% | 4,375 / 2,535 |
| Copy 4 | 99.22% | 85.16% | 85.94% | 58.59% | 4,484 / 2,466 |
| MQAR4 2 | 58.59% | 57.81% | 56.05% | 53.32% | 4,350 / 2,523 |
| MQAR4 3 | 55.08% | 54.49% | 54.69% | 58.01% | 4,380 / 2,428 |
| MQAR4 4 | 56.45% | 56.25% | 55.27% | 56.45% | 4,344 / 2,325 |

Each observed training CPU is between **25.0000 and 25.0094 seconds**. All six final-snapshot pairs satisfy the prespecified ≤5% relative paired CPU gap, equal model/data fingerprints and no step-cap truncation. Copy OOD has three negative paired effects (**−41.41, −10.94, −27.34 percentage points**, mean **−26.56 pp**). MQAR4 OOD has mixed signs (**−2.73, +3.32, +1.17 pp**) and does not establish an advantage. In particular, **do not present passing CPU accounting as passing the P2 scientific gate**.

**Source/repro:** `timed_cpu_matched_v2.py` (Git blob `a62d8e5056cd9c66947815b4eb8b5af9cf3a84de`) and `test_timed_cpu_matched_v2.py` (Git blob `fdc270e55e894d9018314218c18679d75246afc4`) were remotely read back byte-identical to the executed local files. **66/66** local targeted tests PASS, no skips, using the earlier disclosed reconstructed HX subset, not a complete upstream repository checkout, full CI, Rust, GPU or Joules testing.

`TIMED_CPU_MATCHED_V2_12_RUN_MANIFEST_20261031.json` retains 12 exact SHA-256 file identities and primary accuracy, BCE, CPU, step-count and matched-data hashes. A separately frozen original-byte archive of all 12 JSON records, sources and SHA256SUMS has SHA-256 `e176e8e29467fb8e71662d1a41c06bfc85e8e850152b0bb1dd1321b9bb0e36a9`; the manifest is **not falsely called byte-for-byte raw JSON**.

## Reproducibility warning: observed mutable-output discrepancies

**Do not ignore this:** Three local filenames had original stdout-reported content digests differing from subsequent on-disk inventory. The cause was not independently established. The earlier digests/outcomes and later immutable snapshot details are preserved as `TIMED_V2_OUTPUT_DISAGREEMENT_20261031.json`. The frozen 12-file snapshot can be internally cross-checked, but earlier overwritten bytes were not recovered; hence strict lossless provenance across **every attempted execution** is **OPEN**. Next recorder must create unique output names, use atomic create-only writes and signed/attested run manifests, retaining rather than replacing reruns.

## Remaining scientific blockers

- **P0 OPEN:** coupled global financial HX self-consistent free boundary, continuum obstacle, rigorous interval error and low-precision active-set gradient.
- **P1 OPEN:** causally isolating Call/Risk/Margin gains with many paired seeds, fully matched backbone/cost and independent tests; negative #4500 pilot retained.
- **P2 OPEN:** honest fully measured training CPU pairing is observed in *this exploratory snapshot*, but actual memory superiority, robust MQAR4/long Selective Copy OOD, overwrite tests, causal event-time benefit and crash-journal/rollback security are unproved. Three observed local output replacement discrepancies require provenance repair.
- **P3 OPEN:** real four-modal encoder with paired temporal/semantic alignment and OOD.
- **P4 OPEN:** native Rust/CUDA, true 64/256/1024/4096-cell throughput, p95/p99, peak RSS, joules and crash recovery.
- **P5 BLOCKED:** no hybrid expansion until independent quality+total-cost gate passes.

Research only: `production_activation=false`, `all_scientific_blockers_closed=false`; **draft/unmerged**. No self-declared P0–P5 gate closure.

## Reproduce focused gate

```bash
python -m unittest -v experiments.hcsn_p2_memory.test_timed_cpu_matched_v2
python -m experiments.hcsn_p2_memory.timed_cpu_matched_v2 --task copy --seed 2 --arm aggregate_count --output /tmp/copy_s2_count.json
python -m experiments.hcsn_p2_memory.timed_cpu_matched_v2 --task copy --seed 2 --arm physical_event_timestamp --output /tmp/copy_s2_timed.json
# Continue all seeds=2,3,4; tasks=copy,mqar4; 2 arms; validate each pair.
```
