# Native copyout fault boundary

`hos2_copyout.rs` remains part of the original `FileTransport`. Normal calls use
their original input and output buffers. An explicit crate-private qualification
arm may replace only the response address for one exact 96-byte Install frame
with a real `PROT_NONE` mapping. The same encoder supplies the arm and the actual
dispatch; the complete original request bytes must match. Read and history calls,
or an Install with any changed payload byte, do not consume the arm.

There is exactly one synchronous ioctl per transport call. Its actual return and
errno are captured immediately, before cleanup or notification. No errno, applied
result, replacement device, grant, delivery sequence or terminal can be supplied
by a run plan. A second call cannot repeat the selected fault. A fake transport
does not expose these native diagnostics.

An actual EFAULT means the response was unavailable. Only the original writer's
retained D query determines whether an effect happened. Its original FinalUse
closure, HOS2 dispatch guard and SQLite effect-entry barrier remain in force
through the ioctl and any bounded Root fault notification. Notifications must not
reenter the held FinalUse frontier. The original outbox reconciles Unknown and
never resends it. Diagnostic call counts and request digests are observations,
not another delivery ledger or an authority.

The Linux unit tests perform real refused ioctls on `/dev/null` and prove that
ENOTTY is not reported as EFAULT, callbacks are not invoked on that refusal,
selection binds all input bytes, and invalid capacity fails before a call. They
do not qualify a native CPU effect. Actual Asterinas acceptance separately needs
both a live-writer lost response and Manager death after the native call but
before source settlement, with the exact original K/D, terminal, Current,
independent consumer frontiers and no duplicate Install.
