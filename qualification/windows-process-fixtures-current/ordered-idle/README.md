# Preserve completion ordering and original Windows process cleanup

The current fixture follow-up addresses two independently observed failures while preserving the production implementation from cfb729fdeacbdb7bb146d1ef5dfd370f0db2fa3c.

The queue test now exactly reuses historical Git blob fedaf7eda73d79403a2287d7ce8e7966a2c242f8 from source112c. The sole difference from the preceding fixture is its original three-line observation of pending turn terminalization after TurnComplete and before the externally invoked idle callback. The completion observer is now available in this stack and remains bounded by the original watchdog. All 35 cases and all 131 assertion lines are byte-identical. There is no polling allowance or new timeout. The queue callback's deferred work, FIFO registration, 32-entry capacity and normal atomic admission remain unchanged.

The Git fixture's original stage markers show that both 3cd executions and the cfb base-merge execution reached the parent-before-child-launch marker but did not return from Start-Process within the original readiness deadline. The cfb source-head execution passed all 33 Git tests, so the evidence does not establish a universal startup failure or its framework-level cause. This candidate uses System.Diagnostics.Process.Start with UseShellExecute=false for the same real child. Both UTF-16LE EncodedCommand arguments, PID and readiness files, inherited standard handles, Job Object ownership, parent lifetime cases, 30-second readiness, 100-millisecond production timeout, 10-second parent-exit wait and 3-second survivor observation are preserved. There is no PowerShell prewarm.

The earlier ordered idle-work restoration remains: Core's exact completion fence survives the callback, and the registered work waits outside it before entering unchanged normal admission. The strengthened cancellation control now has real cfb source and merge execution: all three selected controls passed on each, with 2331 other Core cases explicitly filtered. This is not full Core qualification.

## Retained evidence

Both original 3cd ZIPs were independently downloaded and verified by the read-only bridge. Each had 9102 exact Git-bound inputs and equal before/after snapshots. Original Git was 31/33; queue was 34/35. The only queue failure was duplicate_queued_client_ids_dispatch_to_core_once at its original immediate empty-list assertion. Both previously failing queue lifecycle cases passed. The six complete original test logs under failed-3cd were reconstructed from the bridge output and accepted only after their bytes matched the original recorded SHA-256, including line endings.

The cfb generation job executed all eight commands successfully with unchanged generated Cargo and Bazel locks. Its source-head Git was 33/33 and base-merge Git was 31/33; both queue runs were 34/35. The cfb artifact ZIPs were not independently replayed here, and their single queue failure is not assigned an exact name from the older 3cd evidence. The recorded job identities and diagnostics retain that scope.

The current successor must pass the original formatter and committed-lock generator, followed by fresh full Git33/queue35 and the three selected control tests on both source-head and actual base-merge. The original command arguments, test acceptance parser, matrix, deadlines and retry settings are unchanged. No local execution is claimed because this session has no usable executor.

DRAFT / HOLD. Combined owner suites, HIA/HCSN scientific gates and original archive/history clearance remain separate. No original Library item was deleted.
