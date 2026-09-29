# Neuron V2 startup recovery and lifecycle readiness

This document specifies the daemon-side startup contract for
`AgentdNeuronGenerationControllerV2`. It narrows the general control-plane
contract to one question: when may a recovered generation reopen its execution
gate?

The answer is deliberately strict. Local replay completing successfully is not
enough. The active generation and every retained historical generation must have
no unresolved operation and no pending witness acknowledgement before a lifecycle
transition can advertise readiness.

## Permission boundaries

Startup recovery keeps the same four boundaries as ordinary runtime operation:

1. **New-work admission** remains closed while the controller is `Starting`.
2. **Existing-operation recovery** may query only the exact durable operation
   identity and provider ledger. It does not call provider `execute`.
3. **Terminal truth query** remains available through operation-state APIs and
   grants no execution authority.
4. **Result-use authorization** remains a separate current guard check. Recovery
   reports omit the model result and cannot release it.

`AgentdNeuronGenerationControllerV2::recover_existing_operation` is the canonical
lifecycle-aware recovery entry:

| Controller state | Recovery policy |
| --- | --- |
| `Starting` | Preserve a proven-unexecuted operation; reconcile an exact dispatched identity by query only. |
| `Serving` | Preserve a proven-unexecuted operation so the same key may resume under live admission. |
| `Quiescing` | Close only a proven-unexecuted operation; an unknown provider outcome remains pending. |
| `Sealed`, `Reloading`, `Stopped`, `Failed` | Reject the transition and require the corresponding lifecycle action. |

`close_unexecuted_operation` is an explicit fenced administrative action available
only in `Starting` or `Quiescing`. It may write terminal `AdmissionDenied` history
for an undispatched reservation or authoritative provider `NotStarted` result. It
cannot convert an unknown result, corrupt store, poisoned owner or unavailable
provider into a negative business outcome.

The older controller `recover_operation` entry remains a compatibility surface for
serving/quiescing callers. New daemon integration should use
`recover_existing_operation` so startup and steady-state recovery follow one
documented policy table.

## Readiness postcondition

`AgentdNeuronHandleV2::reconcile_control` now has a lifecycle postcondition:

```text
local reconciliation succeeded
AND pending_operation_code is absent
AND pending_witness_count is zero
```

Otherwise it returns the stable `pending_recovery` control error. This makes the
same condition authoritative for controller start, seal and successor readiness.
A successful local replay is never interpreted as proof that provider truth or
witness acknowledgement has converged.

A recovered `Starting` controller therefore follows this sequence:

1. Construct and fence the active and retained handles.
2. Reconcile retained generations. Any unfinished historical work is an error.
3. Reconcile the active generation.
4. Query exact pending state and use `recover_existing_operation` as needed.
5. Preserve unknown or proven-unexecuted work unless an operator explicitly closes
   the latter through `close_unexecuted_operation`.
6. Re-run `start`.
7. Persist `Serving`, then open only the active generation gate.

At no point does startup recovery open a gate temporarily or authorize a fresh
provider dispatch. Prepared handle clones remain fenced until the final successful
`start`.

## Failure interpretation

The following signals require different actions:

| Stable signal | Operator action |
| --- | --- |
| `owner_busy` | Retry the administrative observation with bounded backoff. |
| `owner_poisoned` | Reconstruct the owner from durable stores; do not retry the business request. |
| `pending_recovery` | Inspect exact operation and witness state; run query-only recovery. |
| `outcome_unknown` | Reconcile the exact provider identity. Never issue blind execution. |
| `reserved_not_executed` | Preserve for live-admitted resume or explicitly close while fenced. |
| `committed_witness_pending` | Reconcile the witness; do not rerun inference. |
| `admission_denied` | Return the durable terminal failure for that exact key. |

Maintenance mode or authority withdrawal may reject new work while still allowing
query-only convergence of an operation that crossed the dispatch boundary.
Current-use authorization remains mandatory before any committed result is exposed.

## Storage and measurement contract

This change does not alter HPTNGS02 or HPTNGI02 bytes, checkpoint/full-receipt
payload equality, failure tombstones, provider identities or witness lineage.
The complete receipt materialization remains part of the current recovery format.

Diagnostics now report both absolute phase latency and independent per-request
shares, in basis points, for receipt encoding, full-receipt materialization,
generation/index sync and witness sync. The shares overlap where one phase is
nested inside another and must not be summed as disjoint accounting. They identify
where a separately versioned migration may be worthwhile; they do not authorize
changing persisted meaning.

## Qualification evidence

Every architecture lane must:

- bind source SHA, fixed integration base, tested commit and tested tree;
- build the real same-candidate Codex executable before worker-host tests;
- compile and lint Neuron, Agentd and worker-host ownership targets;
- execute only Agentd tests owned by `neuron_runtime_v2`;
- reject tracked or untracked source mutation after validation;
- bind diagnostic samples to the actual tested commit, including a synthetic
  merge commit rather than relabelling it as the source-branch SHA;
- retain the complete validation logs and diagnostic summary;
- aggregate every matrix lane into an explicit result job.

The committed workflow defines the intended checks. Only a completed run for the
exact commit establishes an executed pass.
