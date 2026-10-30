# Owned direct-worker wait4 and finally cleanup

**CONTEXT_RECONSTRUCTION.** The unpublished predecessor workspace disappeared. This source was reconstructed from the preserved API, behavior requirements and failure analysis, and is a new implementation with new hashes. That reconstruction and its original 14-case evidence remain in the frozen execution05 namespace. Execution06 mechanically migrates the owner namespace without changing the ownership algorithm; the current 79-case focused run includes all 14 owner tests, recorded in `DETACHED_LAUNCH_VALIDATION.json`.

## Integration and preservation

The Linux-only entry point is `run_controller(core, callback, receipt_directory, *args, binding=None, term_grace_seconds=1.0, kill_wait_seconds=2.0, **kwargs)`. Place it outside the registered envelope invocation. A cwd proxy and the envelope's observer then wrap the owner proxy, so a fallible wrapper receipt occurs after the real child was already tracked. The object-local `core.subprocess` is restored on exit. The shared subprocess module and global Popen are never patched.

`OwnedChildren` and `OwnedProcess` use the original executable, argv, cwd, environment, process count, group and session. They add no startup stub and do not change process groups. The caller's frozen `verify_job` still validates science source/profile/argv before construction. The owner checks a bounded explicit argv, absolute executable and existing cwd before recording the spawn attempt and calling the original factory. Environment values are not copied to receipts.

The returned child is tracked before fallible identity, pidfd and START receipt work. Its poll/wait methods use `os.wait4` directly and record one real usage observation. They never call raw Popen.poll first. The raw object's returncode is set immediately after wait4, before receipt I/O, preventing later destructor reaping. A repeated wait returns the same stored status without duplicating cost.

## Identity and cleanup

Linux `/proc` must agree with the current controller PID namespace. Every returned child is identified by PID, direct parent PID, start ticks, PGID and SID. A pidfd is acquired while the identity is stable. Signals use that pidfd after checking the identity again; they never target a shared group. An unrelated same-group process survives cleanup, and a changed recorded identity refuses the signal.

On every callback exit, already-exited children are reaped first. Remaining owned children receive TERM, share the configured grace, then receive KILL if necessary, followed by a bounded wait. Default budgets are 1 second and 2 seconds, within the original outer 5-second grace subject to receipt I/O latency. Missing identity, externally lost wait4, unreaped children or receipt failures are explicit incomplete closure, not success.

The original return value or the same original exception object, traceback and SystemExit code is preserved. A finalization failure adds a note to an existing error instead of replacing it. If SIGTERM had its default handler in the main thread, the adapter temporarily converts it to cleanup, restores the handler and resends that signal to itself; the actual controller wait status remains `-SIGTERM`. Custom handlers remain untouched. SIGKILL cannot run finally.

A real Popen constructor may internally reap a failed exec/setup child before raising. The adapter preserves the OSError, records `construction_wait4_unavailable=true`, and does not invent a PID, exact individual CPU, or retry. Its possible startup cost can still be nested inside a separately measured outer controller wait4.

## Receipts and accounting

The fresh exclusive operational receipt directory holds owner INTENT, per-attempt INTENT/START/SIGNAL/WAIT4 or CONSTRUCTION_FAILED, and CLOSURE. Individual JSON receipts are bounded to 64 KiB. CLOSURE records original exceptions, cleanup errors, receipt errors, all returned child identities, actual wait statuses and whether accounting is complete. This is accounting integrity, not scientific success.

Each direct-worker wait4 includes descendants that worker itself waited for. These observations are already nested inside the controller's outer wait4; report them as attribution and never add them again. Wall times and RSS peaks are not additive. Unexpected unwaited grandchildren are outside the established direct-child scope. The owner's own CPU explicitly stops before final summary serialization/write.

## New validation

The historical execution05 reconstruction suite passed 14/14; its old timing is not counted as a new execution06 test. The current execution06 owner cases also passed as part of the independently measured 79-test focused run. It tests exact argv/environment/cwd/group passthrough, normal/nonzero exits, idempotent wait4, MemoryError and SystemExit identity preservation, already-exited children, ignored TERM escalation, changed identity and an unrelated peer, two-child cleanup, actual ENOEXEC, START/final receipt failures, nested observers, actual external SIGTERM and absence of the direct child, and an outer wait4 containing its inner worker CPU.

The exact current source/test hashes, stdout/stderr and per-case actual receipts are in the new WAIT4 record. All child workloads are tiny stdlib fixtures. No scientific tasks, real import materialization, uploads, commits or Rust tests are performed by this component suite.
