# V10 reproduction and evidence identity

Run from the full repository root with Python 3.12, NumPy and SciPy; historical AV additionally uses Torch. Versions observed in this run are recorded in `RUNTIME.json`. The read-only `/tmp/hcsn-torch-runtime` path was a session-specific dependency location, not a portable package or part of the published source.

Use new output directories. Existing plans, final/selected weights, failed attempts, source snapshots, compressed traces and cost receipts are immutable evidence. Do not overwrite a frozen result or alter its source hashes to make it execute under changed code.

## Read the completed evidence

- `SOURCE_CONVERGENCE.json`: primary v9 base and separately recovered historical-v9 archive/remote tree identities.
- `frontend/RECOVERED_PACKAGE.json`, `HISTORICAL_RECOVERY.json`, `HISTORICAL_EXCLUSIONS_PARTIAL.json`: actual recovery scope, including missing v6/new-capture evidence.
- `risk/results/closure001/`: budgeted output reserve, exact executor diff, 144 normal runs, two actual over-budget probes and raw audit.
- `joint_retrain/results/development001/`: true joint dynamics/content fitting, all candidates, selected models, heldout predictions and source freeze.
- `persistent_renewal/results/development002/`, `extension001/`, `confirmation001/`: distinct base, validation-only extension and fixed 384-world confirmation. Do not pool their estimates or relabel the expanded confirmation as the original preregistration.
- `av_analytic/results/development001/`: 70 fits, selected and final weights, copied original inputs/heads and 3,240 historical executions. `constant001/` is a separate post-hoc reference, not a replacement for frozen B.
- `economics/SUMMARY.json`, `LEDGER006.json`: 67 measured local phase receipts (2124.153532 CPU seconds), audit-tail accounting and exact scope. The 384-world batch wall is a time window, not the sum of overlapping shard wall times.
- `review/`: independent state/probability/score reconstruction, corrected source-identity sidecar, target-shift diagnostic, interface supplement and CI static/actual scope.

Raw gzip files are committed as their original compressed bytes. No rerun or recompression is needed to inspect the published evidence. The largest individual files remain below the connector request bound after base64 encoding; delivery inventory verification binds their exact Git blob, size and mode.

## Fresh historical AV replay without the original recovery path

The published AV output contains all eleven prepared input files: legacy train/validation/test NPZs, both common-head checkpoints and each task's training/validation tensors plus source metadata. Clone just that byte-bound input set into a fresh output:

```bash
python experiments/hcsn_v10_closure_20261101/publication/prepare_av_replay.py \
  experiments/hcsn_v10_closure_20261101/av_analytic/results/development001 \
  /tmp/hcsn-v10-av-new
```

Then use an environment with the compatible Torch runtime installed:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_v10_closure_20261101.av_analytic.campaign train --output /tmp/hcsn-v10-av-new
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_v10_closure_20261101.av_analytic.campaign evaluate --output /tmp/hcsn-v10-av-new
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_v10_closure_20261101.av_analytic.audit /tmp/hcsn-v10-av-new
```

`campaign plan_at` verifies the published candidate source and all copied inputs before training/evaluation. The original byte-bound recipe and seeds are preserved; runtime timings and serialization metadata can vary. No claim of fresh AV confirmation follows from reproducing historical recordings.

## Fresh finite-model experiments

Component README files contain the exact `prepare`, `data`, `train`, `evaluate` and audit commands. The original renewal candidate needs the inherited v2 source segments in the repository; `campaign prepare` extracts only explicitly listed NumPy/SciPy definitions and binds their source hashes. Current source corresponds to the optimized implementation; first-preflight source is retained under its own snapshot.

For the validation extension, use `persistent_renewal.extend` with a completed fresh base fit; it reproduces the original prefix of the three continued training trajectories. For the fixed confirmation, use `persistent_renewal.confirm` on frozen completed extension models. Freeze all shard seeds and the declared fixed size before execution, run every shard, then aggregate once. Existing confirmation results are available directly and need not be regenerated merely to review this work.

The CI-specific finite-model replay is independently callable without elevated privileges:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_v10_closure_20261101.economics.ci_joint_replay --output /tmp/hcsn-v10-ci-joint-new
```

It copies only frozen model/data artifacts to the new directory, checks source/input identities and compares the new summary against the committed finite-model reference. This command alone does not measure cgroup memory.

## Measured lifecycle and isolated memory

Use `economics/stage_meter.py` for each new local formal phase, with a unique study/stage/attempt directory. Only its outer wait4 CPU is additive. Nested component/monitor CPU is diagnostic and already included. The outer launcher imports, CONFIG writing and final PHASE receipt serialization lie outside that boundary. Initial development/recovery and missing historical costs remain unknown.

`.github/workflows/hcsn-v10-memory-qualification.yml` runs the narrowly identified frozen joint profile. It uses read-only repository permissions, sparse exact-head checkout, existing action pins, explicit dependency versions, a private cgroup with pre-exec membership gate, unprivileged task execution and bounded cleanup. The kernel counter is cgroup memory charge including attributed cache/kernel, not RSS/PSS or a uniquely deduplicated physical-memory metric. Artifact identity, actual success, empty-group/cleanup/OOM status and numerical equality must be audited before qualifying that host/profile. A queued job, successful read-only probe or static review is not that evidence.

Both actual CI runs succeeded and their artifacts were independently reconstructed; the strict frozen joint profile peak is 51,703,808 bytes. CI records are external to the local monotonic time window. Checkout, package installation and remote task CPU are not measured by the memory-only helper and must remain unknown. Device energy is not inferred from CPU, TDP or elapsed time. `CI_STATUS.json` records the observed remote state and source identity separately.

All final local behavior and raw reconstruction preceded the recorded final formatting attempt. Full Rust formatting/CI is not asserted: this editing checkout contains the recovered research files and lacks the complete `codex-rs` workspace. See `FORMATTING_STATUS.json` and the strict `ACCEPTANCE.json` for limits.
