# CPU budget and cost accounting

`joint_budget.py` runs one fresh, audited Linux fit worker and enforces the
registered CPU/wall admission contract. Its authoritative measurement is
`wait4` user+system CPU, including the same-process exec wrapper, interpreter,
imports, initialization, collection, optimization, diagnostics, export and exit.
All worker threads count. The worker must not create subprocesses; observed
additional process-group members cause rejection. This is not a security sandbox.

`BudgetSpec` is fixed before fitting. It declares nominal standalone CPU, an
overrun tolerance, an actual matching band, maximum between-family CPU spread,
wall limit and an export reserve. A zero exit code does not establish admission.
Live monitoring and the final CPU measurement reject excess; no post-hoc budget
increase or deleted fit is allowed. An early successful worker may be admitted
but still fail the actual matching gate. Empty work to fill the band is forbidden.

The parent PID namespace and mounted `/proc` namespace differ in this executor.
The same-process exec wrapper first writes a handshake using `/proc/self/stat`;
monitoring uses that actual mounted-process identity, not `Popen.pid`. The
parent PID is checked, and the final CPU measurement remains independent `wait4`.
`RLIMIT_CPU` is a deliberately wider catastrophic backstop: soft limit is
`ceil(cpu_backstop_multiplier * (scientific_cpu_limit - shared_cpu))`, with
registered multiplier 2 and hard limit soft+1. The actual values and initial
PROF/SCHED/rusage clocks are recorded in handshake and receipt. Linux raw PROF
and the registered adjusted/SCHED CPU counters can differ; the backstop is never
the scientific admission threshold. Polling is not a universal hard bound
on the overshoot of a noncooperative program. Such a run still cannot be admitted
when its final CPU exceeds the registered limit.

## Worker interface

```python
from .joint_budget import BudgetCheckpoint
budget = BudgetCheckpoint.from_env()
while budget.can_continue(estimated_next_batch_cpu_seconds):
    collect_or_optimize_one_bounded_batch()
export_final_model_and_receipts()
```

The checkpoint uses CPU since process execution, not since this Python object
was created. The export reserve is an allowance, not free time: export and exit
still consume the budget. A too-large next batch/export that exhausts the final
limit produces a rejected fit. Record actual collection and update counts.

Run from the repository root, with a new output directory:

```bash
python -m tools.hcsn.digital_joint_20261102.joint_budget --spec registered_budget.json --out /tmp/new-fit-budget --shared-receipt /tmp/shared-budget/RECEIPT.json --consumers 5 -- python -m tools.hcsn.digital_joint_20261102.joint_train <registered-worker-arguments>
```

Generate shared data/calibration/teacher inputs in their own measured process,
using the same launcher without `--shared-receipt`. Each fit is charged the
complete admitted preparation CPU; its worker has only the remaining allowance.
Shared content/teacher work performed later during policy collection belongs in
that fit's worker. It cannot be moved outside the measured process and omitted.

Two ledgers are explicit: standalone cost charges each independently deployed
model the full preparation; amortized cost divides preparation over its actual,
registered consumers. `cost_ledger(receipts)` refuses a consumer-count mismatch.
Physical campaign CPU counts preparation once, all launched workers including
failures, and observed monitor overhead separately. `match_group(receipts)`
requires every worker's actual band and the registered maximum CPU spread.

Monitor CPU is measurement overhead and is not inside the worker CPU limit.
The receipt records the monitor interval, including shared preparation monitoring
once in the settled ledger. It excludes supervisor imports, final receipt writing
and supervisor exit, and any outer campaign launcher. Therefore this harness by
itself does **not** prove complete end-to-end system cost or energy advantage.
CPU admission is separate from utility, latency, throughput and adoption gates.

## Actual instrumentation qualification

`evidence/joint_budget_profile_backstop_v2/SUMMARY.json` passes ten process checks.
The two bounded optimization workers use standalone CPU 1.930001/1.933951 s;
their difference is 0.003950 s within the registered 0.2 s maximum. Actual CPU
overrun, wall overrun and unsupported subprocess controls are rejected; a short
successful worker is not called matched. These are NumPy optimization workloads
for instrumentation, not results for the proposed neural model. A real child
that completes successfully before a delayed supervisor reaps it is also rejected
when final elapsed wall exceeds the limit: observed 0.315304 s versus 0.1 s.

The failed `attempt1` misread the namespace PID as the mounted PID and incorrectly
rejected a worker; its exact source SHA and failed receipt are retained. The later
`final2` optimization depended on unavailable `/proc/.../children` files, failed
the subprocess-control check, and was rejected. The proven process-group scan
was restored. Independent review then found a missing final wall check for a
child finishing between polls; the check and ninth regression were added before
formal fitting. The first formal attempt then exposed an early SIGXCPU at measured
worker 51.424929 s with a predicted raw-clock backstop of 55 s. An independent
Torch probe configured soft6/hard8 and observed SIGXCPU at raw PROF 6.003868 s
versus SCHED/process_time 5.270492 s. This establishes clock inequality here, not
a full reconstruction of fit23's drift. The root authorized a wider 2x backstop
under a new source identity and complete-stage rerun; scientific nominal60/2%,
cooperative deadline and matching rules stayed fixed. The new actual control has
RLIMIT2/3 but scientific limit .51 s, and is strictly rejected by parent SIGTERM
at worker .525961 s. Present source SHA is
`4c901817936db0c0afa5336fbf10185a4faf98cf4a905dc7796b9d089d85cab6`.
Earlier profiles and the old formal receipt/source are retained as development
or failed evidence. Rejected subprocess-violation attempts are outside the
supported accounting profile: un-waited descendant CPU is not guaranteed counted.

GPU and energy adoption gates remain **HOLD**: this executor exposes no standard
GPU device or accessible powercap energy counter. Missing measurements are null,
never zero. CPU evidence is not substituted for GPU or joule measurements.
