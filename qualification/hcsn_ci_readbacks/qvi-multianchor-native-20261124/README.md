# Native QVI multi-anchor conditional weight editing

Read RESULTS_ZH.md for the complete result and limitations, FORMULAE_ZH.md for the proof, and protocol.json for the preregistered experiment. This is the original public two-cell scientific fixture, not a private Pocket4 checkpoint or a production Runtime integration.

The native std-only Rust program implements analytic source-cost inversion, a bounded three-coordinate readout solver, finite-problem no-edit certificates and strict FP64 parameter composition. All final live candidates were rejected or rolled back; none passed the original complete unseen-initial-state retention gate.

## Build and numerical tests

Use Rust 1.95.0 or a compatible toolchain. No Cargo dependency or manifest is required.

    mkdir -p build
    rustfmt --edition 2024 native/*.rs
    rustc --edition 2024 -O native/main.rs -o build/qvi_edit
    rustc --edition 2024 --test native/planner.rs -o build/planner_tests
    rustc --edition 2024 --test native/compiler.rs -o build/compiler_tests
    ./build/planner_tests
    ./build/compiler_tests

## Native interface

The bounded UTF-8 stdin format starts with HEPTA_QVI_EDIT_V1, followed by row count (1..64), column count (1..3), budget, fit tolerance, eight original QVI parameters, target boundary, and one row of matrix coefficients plus target per anchor. See attempt003/two/native_problem.txt. Output is finite JSON with FitFeasibleNeedsFullValidation, NoEditInfeasible or NoEditNumericallyUnresolved. Its certificate applies to the recorded FP64 linear system. Caller must bind the feature exporter and checkpoint, then validate the full original forward outputs.

The compilation format is HEPTA_QVI_COMPILE_V1 followed by dimension, budget, base parameter vector and delta vector. Output gives composed parameters and outward bounds on actual changes. This step prevents a one-ULP box escape after adding a delta to a nonzero base. A fit-feasible plan is not permission to commit.

## Recorded experiments

- attempt001 preserves the initial tuple/list checkpoint comparison failure and original source.
- attempt002 retains the complete raw fitting experiment and its original FP64-edge guard. It is not the final strict parameter qualification.
- attempt003 is final: strict native compilation, exact rational parameter checks and full fixed validation. Eleven changed candidates were replayed; nineteen byte-identical numerical candidates reuse bound receipts. No refitting occurred.

The complete package includes raw receipts, candidates, restored live files, source snapshots and a content manifest. Framework binaries and compiled executables are excluded; rebuild them from source.

## Fresh reproduction

Use Python 3.12, Torch 2.10.0+cpu, NumPy 2.3.5 and SciPy 1.17.0. Set OMP_NUM_THREADS=1, OPENBLAS_NUM_THREADS=1 and MKL_NUM_THREADS=1. If dependencies are in a custom directory, add that directory to PYTHONPATH. The scripts prepend the bundled frozen upstream directory themselves.

    python run_experiment.py --output fresh_raw
    python replay_serialization.py --source fresh_raw --output fresh_strict
    python verify_independent.py fresh_strict

Output directories must not already exist. The first script deliberately preserves the historical raw fitting stage; only the second stage provides strict composed-parameter qualification. Never treat the first-stage 1e-15 implementation guard as a change to the frozen 0.1 budget. capacity_certificate.py rechecks exact algebra for the delivered attempt003 matrices.

The original protocol was published before fitting at commit 1c9762b963f871166ca6c83286a41a330dda4f38. The serialization correction was published before strict replay at c4f1630cb856d0e6d23294a39cb2153fbc1e9ce0. Scientific sources are frozen at 610f91087b598656f7f3913e600c705b95bf071f; research-index readback is f8a6b335d8499a8546aac8a46dd6128518650cfd. These distinct identities must not be relabeled as one source or current production state.
