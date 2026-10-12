# Independently learned Cells and invocation-local shared basis computation

Continuation of PR #1654 at `36b4b8abcdb601d26eba3e806d63a2ec9147ed3d`.
Existing qualification path only; no native owner, persistent cache, model loader,
authority or production route is added. The pending BGE execution is not replaced.

## What is actually different

Earlier serving probes reused one selected Head under many request aliases.
This study instead inherits four Cells from one learned parent, trains each on
its own 16 disjoint original training utterances, and retains four distinct
private parameter rows. All four solve the same four-intent task; this does not
claim four new domains, modal specialization or new information from duplication.

The exact historical mmBERT artifact, loader and 328-row source census from V5
are reused. The same 64 base rows train the common parent; the 64 adapt/extra
rows are content-ordered within each training label and distributed four ways.
No evaluation input, label or score selects a partition or a winner. Base training
uses 200 steps, then each Cell gets 200 private steps: **1000 total**, not 200.
This executes 19,200 sample presentations. The original base-only normalizer is
retained; all shared weights and every peer's private parameters stay unchanged
during a Cell's update. Candidate copies and preparation time are charged.

At rank 8, four Cells have 68 private scalars and 16,900 shared scalars. The
67,872-byte figure is the packed FP32 bank tensors, NOT Encoder storage, Python
objects, optimizer state, activations or measured RSS. No Encoder ran locally.

## Shared computation versus a strong frozen dense control

`shared_cell_execution.forward_shared` computes `x @ basis`, gate features and
the base readout once per explicitly referenced input within one invocation.
Only the coefficient and gate combination is Cell-local. No floating-point
vector equality is used as an input identity or permission check. Caller owners
must supply correctly scoped inputs; this is not a new authorization boundary.

The ordinary `BasisCellHeads.forward` is unchanged. Tests compare outputs and
all parameter/input gradients, including duplicate-reference accumulation.
Forward scratch admission precedes projection; invalid indices, dormant Cells,
nonfinite results and finite-operand overflow fail. The scratch estimate covers
explicit forward intermediates, not library workspaces, backward memory or RSS.

The benchmark retains both existing expanded-batch math and a strong frozen
control that compiles a dense residual/gate matrix for every Cell. Compilation,
extra tensor storage, warm-up, reference computation, preparation and full probe
costs are recorded. Each timing trial includes Head math and validation; it does
not include a fresh Encoder. Three balanced rotated orders are diagnostic timing
repeats, not independent scientific outcomes or latency-tail qualification.

## Observed local run

Four genuinely fitted Cell rows each obtained 118/120 held-out correctness.
The inherited parent Brier was 0.0208972. Cell 0/1/2/3 Brier values were
0.0208483 / 0.0211735 / 0.0231667 / 0.0224007. There is no demonstrated quality
improvement; no Cell was chosen after seeing the held-out scores. 480 predictions
represent **120 unique test inputs**, not 480 independent examples. Separate
saved-byte scoring and affine reconstruction produced maximum logit error
3.814697265625e-6 with zero argmax reversals, below the fixed 1e-4 ceiling.

For the 480-request trained-Cell probe, median expanded/shared/folded times were
5.6033 / 5.0470 / 2.0952 ms on this CPU process. At 4096 **synthetic independently
parameterized, not trained** Cells and one reused input, they were
48.2795 / 34.7652 / 18.3474 ms. A retained earlier repeat with 32 distinct inputs per batch
was slightly slower (52.4278 vs 51.4164 ms); the final run retains all raw times too. Retain this negative result; the
shared projection is not an unconditional fastest-path claim. The 4096-Cell
packed bank was 346,128 bytes; the folded control required **31,473,664 additional
bytes**. This exposes a speed/storage tradeoff, not a duplicated-421M comparison.

123 inherited plus 18 new tests passed locally without skips. Local imports still
use the previously disclosed function extracts for `model_runner` and `study`;
the plan records their actual file hashes and marks them outside the qualification
source. This remains a partial checkout. Full repository source-head/merge CI and
the pending new pretrained run require their own receipts. Current code hashes,
original failed attempts and preliminary measurements remain in the delivery.

## Reproduce

```sh
export PYTHONPATH=qualification/stem-cell-v1
python3 -m unittest -v shared_cell_execution_checks multicell_execution_checks
python3 qualification/stem-cell-v1/multicell_learning_study.py \
  --archive /fixed/artifact-11757461425.zip --output /new/multicell --synthetic-scaling
python3 qualification/stem-cell-v1/multicell_learning_study.py \
  --archive /fixed/artifact-11757461425.zip --review-run /new/multicell \
  --output /new/multicell-scores.json
```

These commands extend the existing historical-feature CI job; no new runner job
or production gate is introduced. Results are immutable and failures remain
failures. New base consolidation, NDU action optimization, semantic recurrence,
multimodal generation, target-host recovery and production promotion remain
separate work, not capabilities certified by this kernel or these public tests.
