# Private Cell training and calibrated serving

This is an experimental Python implementation under `qa/stem-bakeoff`.
It preserves the shared Encoder / private Cell ownership boundary. It does not
replace the native Rust deterministic baseline, promote a learned task to
production authority, or establish a universal encoder/head winner.

## Three different forms of reuse

1. **Encoder reuse:** a source and a complete feature identity determine an
   immutable feature bundle. Many Cells can consume that bundle. No private
   optimizer owns the Encoder, and Head training does not call it.
2. **Training-bank reuse:** `FrozenTrainingBank` keeps one copy of each exact
   source vector, its normalized vector, and task-specific row indices. Repeated
   source IDs must have byte-identical vectors. The actual five-task audio probe
   needed only 80 unique source rows for five separate 32-example training banks.
3. **Serving-state reuse:** an identical frozen task, Head tensor state and all
   four calibration scalars can be evaluated once and fanned out to physical
   Cell IDs. This is a snapshot optimization. A Cell with a different learned
   state gets a different identity and is evaluated separately.

Independent training states are never deduplicated. A thousand independent
states trained on five tasks still represent five defined tasks. A thousand
identical snapshots provide neither new labels nor additional learning.

## What belongs to each Cell

`MicrobatchCellTrainer` owns separate parameters, first and second Adam moments,
gradient clipping, labels/class weights and update counters for every Cell.
Leading-array dimensions are Cell dimensions; reductions never mix Cells.
The immutable feature bank is shared. Batch compatibility requires the same
feature identity, width, class count, Head mode, rank and tensor schema.

The trainer rejects stale feature identities, conflicting source vectors,
nonfinite parameters, invalid private parameter budgets and excessive tensor
budgets before updating. Its conservative temporary-tensor bound is recorded;
Python objects, allocator internals and BLAS buffers are explicitly outside that
bound. Process RSS is a separate measurement.

The engineering probe uses the original `NumpyCellHead.train` objective and Adam
updates. It does not replace the frozen regularization/checkpoint search in the
main learning curves. Integrating the search scheduler with the batch trainer
requires preserving each Cell's own selected checkpoint and search accounting.

## Parameter and storage counts

For a binary task of feature width `d`, the linear Head has `2d + 2` trainable
scalars. The diagonal gate adds `2d`, yielding `4d + 2`. The rank-4 residual adds
another `8d`, yielding `12d + 2`. Calibration stores four further scalars.

Encoder output arrays are FP32. The current research Head/calibration arrays
and Adam state are **FP64**, so each stored scalar below occupies eight bytes.
These are tensor counts, not complete resident-memory estimates.

| Feature width | Linear + calibration | Gated + calibration | Rank-4 residual + calibration |
|---:|---:|---:|---:|
| 80 (MFCC) | 1,328 B | 2,608 B | 7,728 B |
| 384 (Granite) | 6,192 B | 12,336 B | 36,912 B |
| 768 (EG2) | 12,336 B | 24,624 B | 73,776 B |
| 3,072 (raw RGB) | 49,200 B | 98,352 B | 294,960 B |

Adam adds two arrays per trainable parameter during training. Gradients, active
microbatch intermediates, training-bank storage, routing, source retention and
metadata must be counted separately. Inference snapshots need no Adam state.
Changing precision is a separate numerical condition, not an assumed saving.

## Actual independent-gradient probe

The fixed probe consumes the sealed cheap-audio `seed-7_n-32` training artifacts.
There are five existing task definitions, three Head modes, 64/256/1,024 private
Cells, 20 Adam updates per Cell, microbatch 32 and one BLAS thread. Every Cell
uses a different initialization seed. Scalar and batched runs start from the
same respective initial states and receive the same training examples.

The two methods together executed 161,280 private optimizer updates and
5,160,960 example updates. All conditions retained distinct final Cell states.
Eight conditions matched bitwise; the residual/1,024 condition differed by at
most `5.55e-17`. A perturbation test also checks that changing one Cell's labels
does not change the other Cells' parameter trajectories.

For 1,024 states, scalar/batched wall times were respectively 1.752/0.307 seconds
for linear, 3.019/1.392 for gated and 4.500/1.678 for residual. These are single
fixed engineering measurements under shared CPU contention; they are not
isolated hardware benchmarks or confidence intervals.

The full probe, including bank preparation, both methods, parameter comparison,
parameter archive writes and final input verification, measured 17.720 seconds
wall and 17.631 seconds CPU. The final root report/manifest self-writes are
excluded. Nested method timings are breakdowns of this total and must not be
added again. A separate agent verified all 29 artifact files and 18 parameter
archives against their input/code pins.

## Serving contract

`CalibratedCellRouter` binds task identity, Head tensors, the complete feature
identity and all four stored calibration scalars. It copies frozen state into
immutable storage. Its current calibrated probability path is binary-only.

`probe_calibrated_serving.py` compares physical evaluation with exact-state
reuse using saved trained Heads, fixed heldout feature inputs and seven timing
repetitions. The probability arrays must match bitwise for every repetition.
The probe reports physical Cell count, unique task/Head/calibration states,
parameter/calibration storage, mapping bytes and dispatch work separately.
It owns no Encoder and performs no learning or calibration refit.

An accepted/rejected decision belongs to the declared calibration and task
protocol. A routing result, fast execution or successful serialization cannot
grant a failed-quality task authority. The operational learning failures remain
negative evidence even though their feature/training/serving contracts work.

## Reproduction entry points

- `probe_cell_microbatch_training.py`: fixed independent private-gradient probe.
- `probe_calibrated_serving.py`: saved-state inference and fanout probe.
- `test_cell_microbatch_training.py`: trajectory, isolation and bound checks.
- `test_probe_cell_microbatch_training.py`: immutable artifact/schema binding.
- `cell_cost_ledger.py`: explicit owner lifecycles and disjoint/inclusive costs.

The experiment archive contains the exact training banks, Head states, raw
measurements and independent verification receipts. Source code belongs to the
pinned repository commit; checkpoint weights are reacquired from their fixed
upstream revision and verified inventory rather than copied into each Cell.
