# ACT continuation: actual waits and process death

Code source `b0065696ee4642539361d77543fef18837d278b2`, tree
`181fca489f3d1348da9462e216084d6bbfbb4783`, matches the complete local index.
The prior 1,536-row panel remains bound to its own source; it is not relabeled
as a combined async/recovery experiment.

Eight new async tests pass. A real spawned worker waits on its original pipe;
the sole owner can release the admitted invocation once. Read-only timeout,
deadline expiry, EOF and process exit cannot become success. Success requires
the original intent and actual value bytes. Opaque physical completion remains
UNKNOWN. The deadline fences entry to mutations and cannot interrupt a call
already entered.

Nine new durable-control tests pass. Actual subprocess death before/after
publication is followed by another process restoring the original deadline,
pause, conservative primitive accounting, repair budget and unresolved original
identity. A real deadline expires while the original process is gone. Exhausted
budgets remain exhausted. Cooperative concurrent writers are rejected by flock
and SQLite revision checks. Historical actual owner request counts remain null.

Independent review found a concrete receipt bug before publication: replacing
an invocation and its directory hash consistently could be accepted as the
original effect. The fixed implementation binds `task_id:key` on recovery,
observation, audit and apply. The retained red/green materials include actual
post-publication process-death fixtures and SQLite bytes. The red source was
reconstructed by reverting just the unpublished guard, explicitly recorded in
`red.json`; it is not represented as a published vulnerable commit.

The new native gate is [#6127](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6127),
source `b02850c04dcd40f2703e95cc670df531468fd0e3`. It builds the real Agentd/seed
executables and explicitly selects the original Notes launcher integration case.
The previous architecture success had filtered that case out. Fifteen receipt
guard cases, three original nextest parser cases and shell/YAML checks pass;
actual native execution remains NOT_RUN while run 43163424939 is queued.

`BLOCKERS.json` records every retained open gate. In particular, these separate
fixtures do not qualify combined async/restart execution, GRU hidden-state
restoration, production goal-checking host registration, original Root/AuthBus
FinalUse, new independent real applications or full lifetime cost. Both target
health calls timed out at MCP level; target reachability remains UNKNOWN.
The fixed library stays the reference and adoption remains false.
