# Shared arm budget: engineering qualification v2

This new directory connects four accounting admission boundaries. It does not
change older budget, solver, evaluation or model code, or any historical result.
It runs no model and makes no five-arm, future-task, fission or compression claim.

## One arm and seed, one remaining allowance

`ArmController` reuses the existing `BudgetLedger`. Its directory binds the arm,
seed, protocol SHA, complete budget and capacity manifest. Every training,
retrieval, generation and task-gate stage using this API opens that same binding.
Changing the binding fails. Each event obtains an exclusive durable claim before
admission; an existing pending or terminal claim never launches another effect.
`run` invokes its callback only after capacity verification and reservation.
Restart safety assumes persisted directory entries and no filesystem rollback;
parent directories are not fsynced, so this is not power-loss exactly-once.

Reservations must explicitly include every meter. Unknown actual values remain
`null` in the observation report and consume the reserved amount in the budget.
Known measurements settle as observed. Infrastructure failure or timeout keeps
at least the full reservation; a known partial cost above it still triggers an
overrun when another observation is unknown. A lost operation consumes the full reservation
and closes the arm. Overruns are retained and close the arm. A complete negative
task result is still measured work: its observed cost is charged, with no reset
or removal of the attempt. Legitimately unused parts of its reservation may be
released. Neither a completed event nor a raw receipt can settle another effect.

The legacy ledger's numeric `actual` and `executed_used` fields carry budget
charges in this adapter. They must not be relabeled physical measurements:
`settlement.json` separately stores nullable observations and each charge basis.
Shared-parent allocation across different arms and a whole-study physical-cost
aggregator are not newly integrated here.

## Raw receipts and coverage

`receipt_bridge.collect` reads explicitly pinned historical procedural-v1,
wait4-v2 and warm-controller-v1 records. The existing cost reader verifies raw
stdout/stderr. Duplicate attempt IDs, duplicate raw receipts, overlapping
coverage, missing covered records and incorrect controller child sums fail.

The coverage plan is owned by the trusted controller. A waited process includes
its waited descendants; covered records are attribution only. Controller self
CPU excludes its children. End-to-end wall comes from one registered owner;
the sum of per-attempt wall remains separately labeled. A controller's declared
child CPU is checked against the selected raw process records, allowing at most
one ns of legacy float conversion difference per child.

This validates declared local evidence relationships, not OS attestation or
hostile same-UID isolation. A caller cannot infer process ancestry from amounts
alone and must freeze the actual coverage plan. Missing read/write/token meters
stay unknown. The bridge does not infer model training or decoder calls from a
process's exit status, CPU time or output size.

## Checkpoint tensor admission

`tensor_capacity.admit` streams the entire pinned safetensors file, consumes its
header from that same stream and checks file identity before and after reading.
It validates dtype, shape, contiguous non-overlapping byte ranges and full
payload coverage. Adapter A/B shapes must agree with the pinned LoRA rank and
every declared target must appear. Full layer/base loader compatibility remains
outside this serialized-only check. No torch/model import or tensor execution is involved.

Active adapters and active router tensors share the same total value and tensor
byte ceilings. Retained parents, frozen bases, optimizer and gradient tensors
have separate roles and totals. Two logical cells count twice even if they
reference one checkpoint file; unique stored checkpoint bytes are deduplicated
only by observed inode, with configs included. Equal content on distinct inodes
does not imply actual storage sharing.

Roles and capacity limits are frozen controller declarations. Admission describes
serialized checkpoint tensors, not which parameters a future model loader will
train, dynamic allocations, optimizer peaks or complete deployment storage.
Every `begin` repeats admission. A later loader must maintain the same pins.

## Qualification and remaining integration

`qualify.py` consumes a SHA-bound plan with exact source/runtime identities and
test IDs. Pure tests use explicitly synthetic receipt/tensor format fixtures.
Additional qualification only reads existing r8 checkpoints and saved warm-run
receipts. Its historical accounting replay is not a new physical model run.
The qualification process's own CPU/wall is reported separately.

The frozen plan and every attempted result, including failures, belong in a new
control directory. Tests precede final repository formatting. Publication must
retain the executed-source identity or an equivalent formatting bridge.

Older runners have not been modified to use this controller. Existing Ruff/codec
executors and the repair solver still need a versioned call-site integration.
The API does not enforce aggregate process-tree CPU/RSS/storage, supply a
continuous storage byte-time meter, or qualify the strong retrieval baseline.
Whole-host CPU, energy, billing and complete OS costs remain unknown. Common
budget engineering is not evidence that trained memory improves task success.
