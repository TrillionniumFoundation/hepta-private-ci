# Legacy child completion during a parent finish

The Linux musl job on e3277e96 failed in two commands. The full-tree six-agent fleet case received a complete, successfully parsed response whose payload was outside the Drain variant. The original diagnostics did not retain that payload. The native Core integration target exhausted shard 14 on a six-second timeout waiting for a completed child's notification in the parent rollout. The archived original attempts, their individual outcomes and SHA256 digests are in original-attempts.json. [Original job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787598/job/137546561415)

In the Core terminal failure, the parent model completed at 07:51:14.071058 UTC and the child model completed at 07:51:14.097735 UTC. At 07:51:14.151638 the original idle injection refused the event while the session was terminalizing or shutting down. The six-second check later failed. The original legacy child watcher attempted one injection. The controlled regression exercised an actual normal parent finish to distinguish the transient lifecycle case from shutdown.

| Original scope | First attempt | Second attempt | Final attempt |
| --- | --- | --- | --- |
| Core shard 9 of 16 | CUA multimodal mock received 5 of 6 | Same mock received 3 of 6 | Passed |
| Core shard 11 of 16 | Network approval denial output assertion | Mock returned HTTP 404 and output differed | Passed |
| Core shard 14 of 16 | Multimodal mock received 5 of 6 | Same mock received 3 of 6 | Child completion notification timed out |
| Fleet, two tests | Six-agent upgrade received a non-Drain payload | | Failed |

A controlled musl unit probe held the real parent finish callback before its owner retired. The original product path returned early and discarded the event. The candidate held the typed child notification until the owner retired, then wrote exactly one notification. The same probe verified no premature write while the fence was held and no accepted notification after explicit shutdown. The baseline added only the test and a test-only call into the original V1 method. Both trees used the same probe semantics. [Source comparison](https://github.com/TrillionniumFoundation/hepta-private-ci/compare/e3277e9677688be5c4c235a7a127f0b51e373399...aad73002ea6b3ce63928cbb3125b23430ec6d7a7)

| Musl measure | Original path | Candidate |
| --- | ---: | ---: |
| Controlled finish ordering | 0/1 | 1/1 |
| Unchanged notification end-to-end test, six-second limit | 3/3 | 3/3 |

The separate replay of the unchanged original fleet target passed both of its original cases in each of three runs. The full target times were 6.88, 14.40 and 8.21 seconds. The observed fleet error remains unexplained at the payload-variant level. A previous complete musl run with the same source blobs passed both the fleet and Core targets. [Earlier complete job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45125165932/job/137528575274) [Scoped replay](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45137315561)

The candidate only routes a concrete SubagentNotification through the additional waiting path. It borrows the current lifecycle completion and reacquires the active-turn guard before the existing recovery revocation, active enqueue or idle history write. Its local await_holding_invalid_type lint expectation documents the guard held through the corresponding write. The paired cases, original compiled sources, archived logs and result coordinates are recorded in paired.json and raw-log-members.json.

The original GNU Clippy aspect completed successfully on the candidate's Core unit binary and its product dependencies. The successful build event was archived. [GNU Clippy](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138242632/job/137569597146)
