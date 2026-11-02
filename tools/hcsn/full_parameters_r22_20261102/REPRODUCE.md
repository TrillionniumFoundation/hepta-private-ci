# Reproduce the nine-coordinate constructor checks

The source publication receipt must bind every entry of SOURCE_FREEZE.json
before the formal namespace is opened. `PUBLICATION.json` requires
`readback_verified: true` and `source_sha256` exactly equal to the freeze
`sources` map. All local Python dependencies and both independent auditors are
in that map. DEPENDENCIES.json identifies the interpreter, installed numeric
packages and Rust compiler; third-party package binaries are not vendored.

From the repository root, first restore compressed evidence if TRANSPORT.md is
present. Do not overwrite an existing result directory. The actual retained
formal run uses this command shape, with separate full-process accounting:

```sh
PYTHONPATH=/tmp/hcsn-mpmath OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 1 \
python tools/hcsn/full_parameters_r22_20261102/measure.py \
  --receipt tools/hcsn/full_parameters_r22_20261102/CONFIRMATION_PROCESS.json \
  --stdout tools/hcsn/full_parameters_r22_20261102/confirmation.stdout \
  --stderr tools/hcsn/full_parameters_r22_20261102/confirmation.stderr -- \
python tools/hcsn/full_parameters_r22_20261102/verify.py --formal \
  --output tools/hcsn/full_parameters_r22_20261102/confirmation_01
```

For independent replay, invoke `independent_check.py confirmation_01 --output`
with a fresh JSON filename, through the same meter. For the separately authored
mathematical path, invoke `independent_math.py --raw confirmation_01 --output`
with another fresh JSON filename. It reads exactly the nine indices frozen in
both its source and PROTOCOL.json. Its adaptive 80/90-digit infinite integrals
take more CPU than the primary campaign; retain that cost separately.

The primary campaign has 595 cases: all 512 corners, 64 fresh interiors,
18 single-coordinate endpoint interventions and one baseline. It checks every
one of 2,001 values and 18,009 physical derivative entries at every point,
including fixed-emission zero derivatives. Every derivative array also faces
two registered finite-difference extrapolates. Off-box, NaN, interpolation-knot
and process input-capacity controls are separate actual rejection tests.

All completed development/failure directories are retained. They use only
previously opened R20 corners and the declared R12 baseline. The initial wrong
knot control and a mechanical build error are documented; no confirmation
source is repaired after outcomes. A nonzero formal outcome is preserved and
cannot be relabeled as passing by changing tolerances, samples or exclusions.

The native binary is a reproducible build product whose executed digest is in
the summary. Its output data have no binary-bound resumable state. Unneeded
ELF build products may be excluded explicitly from the evidence manifest;
this does not apply to R20 runtime's essential checkpoint-bound ELF.
