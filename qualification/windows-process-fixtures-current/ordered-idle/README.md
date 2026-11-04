# Restore queued idle work after exact turn completion

The retained source and base-merge runs of #4755 both failed the same original cases: Git 31/33 and queue 33/35. Their original artifact identities, source bindings and readback jobs are recorded in ORIGINAL_FAILURES.json. Readback success preserves these failures.

The queue callback ran while Core still retained the exact terminalization completion fence. Normal StartIfIdle therefore refused admission; after the callback returned there was no deferred wake for the queued item. This candidate restores the bounded ordered idle-work adapter and completion observer from immutable source112c, plus the exact 1052-byte queue deferral block. It does not remove a completion fence, add admission authority, or globally wait in unrelated turn-input APIs.

The original two asynchronous adapter controls remain. An additional control cancels the predecessor completion, verifies that its work did not run, and requires a follower to remain blocked until its own fence completes. The separate selected core test command must execute all three exact controls. Its other filtered core cases are reported explicitly; it is not the full Core owner suite. The original Git33/queue35 argv, acceptance parser, source/merge matrix, deadlines and assertions remain unchanged.

The Git readiness failures are not yet explained. Two small files record the original parent script's before/after-child-launch stage and the child's first script stage. They run inside the original measured fixture process tree. There is no preparatory PowerShell process, broader environment forwarding, JobObject change, increased readiness time or relaxed cleanup assertion.

The existing generation job runs the repository formatter and original Cargo/Bazel lock commands. A changed generated source must be adopted and rerun before the native gates qualify. Native output adds a bounded fixed-field diagnostic summary; arbitrary original output remains in the retained artifacts. No local execution is claimed because this session has no usable execution environment.

DRAFT / HOLD. The current source, combined owner suites, HIA/HCSN scientific gates and full original archive/history clearance remain separate qualifications. No original Library item was deleted.
