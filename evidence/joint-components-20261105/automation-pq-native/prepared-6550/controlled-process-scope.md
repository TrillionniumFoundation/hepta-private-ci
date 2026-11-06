# Controlled ordinary process scope

Base protocol read directly from Hepta 1556a4df6e279055fd8196f81a4ca2fe0f19384a.

- `hepta-agentd/src/state_control.rs::response_with_execution` rejects a request spawn generation before dispatching any method, including health. `client.rs::send` independently requires response spawn generation to equal the original client generation. The old-client health refusal is an exact current protocol assertion; it does not substitute for the old-grant execution refusal.
- `hepta-supervisor/src/control.rs::kill_slot` fences Running to Draining and calls the owned process kill method. `unix.rs` sends SIGKILL. `tick.rs::finalize_exit` removes the exact lease only after an observed exit. This is an owned supervised crash with a pre-fence, not unannounced power loss.
- After a terminal owner and absent lease, `recovery.rs::start_release_slot` makes one CAS to Starting. `hepta-fleet/src/model.rs::successor` uses checked_add(1). Policy preparation uses that terminal successor under one harness writer, then verifies actual leased generation, health PID and live kernel process identity.
- New and old `(pid, start_ticks)` tuples must differ; PID numbers may be reused.
- Qualification requires explicit `HEPTA_PQ_EFFECT_SOURCE_ROOT` and `TESTED_SHA` from the original source guard wrapper. A missing root with TESTED_SHA fails. Nonqualification functional execution records `qualification_binding: false`; no Bazel/runfiles qualification is claimed.
- Original nextest test group, one-case 60-second limit and no retries remain. This target is Linux only because evidence capture uses `/proc`.
- `HEPTA_PQ_EFFECT_PROCESS_EVIDENCE_DIR` holds the actual running service image and phase checkpoints. Checkpoint output is file-only so the original exact-name/no-skip test log guard remains intact.
- The original evidence-frontier and trust bytes are never refreshed at restart. The external fixture FinalUse service stays alive and its frontier must remain exact. Test seeds/services are controlled operator fixtures, not production root custody.

These are implementation and test-design statements. Native execution has not yet qualified this stage.
