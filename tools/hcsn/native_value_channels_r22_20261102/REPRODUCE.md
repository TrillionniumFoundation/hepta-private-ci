# Reproduce the native five-channel profile

The source freeze maps13 files, including the unchanged R11 snapshot, the
primary high-precision reference, both read-only numerical auditors, the
separately authored exact-rational/source contract and its protocol. Installed
Python packages and Linux libm are identified in DEPENDENCIES.json; they are
not claimed vendored. No fresh confirmation may start until PUBLICATION.json
contains `readback_verified: true` and `source_sha256` exactly equal to
SOURCE_FREEZE.json's `sources` map.

After source publication, first execute review_contract.py through measure.py
with a fresh result filename. It checks only source/constants and real-domain
rational bounds, and opens no new parameter points. Then run the main
confirmation with fresh output and receipt paths:

```sh
PYTHONPATH=/tmp/hcsn-mpmath OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 1 \
python tools/hcsn/native_value_channels_r22_20261102/measure.py \
  --receipt tools/hcsn/native_value_channels_r22_20261102/CONFIRMATION_PROCESS.json \
  --stdout tools/hcsn/native_value_channels_r22_20261102/confirmation.stdout \
  --stderr tools/hcsn/native_value_channels_r22_20261102/confirmation.stderr -- \
python tools/hcsn/native_value_channels_r22_20261102/verify.py --formal \
  --output tools/hcsn/native_value_channels_r22_20261102/confirmation_01
```

The fixed roster is64 newly seeded parameter vectors at three declared states,
plus the previously seen baseline at the same states:195 numeric points, not
195 independent task worlds. Every point has five values and50 derivatives.
The state is log-distance, always above the near-boundary Taylor/blend region.
The debt output is one newly issued unit d(V,m); tau=m is not an independent
tenor input. Read SCOPE.md before interpreting the gradients.

Next run independent_check.py with the retained confirmation directory and a
fresh `--output` filename, through its own measure.py receipt. Finally run
independent_math.py `--raw confirmation_01 --output <fresh-file>` through a
third receipt. The latter evaluates the six source-frozen indices by a
Volterra equity ODE/Laplace boundary/complex-step path and cross-checks F/G at
two old baseline points by first-passage-density integration. Numerical
imports and code are disjoint from candidate/R11/primary reference.

Every output/receipt path is create-only. The main run preallocates8MiB of RAW
storage before opening the new roster, then overwrites/truncates that extent
with the compressed record. An uncompleted preallocated archive is a failed
output, not evidence of completed cases. This precaution does not qualify
arbitrary I/O failures, process death or actual power-loss recovery.

Restore byte-exact original evidence via TRANSPORT.md when supplied. Native
executables are rebuildable products; no resumable state is bound to their
exact binary in this component. This differs from R20's essential runtime ELF
contract. Full-process receipts supersede nested inner timings for cost sums.
