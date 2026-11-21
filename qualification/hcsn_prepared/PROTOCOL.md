# HCSN prepared-window execution, v1

Identity: `HCSN-PREPARED-KERNEL-20261121-1d88-v1`. This is a new synthetic
implementation qualification. It does not consume or reopen the P1–P4, TaskADV,
full-equity, N256, C2 or HPCA final sets. Existing failures remain unchanged.

## Hypothesis and implementation

`hcsn_scale.SequenceModel` executes each window separately. Each observation
builds a generator, evaluates two matrix exponentials and solves the finite Call
system. The drift, boundary and write mark depend only on that observation's
input. Therefore a bounded batch of complete windows can prepare these operators
together before sequentially transporting each window's population.

`PreparedSequenceModel` uses the same parameters, finite generator, remap, reset,
Erlang phase dynamics, FP64 transport and finite-policy Call as the serial model.
Each sample keeps its own intervals; no timestamps are averaged or resampled.
Its state is a temporary tensor batch, not a persistent `FlowState` with a false
shared clock. `representations` chunks windows in groups of at most 32. The
executor has separate identity metadata and cannot inherit older qualification.
GRU is also batched as a scheduling control. A speedup shared by both models is
evidence about batching, not a unique HCSN property.

Preparing B×T operators retains extra matrices and AD history. Operator entries,
events, batch and time are capped. This is bounded window execution, not a claim
of fixed-memory BPTT. No Call/risk channels or invariant checks are removed.

## Required numerical gate

Run `python -m unittest qualification.hcsn_prepared.prepared_tests -v` once on
the frozen candidate source. Five tests compare every output channel, independent
clocks, boundary movements in both directions, causality, full parameter and
input gradients, an Adam update, mixed-precision transport and chunked outputs.
FP64 equivalence uses rtol 1e-10 / atol 1e-11 for outputs and rtol 1e-9 / atol
1e-10 for gradients. Existing population mass/content tolerance stays 1e-10.
The separate mixed-precision output check uses rtol 3e-5 / atol 3e-6, while the
transport and population invariants still use FP64. No N256 byte criterion is
changed or claimed satisfied. These thresholds are frozen before any execution.

## Cost gate

`benchmark.py --freeze MANIFEST.json` binds the source bytes, declared protocol
and runtime versions without importing Torch. Root's resource admission must
precede `benchmark.py --run MANIFEST.json --output NEW_DIRECTORY`. Both commands
are invoked as `python -m qualification.hcsn_prepared.benchmark`.

Cases: HCSN/GRU × serial/prepared × B=1/2/32 × width=4/16, T=16, input=15,
FP64 CPU, one intra-op and inter-op thread, deterministic algorithms. A fixed
synthetic random seed generates unique per-sample integer-microsecond intervals.
No optimizer updates or task labels are involved. All 24 cases run sequentially
in isolated child processes. Each performs one warmup per operation, five
representation forwards and three complete loss/backward passes. Preparation
is included in all timings. An additional prepared HCSN component observation
separately reports setup and propagation; it cannot replace end-to-end timings.

The total budget is 180 wall seconds, at most 25 seconds per case and an observed
RSS ceiling of 1 GiB per process. The coordinator separately binds host and
allocation; this script does not establish external resource custody. Imports,
warmups, diagnostics and process overhead are paid in total process wall time.
Peak RSS is the process high-water mark, including framework overhead. Timeouts
and exhausted cases remain in the receipt. Output directories are exclusive;
there is no silent overwrite or retry. Runs need no data files and accept none.

Report paired medians, all samples, total wall time and RSS. Parameters and input
hashes must match between each pair. Numerical success permits a claim of
implementation equivalence within the declared tolerance. Timing results permit
only a synthetic CPU scheduling claim. A full-scale training advantage, quality
gain, fixed-memory learning or superiority to Transformer/SNN remains untested.

## Subsequent task experiment

Any learner comparison must use a new, source-frozen experiment identity with
new independently held-out sequences. Select source/configuration and candidates
on training/development data, freeze every selected candidate, then evaluate the
final set once. Compare serial and prepared executors at identical parameters,
data, dtype, thread and budget; additionally compare batched GRU. Report complete
feature preparation, backward, checkpoint, search and validation costs. The
original 169 final evaluations cannot be used to select new capacities or rules.

Status at source freeze: implementation written; static compile only. Dynamic
numerical and timing status must come from an actual execution receipt.
