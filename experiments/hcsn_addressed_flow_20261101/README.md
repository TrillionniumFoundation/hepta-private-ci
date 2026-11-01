# Addressed-content continuation of the four-stage Hepta study

This additive experiment continues the published four-stage source at
`7226bd94c6f30d113b2abb8dcf3678e63eb81f38`, PR #4546. The original evidence and
negative results remain unchanged. `BASELINE_VERIFICATION.json` records remote
Git blob readback for the reused source. New source, candidate and policy
freezes identify this continuation separately.

## Questions

1. Preserve the same finite CTMC contract for probability, first event,
   repeated events, marked content, reset and local value; challenge numerical
   limits using independent references. `operator_fastpath.py` is optional;
   the default model still uses the audited dense matrix exponential.
2. Check actual use of elapsed time, missing observations and recovery after
   a forcing jump. Clock ablation differs from subdivision of the same time.
3. Repair key/value and episode-local alias correspondence with shared learned
   addressing. Both the ordinary and Flow cores receive the identical typed
   token prior, content/relationship state capacity and shared initial weights.
4. Diagnose real audio/video/text features before attributing a result to a
   dynamic core. Closed-vocabulary sentence supervision and the structured
   relation prior are explicit. This is not an open-domain foundation model.

`ADDRESSING.md` explains learned content routing and the occupancy normalization
that can cancel common event attenuation. A repaired content memory is not,
by itself, evidence for an analytical-core advantage.

## Prospective study

`study.py` registers 51 fixed-budget fits: 36 content fits and 15 dynamics fits.
Every fit uses 600 steps and the final checkpoint. All arms share the exact
training stream for each task and seed. All checkpoints must complete and be
frozen before the new confirmation stream opens. No early stopping, seed
selection or confirmation-based hyperparameter selection is permitted.

`STATISTICAL_PLAN.json` fixes quality gates, paired comparisons, bootstrap
intervals, the interpretation of clock tests and cost accounting before
confirmation. Source hashes include this plan.

`control_study.py` implements a separate actual READ/STOP experiment. A common
value controller learns from executed paired training continuations. Its inputs
are available at the first query. A delayed READ first observes that query,
acquires a missing final raw write after 0.1 additional time, then answers.
The comparison includes the best fixed price threshold selected on development
data, plus always-read and never-read policies. The same frozen controls are
used with both cores, producing A/B/C/D and all five registered contrasts.
The READ price and measured CPU cost are separate ledgers.

## Execution

Use Python 3.12, NumPy, SciPy and CPU PyTorch. Run from the repository root with
`OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1` and one Torch
thread per worker. The protocol captures actual versions. The AV frontend also
uses ffmpeg and scikit-learn. Use fresh output directories.

```bash
python -m experiments.hcsn_addressed_flow_20261101.study \
  --freeze --out experiments/hcsn_addressed_flow_20261101/results/campaign001

# Publish the frozen source and protocol, then use that exact source commit.
python -m experiments.hcsn_addressed_flow_20261101.study \
  --phase train --out experiments/hcsn_addressed_flow_20261101/results/campaign001 \
  --source-commit SOURCE_COMMIT --workers 3

# Publish ALL_CHECKPOINTS.json before opening confirmation.
python -m experiments.hcsn_addressed_flow_20261101.study \
  --phase evaluate --out experiments/hcsn_addressed_flow_20261101/results/campaign001 \
  --candidate-freeze-sha256 CHECKPOINT_MANIFEST_SHA256
```

Use the inherited `hcsn_four_stage_flow_20261031.meter` wrapper to include
interpreter imports, child processes and writes. Inner fit CPU is nested inside
the outer meter and must not be added twice. All failed development attempts,
source snapshots, candidate calibration and confirmation costs remain in the
evidence. No GPU or attributable energy meter is present in this runtime;
energy remains null and CPU seconds are not converted to joules.

The final report and publication receipt distinguish numerical validity,
restricted task quality, actual analytical increment and deployment readiness.
