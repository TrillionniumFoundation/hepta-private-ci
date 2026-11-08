# Pretraining provider execution amendment

This amendment is recorded before the first formal task fit and before the
study plan is frozen. Its parent is the prospective source commit
`2725a19b357b1e3b4afabd412aaa67f818969295` in draft PR #5320.
The earlier 600-second provider envelope remains visible in that commit.

## Reason and scope

The original envelope was written while Colab was the intended provider.
The actual final qualification ran on Kaggle and completed all registered
checks. Its independently verified artifact has SHA256
`9ec88b996749732155d4c31e7830b297a668fbf648a3f849aff6aa8cab334661`.
The complete non-task 400-update probe used 80.99728586699996 seconds, below
the already registered 450-second qualification gate. This observation does
not guarantee every future task fit will meet its deadline.

The Kaggle provider envelope is now 3,000 seconds. This changes provider
segmentation only. The mathematical and consuming-runner 32-file source set
`731f883bf55e28abdfc02c7e650e1c8108877fa6d99fd9fe82b349ef67c87a39`
is unchanged. Every fit still has the original 400 updates and 480-second
hard deadline. All 160 fits, the ordered roster, data and training/episode
seeds, 20-fit selection groups, learning rates, statistical contrasts,
minimum useful differences, and qualification thresholds are unchanged.
No formal task results have been inspected to choose this amendment.

## Sequential execution and immutable evidence

One provider job handles one statistical group and one phase. Each runner
invocation performs at most one fit or one selected evaluation, on GPU 0,
with no concurrent fits. At least 720 seconds must remain before a new
operation is claimed: 480 operation, 60 supervisor/startup/termination,
and 180 export/close. Unknown remaining time is insufficient. A provider
boundary never shortens a fit or removes it from the denominator.

The sole runtime owner verifies the previous provider's authoritative
terminal and manifest, complete artifact hashes, and immutable history
before admitting another provider job. Inputs mounted from a prior private
notebook are accepted only when their exact expected capsule/bundle hashes
match; a moving notebook reference is not sufficient identity. A bounded
CPU-only attachment check may verify this transport without task data,
Torch import, or optimizer work. It provides no model-qualification credit.

All 20 training/validation attempts in a statistical group must have explicit
terminal records before the separate selection phase. The original selection
lock and its bound checkpoint/terminal hashes must be verified before a later
evaluation phase. Known failed or timed-out attempts remain visible and are
never replayed. An unknown attempt, identity/integrity failure, or mismatch
with the frozen software/device environment halts the entire owner for
read-only reconciliation. No automatic retry of training is permitted.

Provider wall time and GPU counter intervals are recorded with their scopes.
Parent intervals and nested worker intervals must not be summed twice.
Whole-machine physical energy and monetary cost remain unknown where no
actual measurement or billing record is available.
