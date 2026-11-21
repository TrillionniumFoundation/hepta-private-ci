# Finite fixed-law specialization cost study

This is an isolated, source-pinned research workload. It is not a production
deployment, a new quality holdout, or a future latency guarantee.

Six original trained checkpoints (`flow` and `flow_fixed`, seeds 101, 211,
307) retain their own laws. The three original input contracts are T10B64,
T10B1 and T20B8. CPU FP64, one Torch thread and one inter-op thread, and CPU
affinity 8 are fixed. Every full task verifies the checkpoint and live tensor
identities, returns the complete state and classifier logits, snapshots and
serializes the complete state through an in-memory Torch archive, restores it
without its former autograd graph, executes one ordinary continuation step,
and compares all arrays and metadata with the previously frozen reference.
This is a serialized cold-state restore in the same process, not process
restart, durable disk recovery, or retention of past autograd.

Before model execution, `freeze_protocol.py` seals the complete worklist,
source/input/reference bytes, runtime identities, hardware, and the budget.
There are two calibration and four confirmation blocks. Each block contains
six checkpoints times three inputs times two implementations times four
complete calls. Thus the queued confirmation workload is **288 calls per
implementation**; 864 calls total include both implementations and calibration.
There is no production call-volume assumption. Orders alternate by block and
cell. No claim of independent timing samples or population confidence coverage
is made: blocks are separately executed time periods on one shared host.

After calibration, before any confirmation call, a deterministic chooser seals
its choice. It predicts each queued cell's cost using [0.5*calibration minimum,
2*calibration maximum] for a four-call block. These are predeclared empirical
prediction envelopes, not statistical confidence limits, owner-pinned future
bounds, or scheduler guarantees. Confirmation checks their coverage. CPU is the
explicit research objective, with numerical equivalence, a 512 MiB RSS cap,
and the finite study deadline as constraints. Candidate cost conservatively
charges **all** preparation and calibration CPU, the planned timeout probe,
and a three-second post-analysis reserve, in addition to predicted complete
confirmation tasks. This investment-recovery objective does not hide these
costs as sunk. KEEP_ORIGINAL is chosen unless its predicted lower cost is
strictly larger than that complete candidate upper prediction. Both paths are
nevertheless run in confirmation because comparison is the authorized research
job. A choice is not adoption.

The supervision budget is 120 CPU seconds total across the timeout probe,
scientific child and its imports; the main child has a 114-second soft and
116-second hard CPU limit, and a 240-second wall timeout. A deliberately timed
out **non-model** probe verifies failure accounting; its actual CPU/wall/RSS
and all real failures are recorded. Partial timing rows are retained; there is
no automatic retry. The final independent arithmetic reader is allotted two
CPU seconds and the three-second analysis reserve includes it. These limits
bound abandonment of this finite study, not the successful completion cost of
an arbitrary future deployment.

Full scientific-child CPU/wall/RSS includes import, pin verification, loading,
law preparation, all 12 cache builds, golden array loading, identity checks,
full state reconstruction, serialization/restore, continuation, comparison,
evidence writing, chooser and final bookkeeping. Stage timers are attribution
only: their zeros remain in raw data and block totals are the cost units.
Cache bytes and complete-state bytes are reported separately. Build-only
forward speedups from the older study are not a present estimate.

The three-second analysis reserve is a predeclared accounting allocation, not
an enforced successful-completion upper bound. The review supervisor measures
the independent reader's full process and all remaining science bookkeeping;
if their combined residual exceeds the reserve, the prediction contract is
marked invalid and the final research choice becomes STOP. The final receipt's
own small emission tail is explicitly outside its measured process boundary.

The general NDU v2 result remains KEEP_ORIGINAL_AND_STOP: no production
horizon, enforceable future original lower / candidate upper bounds, or
resource-to-task-utility exchange rates are supplied. The finite empirical
research envelope is never converted into owner-pinned bounds. The study gives
conditional break-even and a CPU/cache-memory Pareto record only. No weights,
optimizer, active pointers, services or trading state are changed.

## Independent peer review

The parent and the continuation-compilation researcher receive this frozen
protocol for review before scientific execution. Any technical failure is
preserved and does not authorize a result-dependent change to the worklist.
