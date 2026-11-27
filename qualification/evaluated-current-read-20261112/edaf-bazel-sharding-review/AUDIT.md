# Agentd Bazel 300-second timeout: scoped configuration candidate

This is a configuration of the existing method-sharding runner. It neither dispatches Bazel nor changes product permissions, Rust test bodies, ignores or deadlines.

## Fixed evidence and source

- Diagnosis source: `9fac31e6f89569f0c582fc2a9cc2bf0b8f05c7ca`.
- The two changed base files were also read at `edaf1d9a420dc99336f36b24515eb9c65a97b0da` and are byte-identical.
- Original Bazel run `43254706563`: jobs `131310622854` and `131310622804` both ended with the target timeout at 300.0 seconds.
- Each original target announced 1190 methods, with 917 explicit ok, 15 FAILED, 87 existing ignored, and 171 lacking a terminal status. These are not completed results.
- The normalized target output is identical across those two jobs; do not turn duplicated observations or shards into independent samples.
- Native run `43254705812`, job `131309678676`, completed 1738 methods across five crates in 845.718 test seconds: 1726 pass, 11 fail, one timeout. The agentd portion is 1094 methods.
- All raw log parts were reassembled and checked against the original complete SHA256 values. No old log or failed result is rewritten.

## Two-file implementation

`defs.bzl` appends two optional parameters, preserving every old positional parameter and default: `unit_test_threads=0` and `unit_test_flaky=None`. They apply only to the generated library-unit target. The thread count goes through the existing `workspace_root_test.test_threads` attribute into `RUST_TEST_THREADS`. An explicit flaky override is applied after the existing sharded-target default.

`codex-rs/hepta-agentd/BUILD.bazel` selects eight shards for only `hepta-agentd-unit-tests`, two libtest test bodies per process, and `flaky=False`. All other targets retain their prior behavior. No timeout attribute is added or changed: each shard keeps the default moderate 300-second timeout.

No `unit_test_args` is added. This matters because both existing launchers bypass sharding when any positional libtest argument or a method filter supplied through TESTBRIDGE_TEST_ONLY is present. The existing target-level --test_tag_filters does not trigger this bypass. A `--test-threads` argument would therefore be incorrect here.

## Existing full-roster sharding

The unchanged shell/Windows launchers obtain the real binary's `--list --format terse`, compute FNV-1a 32-bit over the exact method-name bytes, and assign each method to `hash % 8`. They touch the native Bazel shard-status file and execute assigned names with `--exact`. No method is renamed.

The unchanged macro otherwise marks sharded tests flaky. The explicit agentd override disables that default automatic retry. The actual workflow/configuration was read and contains no `flaky_test_attempts` override. Future evidence must still verify attempt 1 only; a later external override cannot be silently accepted.

Linux uses one libtest process per shard. Eight simultaneous shards can therefore have up to 16 libtest test bodies running, in addition to unchanged Tokio or fixture threads. Windows uses the existing 7000-character batches, carries a sticky failure result across batches, and keeps the same per-method assignment. The outer Windows workflow partitions target labels across four hosts; it does not itself split this one target's methods.

## Old native durations: estimate only

| Shard | Timed agentd methods | Old pass/fail/timeout | Sum of old method seconds | Simulated two-worker seconds |
|---:|---:|---:|---:|---:|
| 0 | 141 | 139/2/0 | 238.342 | 119.352 |
| 1 | 143 | 142/1/0 | 180.043 | 95.824 |
| 2 | 118 | 118/0/0 | 102.417 | 55.609 |
| 3 | 138 | 137/1/0 | 296.108 | 148.902 |
| 4 | 133 | 130/2/1 | 329.889 | 165.506 |
| 5 | 133 | 133/0/0 | 88.295 | 46.232 |
| 6 | 146 | 143/3/0 | 264.977 | 133.570 |
| 7 | 142 | 140/2/0 | 143.767 | 72.161 |

The full 1738-method record retains exact crate/name/status, reported duration, original log lines and the applicable agentd shard. Its 1094 agentd entries form a disjoint eight-way union. The other 644 entries are not assigned to this target.

These estimates are not Bazel measurements or guarantees. In particular, the old 60.007-second timeout is censored; fixes can make previously failing paths run further. Windows process startup, RBE resource contention and platform-specific methods are also absent from this estimate.

Only 935 native agentd names can currently be matched to the partial Bazel output. Membership of the other 159 is unconfirmed. The original Bazel output exposes 1022 distinct method names but has 171 missing terminal statuses; it does not provide the complete 1190-name roster. Do not fill that gap by assuming Cargo and Bazel inventories are identical.

## Required evidence before calling this closed

1. Preserve the new source/tree, configuration, actual binary identity, native shard count and attempt identities.
2. Obtain the complete list from that same compiled binary and all eight actual shard results. Check exact FNV membership, pairwise disjointness and union equality; preserve original ignored identities.
3. Verify no extra libtest/test-filter argument bypassed sharding and no existing skip-filter matches silently removed an agentd method.
4. Keep any FAILED, TIMEOUT, missing result or changed roster visible. A passing retry cannot replace a failed first attempt.
5. Every shard must finish within the unchanged 300 seconds. Preserve all original method-level time/owner checks; the libtest “over 60 seconds” message is a warning, not the native nextest timeout.
6. Run only the already authorized same-source `just test` gate and observe the existing automatic Bazel workflow. This candidate introduces no manual Bazel execution or new workflow.

The candidate does not add a roster collector or claim the missing complete Bazel roster is already archived. If the original runner/configuration cannot deliver complete results under the unchanged cap, that remains an explicit blocker.

## Current status

Code postimages are byte-verified and independently reviewed as source. No formatter, Starlark/Bazel analysis, native tests or new CI run was executed for this candidate. This engineering configuration conveys no original owner capability or scientific efficacy result.

Official protocol references: [Bazel test timeout and sharding](https://bazel.build/reference/test-encyclopedia), [common test attributes](https://bazel.build/reference/be/common-definitions), and [retry command-line precedence](https://bazel.build/reference/command-line-reference). Repository-specific behavior is pinned in the manifest.
