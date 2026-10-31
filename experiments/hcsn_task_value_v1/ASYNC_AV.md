# Real asynchronous audio/video frontend

The completed preparation is in `results/async_frontend001`. It uses 48 original
CREMA-D clips, with the original actor-separated roles: 24 training, 12
validation and 12 test clips. Selection takes the first 4/2/2 actors in the
previously registered cohort order, the DFA sentence and all six emotions.
These source roles and heldout actors have been used by earlier experiments;
this is a new frontend development study, not fresh heldout confirmation.

## Observation and time contract

Video events preserve decoded presentation timestamps. Audio remains at its
native 44.1 kHz rate, with 25 ms Hann windows and 10 ms hops. A window becomes
available at its exclusive END sample time. There is no temporal interpolation,
audio resampling, shared temporal grid, or full-clip duration normalization.
Ties use audio before video, with zero elapsed time for the second event.

The default payload has 16 log-mel or spatial DCT values and 16 differences from
the last observed value of that modality. The other eight columns identify
event modality, actually observed modality, time since each last observation,
and whether each modality has ever been observed. A missing observation exposes
zero payload and no delta from its unobserved value. Its known acquisition time
can be retained; this is an explicit imposed missingness experiment, not measured
network loss. Ordinary models receive precisely the same arrays and metadata.

All `dt` values are REAL SECONDS. Model adapters own any physical-time conversion.
Training-only source-uniform moments normalize the payload separately by
modality. Actor identity, labels and total clip duration are absent from inputs.
The causality claim concerns decoded presentation observations; codec buffering,
delivery latency, GPU throughput and physical energy are not measured here.

## Reproduce

Run from the repository root with Python, NumPy, ffmpeg and ffprobe. Preparation
does not require Torch or SciPy. Keep the existing baseline source manifest,
cohort plan and CREMA-D license; their hashes are checked before registration.

```bash
python -B -m experiments.hcsn_task_value_v1.async_av register \
  --manifest experiments/hcsn_task_value_v1/data/async_manifest.json
python -B -m unittest experiments.hcsn_task_value_v1.async_av_tests -v
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -B -m experiments.hcsn_task_value_v1.async_av prepare \
  --manifest experiments/hcsn_task_value_v1/data/async_manifest.json \
  --output experiments/hcsn_task_value_v1/results/async_frontend_reproduction001
```

Use a fresh output directory for every preparation attempt. Each raw clip is
verified against its frozen LFS size/SHA256, decoded and checked before its local
media copy is removed. The saved per-clip features, complete source URLs,
license, hashes and per-clip receipts remain. Failures retain `FAILED.json`.

## Unified batch interface

```python
from experiments.hcsn_task_value_v1.async_av import load_batch

root = "experiments/hcsn_task_value_v1/results/async_frontend001/data"
batch = load_batch(root, "train", indices=[0, 1, 2])
# x: [B,T,40]; dt: [B,T], real seconds; y: [B]; lengths: [B]
# valid: [B,T]; y_sequence: -100 except each last valid event
# timestamps: original presentation/sample-clock event times
missing_audio = load_batch(root, "train", [0, 1, 2], missing_modality=0)
```

For training, loading each split once avoids repeated decompression. Gather
sequence logits at `lengths-1`; padded events must not refresh neural parameters
or content. At a known missing acquisition, the two observed-modality columns
are zero even though its event-modality marker and timestamp are present.

## Completed checks and scope

All 48 clips passed both truncation and future-perturbation prefix checks with
zero maximum difference. All six behavioral tests passed. The first test run
had a NumPy assertion-shape error; its failure record is retained separately.
No failed clip was replaced. The 13,723 events retain independent native clocks.
All saved NPZ files total 3,442,630 bytes, including per-clip backups; no raw media
is retained. Preparation recorded 13.463281 CPU seconds including reaped
decoders and 28.767469 wall seconds. These body clocks exclude prior first-clip
download/preflight, tests, interpreter imports and environment work; they are
not complete lifecycle costs. No model quality result is inferred from frontend
or causality checks.

Use `cost_meter.py` around an entire new worker command to include worker startup,
imports, encoding, training, selection, checkpoints and exit. Internal training
clocks are already inside that process receipt and must not be added again.

```bash
python -B -m experiments.hcsn_task_value_v1.cost_meter \
  --output NEW_PROCESS_RECEIPT.json --timeout-seconds 600 -- \
  python -B -m unittest experiments.hcsn_task_value_v1.async_av_tests -v
```

The meter saves a combined stdout/stderr log and refuses existing output paths.
It reports `wait4` user/system CPU time, process wall time, maximum RSS and block
operations. Child `/proc` I/O counters are sampled lower bounds when accessible.
This environment denies those reads, so byte counters remain `null` with the
observed permission errors; block operations are not converted into byte counts.
GPU, physical energy and communication energy remain unmeasured. Local process
time or local file I/O cannot establish distributed communication energy.

`FINAL_VERIFICATION.json` binds the prepared source, manifest, data, license,
prefix receipts and final six-test run. The meter's real load, exit-7, timeout
and evidence-preservation checks are in `cost_meter_checks002/VERIFICATION.json`.
Earlier failed verification attempts remain available alongside the successful
runs. The meter itself excludes its interpreter startup and receipt serialization;
the measured worker includes its own complete startup and exit.
