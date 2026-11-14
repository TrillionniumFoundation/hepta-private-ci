# Common-candidate native driver — prepared, not executed

The driver is derived from the exact c763 native workflow and the observed ai395 round-two driver. Reference identities and the seven Root test names are retained in reference.json. This deliverable has only static syntax and source-contract checks. No driver invocation, Cargo build, nextest listing, native test, sudo or mount operation was run while preparing it.

## Inputs and use

Required arguments are --repo, --output, --source-sha and --target. The checkout must be clean and its HEAD must equal the complete 40-character SHA. Output and target must be new, disjoint directories outside the checkout. The driver takes a cooperative lock in that checkout's Git directory. Use an exclusive checkout: other test launchers do not participate in this lock.

```bash
python3 /workspace/scratch/c2fccbdb195e/p0-native-driver-20261111/run_native_candidate.py \
  --repo /workspace/scratch/c2fccbdb195e/common-candidate \
  --output /workspace/scratch/c2fccbdb195e/native-evidence-new-attempt \
  --source-sha "<reviewed-full-40-character-head>" \
  --target /workspace/scratch/c2fccbdb195e/native-target-new-attempt \
  --cargo-build-jobs 2
```

This is an invocation template, not a command already executed. Supply a reviewed head and unused paths. The driver does not check out a ref, install packages, change lockfiles or configure system permissions. It uses the repository's verified V8 resolver; missing or inaccessible required artifacts fail their recorded stage. Cargo is offline. Rust, Cargo, just, nextest and native build prerequisites must already be available.

The six reviewed recorder/helper/nextest source blobs are checked before execution. A candidate that changes one of those contracts is rejected for review instead of silently using unreviewed semantics.

## Exact test selection

The ordinary command is:

```text
just test --locked --offline -p codex-hepta-agentd -p codex-hepta-learning-artifacts -p codex-hepta-intelligence-eval --lib --test-threads 2 --retries 0 --success-output final --failure-output final
```

There is no ordinary test expression. The historical round-two driver's fourth package and selective expression are not used.

The helper is built first with the candidate's own scripts/hepta_cell_test_helpers.py, selecting codex-hepta-infer-worker-host. Its hepta-joint-propose compiler executable must be under the new Cargo target. Only this attempt's read-only helper copy and exact env.json are admitted. The same-source verifier runs before and after the tests. Inherited CARGO_BIN_EXE_* and NEXTEST_* variables and compiler wrapper variables are removed; the actual selected environment and tool versions are retained.

Root execution uses only the seven exact names in ROOT_PARENTS/reference.json, --run-ignored only, a union of exact test(=name) selectors, one test thread and zero retries. sudo is outside the execution recorder, so its observed command remains the real just test invocation. The root launcher asserts euid 0. The fixture is a new private root-owned directory under /run, with source/bind/checkpoints and the same bind mount and environment contract as the c763 workflow.

If sudo, mount, mountpoint or umount is missing, or sudo -n preflight does not succeed, ordinary qualification can continue but Root is recorded as NOT_RUN. No permission, namespace or sysctl configuration is changed. Root absence cannot produce full-driver success. A failed actual Root setup/test is retained as failed or incomplete, never converted into an unprivileged replacement.

## Evidence and failure behavior

Every helper and test command runs through hepta_ci_exec with SOURCE_SHA=TESTED_SHA and HEPTA_CI_LANE=source-head. The driver additionally retains the full launch argv, timestamps, launcher exit code and wall time, including failures. There are no command retries.

JUnit is read from the c763 nextest local-profile path, <repo>/codex-rs/target/nextest/local/junit.xml. Any prior report is moved aside before each test command. hepta_ci_junit.collect verifies source binding, report freshness, terminal counts and test outcomes. Root additionally requires exactly the seven distinct, non-skipped parent names. No JUnit file is manufactured for NOT_RUN.

Complete source inventories contain the commit, tree, status and per-file mode, length, SHA-256 and Git blob identity. They cover tracked and unignored files and hash ordinary files incrementally. The driver records checkout, before-tests, after-tests and final inventories, with extra maintenance inventories when requested. Failure still enters final retention and preserves the original logs; output directories are never resumed or overwritten.

A complete pass requires ordinary tests, exact Root7, both helper verifications, unchanged tested source and successful retention/cleanup. Otherwise the process returns nonzero, and qualification-status.json separates ordinary outcome, Root outcome and incomplete work. Passing fixtures are not independent real tasks. Production adoption, ordinary A/B/C route execution and a real daemon Root cold restart are explicitly false; CPU and complete research cost remain unknown.

## Optional maintenance

To append the workflow's maintenance and binary compile checks, explicitly add:

```text
--maintenance --format-base-sha <reviewed-ancestor-commit>
```

This phase runs only after both ordinary and Root qualification pass. It executes scoped just fix, just fmt, then cargo check --bins for the three packages. No behavior tests run after fix/fmt. Changed Rust postimages and the complete Git patch are retained with bounds matching the original workflow. Changes outside the three Rust owners are rejected. The status distinguishes passing tests on the original source from any maintained source; a changed final tree is not represented as having been tested.

## Known local tooling observation

A read-only discovery found usable Rust/Cargo 1.96.0 and nextest 0.9.103 under /workspace/scratch/f7c0ded86bcc/toolchain/installed/bin. Dependency caches exist at /home/agent/.cargo/registry and /home/agent/.cargo/git. These dependency caches may be used; old target test binaries are not used by this driver.

just was found in the uv cache on the 1.59.0 version line, while the reference workflow pins 1.51.0. That difference must be recorded rather than represented as identical CI tooling. Current ordinary UID/EUID was 1000. sudo and clang were absent from the current PATH; Root prerequisites are not established.

Git-attribution and RMCP are not included in this driver. Their future validation should use separate fresh targets. The prepared RMCP selection contract is available from /workspace/scratch/c2fccbdb195e/rmcp-narrow-fix-c763/manifest.json and requires its six exact cases, not a zero-selection pass.
