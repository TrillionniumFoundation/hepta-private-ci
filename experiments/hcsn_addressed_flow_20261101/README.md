# Addressed-content continuation of the four-stage Hepta study

**Execution complete.** Start with [REPORT.md](REPORT.md) for the four-stage
verdict and [COST_LEDGER.json](COST_LEDGER.json) for the measured cost boundary.
84 formal fits, 774 condition records, and two separate 18-model READ/STOP
confirmations are retained. Typed retention passes the registered nonmissing
quality and resampling gates for both cores; analytical advantage and real
multimodal adoption remain unestablished. Missing-answer prediction remains
poor and is reported separately. Prior negative results are preserved.

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

## Registered study (executed)

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

## Restore and verify the complete published evidence

The branch contains readable source, reports, freezes and summaries. The complete
additive experiment, including all raw predictions, all 84 formal checkpoints,
development attempts, copied source snapshots and AV derived caches, is stored
in 512 KiB binary parts under `artifacts/`. Raw CREMA-D media are not republished
in the bundle; acquisition manifests contain pinned URLs, byte counts, hashes,
license and attribution. Baseline Python dependencies come from the inherited
commit identified above and `BASELINE_VERIFICATION.json`.

From the repository root, using only the Python standard library:

```bash
python -m experiments.hcsn_addressed_flow_20261101.evidence_bundle verify \
  --manifest experiments/hcsn_addressed_flow_20261101/artifacts/COMPLETE_EVIDENCE_MANIFEST.json

python -m experiments.hcsn_addressed_flow_20261101.evidence_bundle restore \
  --manifest experiments/hcsn_addressed_flow_20261101/artifacts/COMPLETE_EVIDENCE_MANIFEST.json \
  --destination .
```

The utility verifies each part, the joined archive and every member. Restore
refuses path escapes, links, duplicate members and different existing files.
Identical already-checked-out source files are allowed. Do not change a published
freeze to make a mismatched artifact pass. `FINAL_PUBLICATION_VERIFICATION.json`
records independent remote Git blob readback; it is deliberately outside the
bundle to avoid a recursive archive identity.

`RUNTIME.json` records the actual environment: Python 3.12.14, CPU PyTorch
2.9.0, NumPy 2.3.5, SciPy 1.17.0 and scikit-learn 1.8.0. ffmpeg is required
only to rebuild media features. All measured compute used one BLAS/OpenMP
thread per worker. Exact performance is specific to this shared CPU machine.

The restored first-version raw outputs can be independently reanalyzed without
training or opening new confirmation samples:

```bash
python -m experiments.hcsn_addressed_flow_20261101.analyze \
  --run experiments/hcsn_addressed_flow_20261101/results/campaign001 \
  --control experiments/hcsn_addressed_flow_20261101/results/control001 \
  --out experiments/hcsn_addressed_flow_20261101/results/reanalysis001

python -m experiments.hcsn_addressed_flow_20261101.independent_retention_review \
  --run experiments/hcsn_addressed_flow_20261101/results/retention001 \
  --protocol-sha256 e3f11bee3ea5136bcd2f3d629f13dd96a38068f62f94def7d800c7acfcc739ba \
  --candidate-freeze-sha256 468459cd0353f7a84dd108edd5c7b416dc2beda0e972cdca87224d9e135c59a4 \
  --source-commit 6809dd449cecaad4f192b5bd176a11f91223769c \
  --out experiments/hcsn_addressed_flow_20261101/results/retention001/RECHECK.json
```

Use fresh output paths. Repeating previously examined samples is reproduction,
not a new independent confirmation. Historical absolute paths inside receipts
record where the original work ran; source and data checks use relative paths
or explicit arguments where supported. Do not silently rewrite a receipt.

## Version and inference boundaries

- `campaign001` / `control001`: original addressed version, confirmation seeds
  61101 / 88101. Its long-distractor failure remains intact.
- `retention001` / `retention_control001`: shared typed-write eligibility,
  fresh fits and new confirmation seeds 73117 / 118101. Both cores pass the
  nine nonmissing content conditions. Paid READ recovers the raw missing write;
  the learned value controller matches the strong lightweight policy here.
- `distribution_probe001`: new seed 91301, same original dynamic weights,
  a registered posthoc state-content factorization diagnostic. It retains the
  full probability vector and does not test its necessity.
- `av_core001`: eight-actor locked cross-cohort reevaluation. All eight actors
  appeared in earlier research. The API name `independent_test` is retained for
  compatibility and does not establish global novelty; see `AV_SCOPE.json`.
- `av_blind1019_core001`: one actor absent from the audited history, same 15
  trained weights and same encoders. Only point estimates, no population CI or
  adoption claim. Frozen generic frontend output is qualified by its separate
  `QUALIFIED_CONFIRMATION.json`.

Three training seeds and paired repeated episodes do not support treating
every episode/model combination as independent. Zero-width bootstrap intervals
on all-success or identical-policy samples are not population certainty.
