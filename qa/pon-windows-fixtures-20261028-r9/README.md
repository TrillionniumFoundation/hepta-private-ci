# Windows fixture repair and queue hook observations

This independent candidate starts at frozen local commit
`334de7a4d9a1b7a813c34eeaadf1ed7c65ad37c5`, tree
`b65ef390e23f038ef2f58affb020f8c393bd8662`. It does not modify the AWS proposal,
production manifest/locks, production security checks, workflows, owner rules,
branch protection or file-size policy. No local Hepta Rust, Cargo, Bazel,
formatter, build or native test ran. Native acceptance remains pending.

## Changes and their limits

### Five directory-handle fixture failures

The five original `cognitive_retrieval_learning` tests failed before exercising
their ledger assertions because `File::open(temp.path())` did not open a Windows
directory handle. The new test-only helper uses the repository's existing
`hepta-learning-ledger/src/production_tests.rs` pattern: read/write access and
`FILE_FLAG_BACKUP_SEMANTICS`. The caller retains its original `expect` messages,
real `LedgerWriter::from_durable`, synchronization, and all five assertions.
The non-Windows branch still calls the original `File::open(path)`.

This is a proposed fixture correction, not evidence of Windows native PASS.
Opening, writing and synchronizing the real directory must still pass hosted
tests. No production private-file validation is changed.

### Four queue hook observations

The four original cases are unchanged apart from a diagnostic guard. Their
assertions, timeouts, Python hook bodies and original literal command
`python3 <script path>` are retained. A new integration-test support module
installs an observation wrapper around that exact command. It does not replace
`python3`, repair the original path quoting or change production hook execution.

Each invocation gets its own directory containing:

- A start marker, command-resolution stdout/stderr and its exit status.
- Exact raw child `stdout.bin`, `stderr.bin`, and the returned exit code.
- When Python actually starts, a JSON record written by that interpreter with
  its PID, `sys.executable`, version, argv, script SHA-256, and executable SHA-256
  or the explicit read error. This is not an identity guessed from `where` output.

The wrapper replays the original stdout/stderr and returns the child's saved
status. Observer I/O errors remain visible; missing or malformed evidence is not
accepted as a completed observation. Windows `echo`/`type` must not be used to
reinterpret the saved child exit code through a stale `ERRORLEVEL` check.
Invocations killed before recording an exit remain
`running_or_interrupted_unknown`; no successful exit is synthesized.

The Rust guard neither consumes protocol events nor changes the test result.
On normal return or panic it prints a bounded JSON snapshot: at most 64
invocations, 4096 bytes per file, and 16384 raw bytes overall. Every truncation,
omission or read error is explicit. The original files are retained outside the
test's disposable Codex home. A hard process/job termination may prevent the
snapshot; it does not create a pass or a complete artifact.

Artifact directory precedence is `HEPTA_QUEUE_HOOK_DIAGNOSTICS_DIR`, then
`TEST_UNDECLARED_OUTPUTS_DIR`, then a unique OS temporary directory. These
variables select test evidence storage only. They do not alter production
permission or sandbox environment switches. Windows and Unix wrappers have
only been statically reviewed locally; output/exit preservation still requires
their real hosted runs.

## Original failures are preserved

Both jobs belong to original run `40633626405`, PR head
`682a88a7f847e31ffb6cd5e0a630dd71dde4bfee`, actual merge
`f9923f7809bf78de8e54885699b67f3816bf2be2`, base
`3e9efb15faa261a4dc3ffc3205cd259aaee41a3f`.

| Original job                    | Bazel targets | Executed | Pass | Fail | Skipped |
| ------------------------------- | ------------: | -------: | ---: | ---: | ------: |
| Windows shard 3, `122636270464` |           157 |      103 |  100 |    3 |      54 |
| Windows shard 1, `122636270341` |           147 |       98 |   96 |    2 |      49 |

Shard 3 contains **43 unique failed Rust test cases**: 29 mandatory prompt
registry platform refusals, 3 final-use store platform refusals, 5 directory
fixture failures, 2 Matrix path-classification failures and 4 queue hook failures.
Agentd's three printed batches total 150 pass / 37 fail / 1 ignored; the final
36/7 batch is not its whole denominator. Queue is 31/4 and Matrix is 38/2.

Shard 1 contains **6 unique failed cases and 8 original failed observations**.
The exec-server target reports 2 pass / 1 fail / 21 ignored. Core's original
summary is `FAILED in 6 out of 13`; those are shard/attempt results, not six new
independent cases. Repeated environment-tracing failures and other rerun
outcomes remain individually recorded in `windows-shard1-matrix.json`.
Reprinted log tails are excluded from execution counts. No core race is claimed
proved, and no retry or timeout increase is used to make these failures pass.

The shard 1 findings are an unqualified Windows filesystem-isolation request,
two missing guardian outcomes, a fork-history equality mismatch, a missing
expected nested tracing span, and an early wait-agent completion. Exact source
locations and every printed diagnostic observation are retained in its matrix.
They are outside this fixture patch.

## Byte-preserving evidence

`provenance.json` binds three ordinary lossless XZ archives, each below the
unchanged 512000-byte cap. No binary is split and no allowlist is expanded.

| Archive                                                 | Decoded bytes | Compressed bytes |
| ------------------------------------------------------- | ------------: | ---------------: |
| Original shard 1 log                                    |        884559 |            89224 |
| Original shard 3 log                                    |        608747 |            58160 |
| Fifteen exact-merge source files and original readbacks |       1038997 |           116344 |

The original log SHA-256 values are:

- Shard 1: `17e40a7e0108ae6479e5e8c62c56a4db893ab7575f1fa1303fea54aebf3a89e4`.
- Shard 3: `fb8799477f23566114297d926fd0337904cf1e20435d88665e2a71995fcf5d68`.

The earlier shard 3 603790-byte readback normalized CRLF to LF. That correction
and its SHA remain explicit, and the verifier reproduces it from the original
608747-byte bytes. The original CRLF data is not replaced with the normalized
version. The source capsule retains full text, exact-merge URLs, SHA-256, Git
blob identities and all original failed-test source assertions.

## Local verification

```sh
python3 -B qa/pon-windows-fixtures-20261028-r9/verify_evidence.py
python3 -B -m unittest discover \
  -s qa/pon-windows-fixtures-20261028-r9 -p 'test_verify_evidence.py' -v
python3 -B scripts/hepta_workspace.py
```

These are Python/source checks only. They verify decoded original bytes, all
43 plus 6 cases, fifteen source identities, protected production/workflow/policy
bytes, and exact restoration of the pre-change test files after removing the
declared fixture/observer edits. This proves no assertion or timeout was silently
changed. Python syntax and launcher ordering checks are not native execution.

## Minimal hosted execution and required retention

Use a new read-only job bound to the exact reviewed commit on Windows, preserving
the original toolchain and security setup. Do not run this work locally. Keep
the original qualification matrix and its complete denominators unchanged.

1. Run the real five directory-fixture tests through the repository entry point:
   `just test -p codex-hepta-agentd --locked cognitive_retrieval_learning::tests::`.
2. Set a unique `HEPTA_QUEUE_HOOK_DIAGNOSTICS_DIR` under `RUNNER_TEMP` and run
   `just test -p codex-queue-extension --test queue_service --locked`. This keeps
   all 35 original queue integration cases, including the four failures.
3. Run the original Bazel targets
   `//codex-rs/ext/queue:queue-queue_service-test` and
   `//codex-rs/hepta-agentd:hepta-agentd-unit-tests` using the original Windows
   wrapper/configuration. Pass the declared evidence directory through Bazel
   `--test_env=HEPTA_QUEUE_HOOK_DIAGNOSTICS_DIR=<absolute Windows path>`; without
   that explicit directory, retain the target's entire undeclared-output archive.
   This does not remove the remaining 32 agentd platform failures from the
   expected open denominator.
4. Upload the complete evidence directory, full nextest/Bazel stdout/stderr,
   discovery/selection, test XML/JSON, every attempt, exit code and elapsed time
   with an `always()` retention step. Hash every file after the runner has ended
   the test processes. Keep started-without-exit, missing identity and failed
   artifact reads explicit. Original execution-log upload alone does not promise
   retention of Bazel undeclared outputs; the dedicated job must upload them.
5. Run the same four observer cases on Unix to verify its wrapper too. Do not
   promote a static check or synthetic observer result into native acceptance.

Run-level timeout or lost artifact remains unknown/failure. Any successful
native result must bind its exact source and run identity; this package contains
no such result yet. All 49 original unique failures remain open until the
corresponding genuine retest and review close them.

`matrix-socket-review.md` describes the separately reviewable missing-path
change. It is not applied, and it explicitly preserves the independent peer
identity, private-state permissions and durability blockers.
