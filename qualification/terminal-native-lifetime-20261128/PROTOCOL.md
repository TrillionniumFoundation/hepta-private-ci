# Terminal native worker lifetime qualification

Prospective engineering scope, registered before either new control executes.
Base source: `7fc08f759e7fb3103b9e18e666ebdee98a1115a8`.
The prior 26-control cohort remains a separate execution and is not rerun here.

## Defect and intended boundary

The existing terminal owner moves its sole compute permit and Ledger reference
into `spawn_blocking`. Dropping the async waiter cannot stop an already running
blocking job. The old Agentd drain predicates did not observe that permit.

The change retains the same compute semaphore, jobs and actual Ledger. Closing
the semaphore and acquiring its permit share Tokio's admission boundary. The
permit remains inside the real blocking closure until that closure exits,
including when its async waiter or JoinHandle has already disappeared.
No separate guessed active counter, resettable lane or replacement writer is
introduced. The one registered lifetime is pinned by Arc identity in AgentdState.
Registration shares the existing runtime-state mutex with drain/fence changes;
late attachment to a closed runtime is refused before installing any lane.
Early generation/root mismatch errors leave a private sticky terminal fence
under that same mutex, even when the existing lifecycle cache still says Running.

Runtime cancellation, runtime-future drop, drain and generation fencing close
new native admission. A small shared entry mutex orders Pending-to-Running against close; it never
covers the long fit. The Running transition is the fit-entry linearization
point and checks the original cancellation token. A cancellation racing after
that successful transition cannot undo admitted work, even if the thread is
scheduled later before calling the existing fit. Such work remains non-preemptible. Cancellation does not prove that
such work stopped; its retained permit continues to block drain until actual exit.
Remote permission changes remain subject to the existing authenticated checks;
this scope does not promise instantaneous distributed revocation.

The real Agentd drain loop, both waiting phases and its final decision, and the
existing `DrainSnapshot.drained` predicate consult the same registered lane.
No wire field or Circuit count is repurposed. An independent unsupervised owner
does not gain a runtime shutdown acknowledgement from these private interfaces.

## Frozen controls

Exactly two new functions under
`plasticity_runtime::lifetime_tests::terminal_learning_tests::native_lifetime_tests::`:

1. `cancellation_before_fit_keeps_real_worker_tracked_until_exit`
2. `draining_closes_native_admission_and_cannot_finish_with_live_worker`

Both use the unchanged existing authorized synthetic Ledger/Memory fixture and
the actual native owner, supervised runtime, command channel and blocking worker.
A per-owner test-only barrier pauses the real worker before the pre-fit gate.
The first cancels and joins the outer runtime while keeping that worker paused:
the original Ledger must remain locked and the registered blocker must stay one.
It also rejects substitution of another owner's lane. Releasing the worker must
reach the closed gate, execute zero fit calls, release the original permit and
make the blocker zero.

The second transitions the real fixture Fleet to Draining and polls the actual
Agentd drain future. With no turn/Circuit/generation work, the terminal worker
must keep it pending. Its current DrainSnapshot must refuse drained status.
An already Draining state with no registered lane must reject late attachment
without replacing the worker's original state or installing a new lane.
An earlier cached Running state must also reject installation after an actual
Fleet generation rejection, despite having had no lane when the fence occurred.
Only after the real worker leaves may the drain future complete. The standalone
fixture does not claim a successful real App Server drain handshake.

Both fit-entry counters must be exactly zero before and after worker release.
No additional native fit, tokenizer/feature conversion, new scientific sample,
private historical cache, DEV/final split, E1–E6 or useful-work reward is used.
Each barrier is bounded at ten seconds; all async worker waits are bounded at
five seconds. The exclusive native owner runs only these two exact names under
one 120-second command cap within the remaining original shared 3600-second pool.

## Evidence and source ownership

Freeze exact Git head/tree, source hashes, command, two-name set and remaining
pool before dispatch. Preserve the first refusal/failure, stdout/stderr, actual
elapsed time and selected/completed counts. A metadata mismatch is not a pass;
an expired or unfinished worker remains unknown and cannot certify drain.
Later repair attempts retain earlier evidence and cumulative budget.

Owned changes: terminal owner/native lifetime, terminal runtime, AgentdState's
private lifecycle projection, actual runtime drain call sites, the two controls
and closed CALLERS entries. Existing source/trust/dataset/permission guards stay
in force. No factory, Root issuer, Ledger recovery provider or authority is added.
The factory Arc-claim repair and original 26 controls are separate work.

Actual formatter postimages must be frozen before the first two-control run.
The existing exclusive native owner performs the final scoped `just fix` once;
any post-fix source drift is reported without silently rerunning experiments.
