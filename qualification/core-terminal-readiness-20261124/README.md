# Terminal readiness and shutdown ownership regression

The observed CI failure was a public terminal event delivered before the
owner completed persistence, recovery publication, idle cleanup and admission
fence retirement. Immediate settings or the next turn could fail as
terminalizing after a client had already received completion.

## Reviewable stages

The production change separates durable terminal preparation, atomic event
delivery plus admission opening, and the remaining shutdown completion fence.
New logic lives in two small private modules. Registry tuple changes are
mechanical; the existing error, recovery-generation and shutdown checks remain.
A first test stage covers complete/abort lifecycle barriers and a public
TestCodex integration test with an actual extension barrier and two HTTP
response fixtures. A second stage uses a real registered parent and delegating
in-memory store to block parent persistence, verify immediate next-turn
admission, and verify shutdown still waits for that old owner.

## Behaviors requiring the final integrated CI

1. Completion and abort are invisible while their lifecycle cleanup is held.
2. Terminal receipt admits settings and the next turn without a settling delay.
3. A blocked parent notification does not prevent the next turn from starting.
4. An old parent notification cannot overwrite the new Running agent status.
5. Shutdown remains sealed and drains parent delivery through the same owner.
6. Existing cancellation, recovery-generation, persistence-failure and
   start-transition tests continue to pass.

The local scoped `just test --locked -p codex-core --lib` attempt compiled
production dependencies and reached the core test binary, then rustc ended
with signal 9 (SIGKILL) after 493.33 seconds. It executed no tests. The signal
alone does not establish the operating system's reason. Parent and public
integration regressions were added after that attempt and are also unverified.
Repository formatting and `git diff --check` passed. Actual behavior, Clippy,
and full regression validation remain pending on the final normal CI head;
this source receipt does not claim those checks passed.
