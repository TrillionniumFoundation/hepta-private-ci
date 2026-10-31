# Calibrated operator study R11

The six requested workstreams have been implemented and executed. See
[REPORT_ZH.md](REPORT_ZH.md) for the scientific findings and
[ACCEPTANCE.json](ACCEPTANCE.json) for scoped admission decisions.

Base commit: `6c6f25f736df040e0d447e0242fb9819e15b3022`.
This additive research lane does not activate a production neuron model.

## Implementations

| Area | Entry | Meaning |
|---|---|---|
| Ordinary value / matched residual training | `value.py`, `model.py`, `train.py` | Exact known action semantics, belief-grid continuation, bounded learned correction |
| Actual native task | `native/`, `build.py`, `experiment.py` | Existing Hepta owner selects actions internally, reads packets and persists successors |
| Propagation | `propagation/` | One finite CTMC; independent generator/ODE/gradient/native checks and separate continuum error study |
| Raw causal content | `content/` | Five equal-parameter recurrent models, true BPTT, fresh test/OOD, uncertainty and cost |
| Complete financial kernel | `numerics/` | Eq8/9/12/A5/A7, forward AD, high precision reference, precision envelope and optimization |
| Causal/recovery/scoring audit | `audit/` | Real file-access monitoring and complete independent native score recomputation |

## Reproduce the task study

Use Python 3.12, NumPy 2.3.5, SciPy 1.17.0. Full-kernel numeric references also
need mpmath 1.3.0. Native builds used Rust 1.95.0, just 1.59.0 and
cargo-nextest 0.9.150. Run commands from the repository root:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.calibrated_operator_r11_20261031.train --out /tmp/r11-training-new

python -m tools.hcsn.calibrated_operator_r11_20261031.build \
  --build /tmp/r11-build-new --toolchain /path/to/rust-toolchain \
  --cargo-cache /path/to/cargo-home --tools /path/to/just-and-nextest \
  --report /tmp/r11-build-report.json --tests

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.calibrated_operator_r11_20261031.experiment \
  --training /tmp/r11-training-new \
  --binary /tmp/r11-build-new/target/debug/codex-calibrated-operator \
  --build-report /tmp/r11-build-report.json --out /tmp/r11-confirmation-new
```

Without available crate archives, the local campaign used explicit
`--cached-source-fallback`, recording every source file and distinguishing it
from archive checksum verification. Fresh CI does not enable that fallback.

Each run requires a new output directory. `training_01` and `confirmation_01`
are preserved development/failure records. `training_02`, `BUILD_02` and
`confirmation_02` are the completed task confirmation, with training freeze
`179037fca15a4f1ff5f08a50fd7c306b6ef5fdca82c6e951caa4091e293cbb20`.

The public grid is fitted inside the native process and its cost is included.
Do not describe this as successful unconstrained neural imitation of DP.

## Evidence and restoration

Large files and dense raw directory trees are published as lossless bounded
parts. The release manifest records original paths, sizes and SHA-256 values;
the restoration command in `release.py --help` reconstructs the original bytes
without silently overwriting a different file. See the separate content and
numerics restoration instructions for their nested raw evidence.

`content/DELIVERY_MANIFEST.json` and `numerics/PUBLICATION_MANIFEST.json` define
their published files. Root publication adds the complete reports and final
manifest after all experiments; publication time does not represent training
freeze time. Source/model/heldout chronology is recorded inside each lane.

## Current scientific status

Ordinary calibration, finite-model parity and declared numerical fixtures pass.
The analytic state changes real decisions, but independent net benefit and
dual-channel necessity do not pass. Pure FP32 financial arithmetic remains
inadequate. Finite CTMC parity does not certify continuum equivalence. These
results remain scoped synthetic research evidence, with complete negative
results and failed attempts retained.
