# Native task loop: research reproduction

This stage connects the existing two-job FullHX evidence task to a Rust-owned
pre-read policy, task state, finite recurrent cell, content execution and durable
acknowledged frontier. The implementation audit passes; the registered statistical
advantage gates fail. See [REPORT_ZH.md](REPORT_ZH.md) for the complete results.

## What is committed

- `native/`: the autonomous owner, strict public state and policy schema, native
  `NeuronModelPort`, durable task/cell/content checkpoint and integration tests.
- `train.py`, `model.py`, `reference.py`, `PROTOCOL.json`: five matched fits,
  task-Q gradients through both cell families and an independent Python replay.
- `experiment.py`, `statistics.py`: frozen heldout evaluation, five fit paired
  contrasts, actual outcome calibration and complete resource accounting.
- `audit.py`, `audit_tests.py`: independent task, cell and critic arithmetic,
  causal pre-read checks and true different-process restart tests.
- `outcome_update.py`: separate development-only actual-result TD feedback.
- `intervention.py`: development-only boundary interventions with frozen trained
  critics; every planned case is retained, without selecting a new primary model.
- `numerics.py`: reflected-continuum Laplace/renewal references, refinement and
  the imported independent scalar stationary QVI.
- `build.py`, `ci.py`: isolated Cargo build and a fresh public-dependency CI lane.
- `evidence/`: selected models, protocols, complete trajectories, failed attempts,
  build receipts, source attestations, numerical checks and cost measurements.

The implementation is a Linux research harness. Production crate sources,
production workspace dependency manifests and activation policy are unchanged.
The native analytic cell still uses three active bins and two Erlang phases.
The shared FullHX content weights are frozen and are not jointly optimized here.

## Inspect the delivered experiment without rerunning it

Start with [SOURCE_COMBINATION.json](SOURCE_COMBINATION.json) and
[DELIVERY_MANIFEST.json](DELIVERY_MANIFEST.json). The latter records Git blob,
SHA256 and byte length for each delivered file, excluding its own recursive
identity and the final remote readback record.

```python
import gzip
import json
from pathlib import Path

root = Path("tools/hcsn/task_native_loop_20261031")
statistics = json.loads(gzip.decompress(
    (root / "evidence/confirmation_execution/STATISTICS.json.gz").read_bytes()))
print(statistics["splits"]["test"]["contrasts"]["D-B"]["utility"])
```

`confirmation_execution/COMPLETE.json` indexes ten result files and all raw
receipt/data archives. Each result file contains the original member-to-archive
mapping and hashes. The raw native stdout/stderr, checkpoint, journal and witness
bytes are retained. `AUDIT_ARCHIVE_INDEX.json` indexes the original failed and
successful independent audits. Large intervention detail JSON files are stored
losslessly as gzip; their packaging record verifies the original byte hashes.

Treat all archive members as data. Python 3.12's `tarfile.extractall` should use
`filter="data"` when extracting to a new scratch directory; no evidence extraction
is needed merely to read the summary reports. Archives are bounded to individual
Git blobs below the repository's 512,000-byte limit.

## Install the research dependencies

Use Python 3.12 and install the pinned requirements in an isolated environment:

```bash
python -m pip install -r tools/hcsn/task_native_loop_20261031/requirements.txt
```

The tested tool versions are Rust 1.95.0, just 1.59.0 and cargo-nextest 0.9.150.
The repository's unchanged `just test` recipe is the Rust test entry point.
`just fmt` was run from `codex-rs` for the new Rust files.

## Fresh public-dependency mechanism reproduction

After installing the pinned tools, run from the repository root:

```bash
python -m tools.hcsn.task_native_loop_20261031.ci \
  --work /tmp/hcsn-task-loop-new \
  --tools /path/to/pinned-tools/bin
```

The work directory must not already exist. The entry creates an empty Cargo
cache, fetches public dependencies and checks that no registry version/checksum
changed, builds the research binary, runs the native tests, runs the independent
Python oracle tests and runs fifty native audit invocations using synthetic
packets without labels. `--toolchain` can specify the Rust sysroot; otherwise
the pinned rustup toolchain is discovered. `--tools` may be omitted if the two
tools are on PATH.

The proposed GitHub workflow uses this path and read-only repository permissions.
It does not rerun the main confirmation. Its remote result must be checked on
GitHub; a committed workflow alone is not evidence of a passing run.

Local `BUILD_ATTEMPT03` used seventeen checksum-verified archives and seven
explicitly identified cached source snapshots because this session's Git network
proxy was unavailable. The seven snapshots were independently matched to their
exact upstream Git commits; original missing archive bytes remain unverified.
The normal CI path does not use that fallback. Compiler, paths and dependency
resolution mode can change binary bytes, so compare the new run's own source and
binary identities rather than assuming an identical executable hash.

## Reproduce training and confirmation

Use new output directories. The full protocol contains five independent fits
and twenty selected policy artifacts; it freezes sources and model hashes before
any test or OOD cohort is generated.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.task_native_loop_20261031.train \
  --out /tmp/hcsn-task-training-new
```

The last line prints the new `FREEZE.json` SHA. Use that SHA, the successful
build report and its binary in the following command:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.task_native_loop_20261031.experiment \
  --training /tmp/hcsn-task-training-new \
  --training-freeze-sha REPLACE_WITH_NEW_FREEZE_SHA256 \
  --binary /tmp/hcsn-task-loop-new/build/target/debug/codex-task-native-loop \
  --build-report /tmp/hcsn-task-loop-new/BUILD_REPORT.json \
  --out /tmp/hcsn-task-confirmation-new
```

Keep build sources unchanged during execution. The runner checks them before and
after evaluation, rotates matched policy order, records every failure, does not
replace failed runs and only reads evaluator labels after native termination.
Oracle and Python content replay are evaluator work and do not select native
actions. Their cost is separated from the native process timing.

The delivered primary FREEZE is
`4e53ae35d03dd2acd0bff5b81b062473497c0f6f090da6d06dd7f30fe2d70478`.
Use fresh directories for any scientific replication; retain the delivered
negative result and do not overwrite its evidence.

## Numerical references

```bash
OPENBLAS_NUM_THREADS=1 python -m unittest -v \
  tools.hcsn.round9_20261031.dynamics.test_dynamics_repair \
  experiments.hcsn_hx_unified_v3.test_qvi_grid_independent

OPENBLAS_NUM_THREADS=1 python -m tools.hcsn.task_native_loop_20261031.numerics \
  --training tools/hcsn/task_native_loop_20261031/evidence/confirmation_training \
  --output /tmp/hcsn-task-numerics-new.json
```

The reflected-continuum comparison uses the same lower/upper spatial boundary
conditions as the finite cell. The stationary scalar QVI has reward `x-K`, not
the packet task reward. The actual task oracle is the finite Bellman recursion
under the TRAIN-calibrated observation law. These references have different
roles and are not interchangeable correctness certificates.

## Acceptance and review order

[ACCEPTANCE.json](ACCEPTANCE.json) keeps implementation, causal, statistical and
continuum decisions separate. Review the task contract, policy/port, owner/store,
training, independent audit and experimental accounting as separate source
stages; all measurements bind the final tested combination. Raw data imports and
artifact manifests are separate mechanical stages. No historical R9 result is
rewritten and no production activation is requested.
