# Source52 r28 original project gates — inert preparation

This executor is not runnable in its current state: FROZEN is False and 15 actual source/apply closure bindings are None. No native command or Rust test has been executed from this template.

The source52 candidate adds the existing runtime.rs leaf to the changed-file manifest. All 194 source51 rows must remain byte-for-byte identical; the new manifest must contain exactly 195 rows. Both Git trees must show that the leaf already existed. The native HEAD must remain the original framework commit.

The source50 Bazel lock command remains its historical result. The executor independently checks source50→source52 as exactly three non-build.rs Rust paths and source51→source52 as exactly one runtime.rs path, together with both raw locks. It does not relabel the old generated-source or run another lock update.

The original r24 and r26 failed commands remain separately bound evidence. Source52 admission requires the separate apply-only task's actual completion, postguard, delta and natural outer success.

The original execution order is Python runner suite (32 tests), four-package strict Clippy, then full four-package nextest with zero retries. The original 1,564 binary/name set is checked only after the full test log closes. Source guards and raw-return-code-first bookkeeping are retained. No additional test filter, timeout, ignored-test override, feature flag, source change, or fix/format step is introduced.

The new proof functions and the one-line native HEAD guard are shown in r26-r28-inert.patch. MECHANICAL-READBACK.json records 21 byte-identical functions, including run_phase, execution_environment, lock_prerequisite, the Python parser and baseline loader. The tests parser differs only in its evidence schema name. Independent static review and actual closure binding remain required before execution.
