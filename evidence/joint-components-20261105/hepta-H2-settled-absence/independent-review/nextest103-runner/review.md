# Nextest 0.9.103 target-runner interface review

Scope: independent static review for H2's external executed-ELF recorder. No desktop command, Cargo invocation, native test, or source change was performed by this review. Sparse evidence transfer is a separate read-only operation. This review establishes an interface, not the correctness or successful execution of the forthcoming wrapper.

## Decision

The pinned nextest version supports the proposed same-PID file-descriptor exec wrapper through `CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUNNER` on the existing desktop native build. The original `just test` arguments, test profile, timeout configuration, selected tests, and retry setting can remain unchanged. The runner environment variable and external wrapper are **new execution configuration** and must be explicitly frozen and recorded for H2. This cannot retroactively supply missing H1 executed-binary evidence.

The authoritative source is nextest's `cargo-nextest-0.9.103` tag, tag object `fb4efda7dde6fcc60ad2b9f575570443d32313ad`, pointing to commit `d2e7b879fb79975e8b47a8e3ce569b651e6381c0`. `source-inventory.json` binds all source bytes read for this assessment. This is an API source identity statement, not a signature-verification claim.

## Actual call chain and arguments

Hepta H1 `justfile:88–89` invokes `scripts/run-nextest.py`, setting `RUST_MIN_STACK` and `NEXTEST_PROFILE=local`. Every subprocess branch of that script inherits the environment; it does not erase the Cargo runner variable. Its scoped metadata optimization preserves execution via `cargo nextest run`. The checked-in Cargo configuration contains no runner, and the nextest configuration contains no wrapper-script override. Those four files are pinned to exact H1 bytes in this review; H2 must continue to bind their actual unchanged bytes and any effective parent/user configuration.

Nextest `target_runner.rs:28–39` resolves the host runner and, when no explicit target exists, clones that host runner for target tests. The variable is therefore applicable to the original native invocation, not only cross compilation. Its environment value is split on whitespace without shell quote processing (`parse_runner`); use a whitespace-free absolute executable path, or a whitespace-free interpreter and wrapper path. Do not rely on quoted spaces in the variable.

For each binary, `list/test_list.rs:912–942` runs two discovery commands, concurrently: the runner followed by the binary and `--list --format terse`, with a second invocation adding `--ignored`. Discovery is not a test pass. The wrapper must preserve exact stdout so nextest can parse the list; its evidence must go to separate files, never stdout. Concurrent discovery also requires exclusive, collision-free record names.

For every selected test, `list/test_list.rs:1109–1127` constructs the runner, original binary, `--exact`, the exact test name, `--nocapture`, any applicable `--ignored`, and original extra arguments. `test_command.rs:81–101` sets `NEXTEST_EXECUTION_MODE=process-per-test` and `NEXTEST_TEST_PHASE=list` or `run`. The run path additionally supplies `NEXTEST_RUN_ID` and the attempt indicator. At this version, do not assume discovery has the same run-ID variable: the phase and actual argv are the reliable distinctions in the inspected source.

An effective nextest wrapper script can explicitly ignore a target runner (`TestCommandCli::apply_wrappers`). The checked-in configuration does not do so; external configuration must remain bound, and a missing per-case pre-exec record must fail closed rather than being explained away as a harmless skipped wrapper.

## Timeouts, ownership and evidence

`runner/executor.rs:608` starts the per-test stopwatch before command construction. It applies the original process group before spawning the runner, and starts the existing slow timer immediately after spawn (`688–721`). That timer is not restarted when the runner execs the test. Thus wrapper retention and hashing consume the original test lifecycle budget; the existing small spawn-to-timer initialization boundary remains the same. Default `30s × 2` termination remains 60 seconds for the relevant cases. Existing grace/kill handling, group scheduling, `--retries 0`, stage wrappers, and the outer 5400-second cap must remain unchanged.

On Unix the original child is a process-group leader (`runner/unix.rs:30–31`). A wrapper which performs no fork, does not change process groups, and calls same-PID exec preserves nextest's child/group ownership. It must preserve cwd, stdin/stdout/stderr and the supplied test environment. Any original nextest internal double-spawn machinery still delegates to this same runner command; the wrapper must record its actual PID/start ticks rather than infer them from a fixed parent depth.

Python supports passing an open descriptor to `os.execve` when the platform exposes it in `os.supports_fd`. Check that capability on the actual host and fail explicitly if unavailable. Retaining and hashing the same opened regular ELF descriptor, then executing that descriptor, avoids the path-replacement gap of hashing one pathname and later opening it again for exec. Preserve original argv[0] and every subsequent argument. Flush/close the evidence record before exec; any exec exception must create a failing record and return nonzero. A pre-exec record alone is not proof that a test completed: accept it only together with the real exact-name libtest/nextest result, strict one-record-per-executed-case accounting, no exec-error record, and the frozen wrapper hash.

An open read descriptor does not itself make its inode immutable against another writer. The private target/no-concurrent-build ownership and before/after stat and retained-byte checks remain necessary assumptions to record. Do not claim a general hostile-writer proof. The existing process observer can supply additional evidence but cannot replace missing records, and historical polling misses must remain historical misses.

This is extra measurement overhead. It remains inside the original budgets and must not be subtracted to manufacture a pass or described as identical H1 execution configuration. Small discovery/run utility controls and the actual H2 native results belong to the implementation owner; none were run by this review.

## Primary references

- [Pinned target runner implementation](https://github.com/nextest-rs/nextest/blob/d2e7b879fb79975e8b47a8e3ce569b651e6381c0/nextest-runner/src/target_runner.rs)
- [Pinned list and per-test command construction](https://github.com/nextest-rs/nextest/blob/d2e7b879fb79975e8b47a8e3ce569b651e6381c0/nextest-runner/src/list/test_list.rs)
- [Pinned execution timeout lifecycle](https://github.com/nextest-rs/nextest/blob/d2e7b879fb79975e8b47a8e3ce569b651e6381c0/nextest-runner/src/runner/executor.rs)
- [Pinned test command environment](https://github.com/nextest-rs/nextest/blob/d2e7b879fb79975e8b47a8e3ce569b651e6381c0/nextest-runner/src/test_command.rs)
- [Pinned target runner documentation](https://github.com/nextest-rs/nextest/blob/d2e7b879fb79975e8b47a8e3ce569b651e6381c0/site/src/docs/features/target-runners.md)
- [Python descriptor exec API](https://docs.python.org/3/library/os.html#os.execve)
