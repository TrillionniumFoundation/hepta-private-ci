# Reproduce the contract closure

Run commands from the repository root. Use a new output path for each rerun;
preserve the committed original evidence. The primary measured environment was
Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0 and PyTorch 2.8.0+cpu, with one torch,
OpenMP, MKL and OpenBLAS thread. The original R7 used different library versions;
this is a new execution with verified input bytes, not a claim of bitwise
reproduction of its old timing results.

Matplotlib is needed only to regenerate figures. mpmath is needed for the
post-confirmation high-precision image-range audit.

## Restore all committed raw evidence

The 99 binary parts are ordinary Git blobs. They are not LFS pointers. After
cloning this branch, run:

```bash
python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.transport restore
```

The command validates every part, the combined archive, the embedded inventory
and every file payload. Existing identical files are retained; differing files
are not overwritten. The archive SHA256 is
`a6251c22d42956146a69af03612144bbeca5ccbcdaa48ac0d136dfdb9a8841e2`.
The independently executed clean restoration reconstructed all 8,724 files;
see `evidence/RAW_RESTORE_RECEIPT.json`.

The sixty primary candidate JSON files are already in
`evidence/calibration_models/`. Raw calibration target arrays and all detailed
fit records are restored by the transport command.

## Verify the primary freeze and rerun the registered confirmation

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python - <<'PY'
from pathlib import Path
from experiments.analytic_event_neuron.round8_contract_closure_20261031.confirmation import verify_manifest
root = Path("experiments/analytic_event_neuron/round8_contract_closure_20261031")
print(verify_manifest(root))
PY

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.confirmation \
  --output /tmp/hepta-r8-confirmation-replay

python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.analysis \
  --root /tmp/hepta-r8-confirmation-replay \
  --output /tmp/hepta-r8-confirmation-analysis.json
```

The confirmation checks frozen input identities both before and after
execution. It keeps all 36 arms, both regimes, all five fits and the registered
world/latent seeds. The 99.166667% intervals cover the predeclared family of six
contrasts by the specified fit-block bootstrap convention; with five observed
blocks they should not be treated as reliable broad-population coverage.

## Exact heldout expectation and numerical checks

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.heldout_exact \
  --output /tmp/hepta-r8-heldout-exact.json

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.kernel_audit \
  --output /tmp/hepta-r8-kernel-audit.json

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.kernel_range_audit \
  --output /tmp/hepta-r8-kernel-range.json

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m unittest \
  experiments.analytic_event_neuron.round8_contract_closure_20261031.test_kernels \
  experiments.analytic_event_neuron.round8_contract_closure_20261031.test_calibration \
  experiments.analytic_event_neuron.round8_contract_closure_20261031.test_controls -v
```

The three test modules contain 11 targeted tests. The mathematical audit has
nine explicitly named gates; those are not counted as additional independent
training trials. The range audit is a post-freeze numerical diagnostic, not a
new efficacy confirmation.

## Retrain the fixed-cell calibration

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.calibration \
  --output /tmp/hepta-r8-calibration-replay
```

This retains every fixed final step and creates 20 fits, 60 checkpoints and 20
complete target archives. To independently replay that new run from saved
bytes, use:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.calibration_audit \
  --output /tmp/hepta-r8-calibration-replay
```

The second stage changes the content/readout branch while preserving a separate
frozen propagation encoder. It is not full-cell joint learning. That additional
experiment has its own [JOINT_PROTOCOL.json](JOINT_PROTOCOL.json),
[JOINT_REPORT.md](JOINT_REPORT.md) and source under `posthoc/`; its evidence is
kept separate from the primary freeze. The joint report contains the complete
new-output-directory register → train → candidate-freeze → evaluate → summary
and independent-audit commands, including the process resource wrapper. All
joint raw gradients and paired trajectories are committed directly in
`evidence/full_joint_v1/`; they do not require primary-archive restoration.

## Native execution, recovery and costs

Follow [native/README.md](native/README.md) to restore the exact qualified Linux
x86-64 executables and produce a path-rebased build reference without requiring
the original scratch paths or cached Rust libraries. The unchanged historical
build receipt remains available and its hash is bound by the new reference.

After a fresh qualification, the complete cost and broker-reuse measurements
can be repeated with:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.native.costs \
  --binary /tmp/hepta-r7-native-restored/executables/r7-native-policy \
  --build-report /tmp/hepta-r7-native-restored/RESTORED_BUILD_RECEIPT.json \
  --qualification /tmp/hepta-r7-native-new-qualification \
  --output /tmp/hepta-r8-native-cost-replay

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.native.costs_reuse \
  --binary /tmp/hepta-r7-native-restored/executables/r7-native-policy \
  --baseline /tmp/hepta-r8-native-cost-replay \
  --output /tmp/hepta-r8-native-reuse-replay
```

The reuse run consumes the baseline's exact registered case order. It keeps an
independent native owner for every episode and compares actions, final public
state and terminal artifact contents/hash against the baseline. First startup,
last close and all actual child CPU are charged. No warmup episode is discarded.

## Recompute the independent audit

After raw restoration, `posthoc/independent_confirmation_audit.py` and
`posthoc/policy_dp_parity.py` accept `--root` and a new `--output` path. They
replay external task transitions and actual hard latent transitions, respectively.
Their saved original receipts are `final_independent_audit.json` and
`final_policy_dp_parity.json`. `posthoc/mc_decomposition.py` implements the
separately labelled conditional paired-world sampling diagnosis.

To regenerate the two static figures from committed result files:

```bash
MPLCONFIGDIR=/tmp/hepta-r8-matplotlib \
python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.figures
```
