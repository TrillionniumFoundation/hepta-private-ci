# P2 physical process cost: real Linux wait4 observations (RESEARCH / DENY_ALL)

This study extends the existing original-source-paired five-arm review and the
operation-count frontier. It does **not** create a second Cell owner, an NDU
Evaluator/Selector, a real Granite model, or production authority. Its sole
additional observation is **CPU/RSS for a real, fresh OS process per arm**.

## Exactly what executes

1. Validate the existing three-seed original-case, five-arm FP32 and route evidence.
2. For each registered seed 41/47/53 and each of the five named arms, spawn a new
   `python -m qualification.cell_meta_execution_af.physical_router_os_meter`
   child. Strip ambient credentials, forbid network model fetch through environment,
   provide source identity, enforce a bounded deadline; *never auto-retry* a failed
   or uncertain child.
3. Inside a child, independently replay the original historical soft, posthoc,
   hard-trained and frozen artifact lineage, then physically re-execute one arm.
   For trained arms repeat **both** stages with the same seed and optimizer; for the
   real frozen stage-1 arm, perform only inference from the saved old parent.
   Compare **all** FP32 bytes, stage-1 copy, route bitsets, Head and Router meters,
   all retrospective source-case probabilities and metrics, permitting only the
   corresponding measured CPU-time field to differ.
4. Parent performs `os.wait4` and records the kernel's user CPU, system CPU and
   process-peak RSS (Linux `ru_maxrss` KiB converted to bytes), plus parent
   monotonic elapsed time. This avoids merely copying a child's self-reported
   CPU/memory JSON.
5. Write one create-only shard per seed. A separate joiner requires all **three**
   seeds, all **five** registered arms, exact original-source/weights/route hashes,
   finite OS counters and unchanged nonauthorizing flags. A partial failure
   cannot be imputed as success. Resource samples and original data are distinct:
   three correlated training seeds do not create three independent datasets.

All subprocess measurements are **fresh Python process startup, complete source
replay, model import and measured arm execution together**. They are not a
training-only CPU microbenchmark, per-call p99, a real Encoder forward budget,
GPU energy, system watts, true production RSS, or a controlled platform TCO.
In particular, the frozen arm reuses the predecessor's stage-1 training and does
not bill that training to this fresh process; comparing these timings as full
lifecycle parity is invalid. Each child is executed serially on the same host,
so CPU run-to-run noise and shared caches remain confounders. No independent
OS/host signer exists; kernel sample collection by the local parent is not a
trusted operator acceptance receipt. Do not treat these numbers as evidence
that an adaptive split outperforms the stronger fixed Top-1 baseline.

## Local physical pilot (synthetic Q24-like toy features, 64 rows per cohort)

Three seeds and 15 real Linux child processes **completed** with exactly
replayed registered final tensors and per-case predictions. The median figures
below are descriptive and environment-specific. Each process also includes
Python/Torch startup and the complete original-source independent review.

| Research arm | Median OS CPU seconds | Median OS process peak RSS (MiB) |
| --- | ---: | ---: |
| Frozen old-parent stage1 | 1.993 | 255.3 |
| Unsplit continued learning | 2.813 | 314.1 |
| Fixed Top-1 | 2.872 | 314.2 |
| Learned Top-1 | 2.871 | 314.7 |
| Adaptive Split | 2.783 | 314.3 |

These observations neither match total compute nor establish a reliable ranking
on other hosts. The learned Router and adaptive branch can differ substantially
on new tasks, while the original public AG News dataset is **retrospective**.

## Exact GitHub workflow and local command

The original `.github/workflows/hepta-cell-meta-granite-real.yml` now runs these
isolated stages only **after** the pinned actual Encoder forward, original
five-arm numeric replay, independent original-source-paired scoring, and original
observed-work lower-bound gate pass. It retains every completed shard on failure
and publishes the join only after all 15 children succeed.

```sh
# The exact original paired reports must already exist in /path/to/panels.
for seed in 41 47 53; do
  python qualification/cell_meta_execution_af/physical_router_os_meter.py \
    --bundle-dir /path/to/panels --seeds "$seed" \
    --out "/path/to/panels/$seed-os-meter.json"
done
python qualification/cell_meta_execution_af/physical_router_os_meter.py \
  --bundle-dir /path/to/panels --join-shards /path/to/panels \
  --out /path/to/panels/os-meter-joined.json
```

The offline numeric unit tests use **synthetic** source fixtures and real CPU
subprocesses; source data is not allowed to exercise provider/tool/effect
execution. A prior Source/CI green result or internal checksum does not grant
independent model/host provenance, a physical Cell Split, Final-use, NDU
selection or operator acceptance. All outputs retain
`production_admission=BLOCKED`, `authority_posture=DENY_ALL`,
`resource_or_model_winner_certified=false`.
