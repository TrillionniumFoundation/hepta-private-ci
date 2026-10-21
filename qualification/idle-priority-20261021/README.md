# Deferred idle priority qualification — 2026-10-21

Source fix: `509e332e5e0d6869063b62cb3ae81919380d1e04`, based on `9d4564d2c`.

## Failure and correction

An older external idle notification can finish its Queue callback after a new turn has entered terminalization, then register Goal against that new fence before the terminalizer itself reaches Queue. A single registration-order tail lets this older Goal start before already queued user input. Goal runtime's continuation-deferral flag does not inspect the user queue.

The fix separates queued-input and automatic-continuation completion tails. Each class preserves its own registration order. Automatic work waits for its own fence and then snapshots and waits for the current queued-input tail. A queued job never depends on an automatic job, so this dependency graph cannot form the former cross-priority wait cycle. Same-fence Queue callbacks have all registered before the terminalizer completes that fence. The shared 32-job capacity, termination cancellation, status rechecks, normal Core admission and queue persistence ownership remain in force.

## Executed evidence

| Check | Result |
| --- | --- |
| Exact scheduler source plus its unit tests, isolated harness | 4 passed, 0 skipped |
| Original single-tail scheduler with the new ordering regression | Failed twice: `automatic-1` preceded `queued-1` |
| Scoped isolated `just fix` | Exit 0, no source fixups |
| Repository `just fmt` | Exit 0 |
| Source diff and complete-file inspection | Clean; source commit contains seven files |

The scheduler harness compiles the product `idle_work.rs` directly and loads its sibling tests. Only unrelated `CodexThread` wiring and the protocol error type are stubs; those stubs are not exercised by the four scheduler tests. The same-fence regression verifies queued-1, queued-2, automatic-1, automatic-2 ordering, and the termination regression cancels 32 pending jobs across both classes and verifies all capacity is returned. The baseline adds only an unused priority parameter/enum plus `FutureExt` needed to compile the new tests; its scheduling logic is the original implementation.

A real Queue/Core integration regression, `queued_input_precedes_an_older_automatic_notification_at_the_same_fence`, is included in `codex-rs/ext/queue/tests/queue_service.rs`. It gates the terminalizer before the real Queue callback, registers automatic work first, then verifies Queue owns the next turn while automatic normal admission returns NotSubmitted and the exact queue row has been consumed. Its live response is held with an SSE gate. **That integration test was not executed locally**: the parent reserved the machine for the research model after a prior broad build exhausted disk. Full Core, Queue, Goal and TUI compilation/execution are assigned to the original hosted CI gates.

Raw logs include the first harness configuration failure (full workspace filters did not match the isolated package) and the first Clippy attempt blocked from binding its local lock listener. The isolated profile then retained the repository's general defaults; the localhost-enabled Clippy retry passed. No product gate or advisory policy was changed.

Tests ran before the required formatter pass. Both the tested-source hashes and final source hashes are retained. Tests were not rerun after formatting, in accordance with AGENTS.md. The lightweight target was independent of the shared product target.

## Reproduction

From the repository root with the pinned Rust and nextest tools available:

```sh
just test --manifest-path "$PWD/qualification/idle-priority-20261021/harness/Cargo.toml" -p idle-priority-harness --locked --test-threads 2
just test --manifest-path "$PWD/qualification/idle-priority-20261021/baseline/Cargo.toml" -p idle-priority-harness --locked -E 'test(later_queued_input_precedes_automatic_work_observing_the_same_fence)'
```

The second command is expected to fail and is only a regression control. It is outside the product Cargo workspace. The archived Cargo locks belong only to these independent evidence harnesses; product Cargo.lock and MODULE.bazel.lock are unchanged by the priority fix.
