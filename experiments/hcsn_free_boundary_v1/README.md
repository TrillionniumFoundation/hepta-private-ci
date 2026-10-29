# Regenerative free-boundary neural research

This package implements and tests a regenerative value boundary as an inductive
bias in a sequence model. The exact scalar oracle, differentiable neural
approximation, content experiments, and actual Hepta owner execution have
separate contracts and separate evidence. The package does not claim to
implement the complete He--Xiong debt/equity model or to establish a universal
advantage over SNNs or Transformers.

The baseline source is commit `68eb16caa9c14c7b5729585c86d9c293018a987c`.
All additions are isolated under `experiments/hcsn_free_boundary_v1`.
Production Rust code, owner authority, and the original native kernel remain
unchanged. This is a research branch, not a production deployment.

## Contracts and implementations

| Object | Implemented meaning | Evidence |
| --- | --- | --- |
| Scalar state | Arithmetic Brownian pressure; upper firing boundary; reward `x-K`; reset `r<K`; frozen refractory duration; exponential discount | [MATH.md](MATH.md), [CONTRACT.md](CONTRACT.md) |
| Policy envelope J | Discounted rewards from all future firings under the declared threshold policy | [oracle.py](oracle.py) |
| Intervention obstacle G | Immediate reward plus the discounted value after reset and refractoriness | [model.py](model.py) |
| Free boundary | Unique stationary scalar optimum, with value matching, smooth fit, and both QVI inequalities | [oracle_tests.py](oracle_tests.py) |
| Neural recurrence | Input-dependent frozen-local coefficients, high-dimensional content, mean pressure/reset/cooldown | [model_tests.py](model_tests.py) |
| Content study | Same frontend/readout, near-matched active parameter count, paired minibatch prefixes, equal training CPU budgets | [PROTOCOL.json](PROTOCOL.json), [FREEZE.json](FREEZE.json) |
| Native execution | Actual owner decisions consume continuous signals; STOP exits the tensor step loop | [NATIVE.md](NATIVE.md) |
| Scaling and recovery | Measured CPU runtime, fixed inference state, new-interpreter mid-sequence recovery | [SCALING.md](SCALING.md) |

For the free boundary, the two value channels are J and G, each transformed by
the same `z/(1+abs(z))` function. First-passage probability remains a separate
state-flow/activity signal. These are regenerative-control value objects;
neither is relabeled as a financial equity Call or debt Put. The `continuation`
ablation means **margin plus J**, not J alone.

The scalar theorem does not certify the moving, input-dependent neural model.
In particular, the mean-state recurrence is not a timestep-consistent
propagator of the full random process. [CLOSURE.md](CLOSURE.md) gives independent
exact renewal and Monte Carlo measurements of this structural bias. Any
distribution-preserving repair is a separately identified experiment, not a
silent replacement of the frozen main study.

## Reproduce the numerical and training checks

The recorded environment uses Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0, and
PyTorch 2.8.0+cpu. CPU experiments set all numerical-library thread counts to one.
Run commands from the repository root, with a CPU PyTorch installation available.

```bash
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1
python -m experiments.hcsn_free_boundary_v1.oracle_tests
python -m unittest experiments.hcsn_free_boundary_v1.model_tests experiments.hcsn_free_boundary_v1.datasets_tests experiments.hcsn_free_boundary_v1.training_tests experiments.hcsn_free_boundary_v1.scale_tests experiments.hcsn_free_boundary_v1.analysis_tests
python -m unittest experiments.hcsn_free_boundary_v1.native_tests
```

The native executable is a pinned Linux research binary restored from verified
parts. Its source commit, original build receipt, wrapper identity, SHA-256,
and adapter bytes are retained in `native_vendor`. No local Rust rebuild or
repository-wide Rust CI is implied by these Python/native checks.

## Frozen content experiment

`study001` contains 244 model/task/seed searches and 488 learning-rate candidates:
eight models across six tasks and three seeds, plus seven mechanism arms across
two tasks and eight seeds, reusing overlapping searches. Each candidate receives
20 process-CPU seconds of actual training. Complete-update overruns are charged.
Validation, loading, checkpointing, interpreter startup, and heldout evaluation
are recorded separately and included in full child-process costs.

The primary checkpoint selection uses validation CE at the common 5/10/20 CPU
gates. Exactly-128-update snapshots cannot create extra primary selection
opportunities. Within an LR, a CE tie prefers an earlier CPU checkpoint; across
LRs it prefers the smaller LR. Test/OOD arrays are loaded only after both LR
searches finish and the selection receipt is written.

The six mechanism comparisons use eight paired seed differences, with the two
fixed tasks averaged within each seed. Acceptance requires all three: at least
one percentage point mean advantage, Holm-adjusted two-sided sign-flip p <= .05,
and a positive lower endpoint of a nominal paired-t 95% interval. Sign exchangeability
is an assumption; the two tasks are not a random sample of all possible tasks.
The three-seed broad task table is descriptive. Missing or failed runs cannot
silently disappear from the comparison.

To rerun the exact source/data protocol, use a **fresh output directory**:

```bash
python -m experiments.hcsn_free_boundary_v1.run_matrix run --output /tmp/hcsn-study001-repeat --workers 3
```

Do not run the scheduler into a restored evidence directory: a new run must
have its own cost ledger. CPU budgets do not imply identical update counts on
different hardware. Numeric selected checkpoints provide deterministic
inference replay; optimizer/RNG continuation checkpoints are not claimed.

The default analyzer requires `COMPLETE.json`; it verifies identities, metrics,
supervised-position mappings, paired batch prefixes, and actual parameter
changes before calculating comparisons. It writes a new `analysis001`
directory and refuses to overwrite prior analysis evidence.

```bash
python -m experiments.hcsn_free_boundary_v1.analysis --help
python -m experiments.hcsn_free_boundary_v1.analysis_secondary --help
```

## Data and original bytes

The exact six tensor datasets and their per-example source identifiers are in
`data/study001`. [SOURCES.json](data/study001/SOURCES.json) binds all 604 original
source files and the feature cache. Every cached audio row was independently
recomputed from WAV and checked against its filename label and speaker.

The real-data tasks use original MNIST digits and a pinned 600-recording FSDD
subset, with speaker-disjoint train/validation/test partitions. The image/audio
selection task uses literal query tokens, not natural-language comprehension.
FSDD recordings repeat across some episodes, and complete utterances are
resampled by a fixed offline log-mel frontend; these facts limit population
and causal-audio claims. Normalization is fitted on training observations only.

Raw sources, including the original IDX gzip files, WAV files, and the exact
audio feature cache, are preserved as the multipart `original_data` archive.
Verify and restore them with:

```bash
python -m experiments.hcsn_free_boundary_v1.archive restore --manifest experiments/hcsn_free_boundary_v1/artifacts/original_data.json --destination /tmp/hcsn-original-data
```

The restorer verifies every part, the concatenated archive, and every member.
It rejects unsafe paths and refuses to overwrite different existing content.

FSDD attribution: Jakobovski/free-spoken-digit-dataset and its contributors;
commit `26eb9aaf76e81b692f806f9140c2d2777410d7a1`, CC-BY-SA-4.0. Retain that
attribution and license when redistributing the audio or its derivatives.
The source URL is in the manifest; the original README is preserved separately
as [data/FSDD_UPSTREAM_README.md](data/FSDD_UPSTREAM_README.md).
MNIST provenance and byte hashes are retained in the source manifest.

The CfC cell and Apache-2.0 license are copied unmodified from the pinned
`mlech26l/ncps` commit recorded in [vendor/PROVENANCE.json](vendor/PROVENANCE.json).
Mamba-1 is an inspectable CPU reference implementation. CPU rankings here do
not represent optimized CUDA Mamba, FlashAttention, or neuromorphic hardware.

## Reading the eventual outcome

Mechanism execution, mathematical validity, predictive superiority, and economic
utility are different acceptance conditions. A working gradient or native action
change cannot substitute for heldout content quality. A faster or earlier stop
cannot substitute for correct predictions. Internal `K*activity` is a model
proxy, not measured read cost, CPU time, or energy. Results and failure receipts
must be read together with the specific source and protocol identity they bind.
