# Six censored HCSN best checkpoints: independent full-D replay

This is a post-terminal quality reproducibility check. All six original HCSN
attempts remain `budget_exhausted`, with training adequacy false. Passing this
check neither establishes convergence nor supplies independent E confirmation,
numerical qualification, architecture superiority, or a new training result.

## Fixed inputs and selection

`PLAN.json` fixes all six names, their order, the immutable v8 implementation,
the original native Python/Torch build, the all-development data manifest and
all 128 D windows. The original campaign final result and terminal command
journal must match their recorded hashes before any checkpoint is loaded.
Every original fit report and plan, best/initial checkpoint container, and
complete-epoch journal is independently bound to the terminal snapshot.

The selected checkpoint must be the **first complete epoch attaining the
strict maximum of D macro-F1**, with matching checkpoint epoch, update counter,
construction configuration and data identity. `last.pt` and `interrupted.pt`
are never loaded. A censored report need not contain `selected_development` or
saved development logits: its best complete-epoch row is the comparison
target. Missing evidence causes HOLD.

## Forward and metric scope

The original v8 model is constructed with the exact saved configuration and
loaded in CPU FP64. Evaluation uses `eval`, `no_grad` and the original padded
batch size 32, with manifest D order and the original valid-label mask. The
training microbatch size is not used. Frozen table memoization starts cold in
each new subprocess and its cost is included. No optimizer is constructed,
restored or stepped; no backward operation or E data access is performed.
Safe checkpoint loading necessarily deserializes existing optimizer/RNG
metadata in the container; those fields are discarded without inspection or
use. The original checkpoint files are never written.

Only D episode files are opened. Frozen frontend/selection metadata are checked
against the manifest; no ABC episode forward or training is performed. The
frozen frontend, output head and physics tensors must equal the original
initial checkpoint. Model tensor digests and all input/source file digests are
checked before and after the full replay, including actual loaded module paths
and the original Torch implementation files.

The independent NumPy calculation implements accuracy, both macro-F1 variants,
balanced accuracy, log-sum-exp NLL, both recorded Brier conventions and 15-bin
equal-width ECE. It never calls the trainer metric routine. All floating metric
differences must be at most `2e-12`; event counts and the full integer confusion
matrix must match exactly. This tolerance is frozen before any real replay.
Complete fresh logits, labels, episode order, event positions and source row
identities are saved, including when a complete replay subsequently fails the
metric comparison. Completed-batch receipts survive a timeout.

## Resources, failures and accounting

There is one worker and one CPU thread. Each fit has a 900-second process
budget, sampled RSS limit 2 GiB and address-space limit 8 GiB. A normal result
also reports its process high-water RSS. A separate launcher enforces the
one-hour process-group deadline covering the entire controller, imports,
input checks, six fits, serialization and archive creation. Stage time is
capped by the remaining total budget. No automatic retry is permitted.

Every declared candidate receives a record even if not launched. Launch errors,
timeouts, missing/malformed artifacts, source changes, incomplete evaluation or
metric disagreement remain HOLD. A process exit code of zero alone cannot
establish a successful replay. Bootstrap download and same-runtime synthetic
tests are separately recorded; their costs are additional to the controller
envelope. Per-fit exit CPU/wall costs are nested within the controller ledger,
and must not be counted twice. Wall sums are service costs, not elapsed time
for the earlier training campaign. No energy meter is available.

The host may concurrently execute the independently scoped numerical audit.
There is no dedicated-idle-host or hardware performance comparison claim.

## Validation

The synthetic tests exercise strict-best ties, legitimate censored reports,
hard-kill rejection, last-checkpoint substitution, input tampering, D-only file
access, ordered labels, closed-form metrics, padding/no-grad/state preservation,
and actual launch failure, missing output and timeout subprocesses. They never
read a real trained model. The exact frozen program is tested again in the
original native runtime before the one permitted replay launch.
