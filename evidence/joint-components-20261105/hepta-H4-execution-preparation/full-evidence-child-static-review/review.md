# H4 full evidence library: subprocess and ignored-helper review

## Finding

No concrete incompatibility was found between the known `authbus_outbox_tests::crash_delivery_child` subprocess and H4's frozen live-to-FD rules. This is a source review, not an H4 gate result. H4's running configuration and repository source remain unchanged.

The review binds all 50 files in `codex-rs/hepta-evidence/src` (717,776 bytes) to commit `6db78eca53a5acdda0d96873d3f4cd65863426f0`, tree `e91f5994017fc5d2cfe58d405a20ee6ad9376772`. Each file's raw Git blob and byte length matches the exact-commit directory response. The source inventory records the fetched API responses or the exact local bytes independently rechecked against that response. The copied six H4 configuration files retain their frozen hashes.

## Why the ignored child does not need the FinalUse exception

`authbus_outbox_tests.rs:507–557` declares the child as `#[ignore = "subprocess crash fixture"]`. The selected parent invokes the current executable directly with `--exact authbus_outbox_tests::crash_delivery_child --ignored --nocapture`. The child writes the claimed delivery ID and exits with status 73 before pool or transaction/session destructors run. The parent requires that exact exit status, reopens the store, reclaims the same ID with fence 2 and attempt count 2, and acknowledges it.

The H4 full-library catalog contains the parent among its 161 unique selected names and contains the child only in its one-element ignored catalog. The live collector checks argv against the selected names before capturing the process or invoking the live-to-FD matcher. Therefore the ignored child's argv is outside this gate's capture selection. Direct `Command::new(current_exe())` also does not invoke the nextest target runner; inheriting the runner environment does not create an FD ledger entry for that direct child. The 161 selected outer test processes remain subject to the original exact FD record/outcome bijection.

The fixed FinalUse self-spawn exception applies only to its own gate, crate and one selected case. It is not used here and must not be widened for this ignored child. This review also does not claim an independently captured child PID/image: the parent test's crash and durable-state assertions provide its test evidence, while the ignored child has no separate selected-test credit.

## Output parsing and ignored classification

The child inherits stdout and stderr, but exits inside the test before libtest emits a terminal `test … ok` result. The previous full-library raw log at source `a877333eff1577179fce8b1ceb6edf4322440e03` shows two `running 1 test` banners for this parent/child and exactly one terminal outcome for the parent. The frozen H4 outcome regex matches the parent once and does not match a child terminal outcome in that historical raw. The complete historical receipt and raw bytes are retained under `historical/`.

That old run remains a failed run: 159 passed, one failed original per-test timeout, 160 selected, one skipped; it is not substituted for H4's 161-case run. Its raw SHA is `c371a078ac81af780b11ea5a71c1c29f0edf51e24f3a66211b3a84ebb43d4421`.

H4 still requires the real current run to report exactly 161 selected and one skipped, to pass every exact selected name once, and to satisfy the FD ledger. Only after that succeeds does the coordinator invoke the same already-captured image with `--list --ignored --format terse` and require exactly the declared child name. This is a list operation, not an extra execution of the ignored crash fixture. The source wrapper retains its original minimum of 22 and 600-second command budget; the coordinator's stricter 161-name requirement remains intact. The original per-test 60 seconds and total 5,400 seconds are unchanged.

## Other local subprocess sites

The explicit process/ignore inventory across all 50 source files finds only this `current_exe`/`std::process::Command` launch, its `process::exit(73)`, and its ignored attribute. Three `tokio::spawn` occurrences in `provider_effect_tests.rs` create asynchronous tasks in the same process; they are not additional libtest executions. This scoped syntax/source review is not a proof about arbitrary dependency internals or hidden runtime behavior.

## Execution boundary

No native test, Cargo, desktop operation, learning trial, remote bulk read, source edit, or configuration mutation was performed. The H1 download remains paused with zero in-flight requests. No additional test or generic helper allowance is proposed. The next evidence is H4's actual full-library receipt, complete raw log and FD/live artifacts.
