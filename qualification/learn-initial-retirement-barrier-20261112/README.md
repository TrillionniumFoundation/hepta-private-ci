# Original Initial retirement barrier source correction

The Root-observed `f07963e408ea14cc00f803acc1c710b40f742d58` native failures both reported timeout at the refresh-barrier phase. Original full stderr is preserved in the neighboring completed-history evidence archive. The former helper ran synchronous `task.require_bundle` inside its 500ms timeout before the first await, so that phase alone does not measure time spent waiting for the barrier.

This source-only correction is `55e934222295a7a36626ce9f624832b569b103ee` followed by diagnostics `269afa554452a467dc5f76eec0c52e4efcc5b8bb` (tree `3b9fdbc9570f6526e774e6c2c7e45666024467d2`). The actual retained task check now completes at the callsite before the unchanged 500ms barrier/Drop/worker-completion timer. The helper still waits for the original serial permit, verifies the actual current observation and healthy original worker, performs actual session Drop, and waits for that worker to finish. The retained task must still refuse afterward and the claims bytes must stay equal.

No product timeout, session end, authority check, execution worker count, or native permission was changed. The parent STABLE receive uses its original 15s LIFETIME, not an additional 500ms timer around the precheck. Added timings report actual precheck, serial wait, Drop/join and total retirement durations.

Formatter, diff check, source identity and static invariant checks completed. No native test was run for this candidate here. The next exact-source native test is required to establish whether the concrete observed failure is resolved; this is not a passing retirement or whole-chain result.
