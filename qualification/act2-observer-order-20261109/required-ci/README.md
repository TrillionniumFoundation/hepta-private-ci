# ACT-2 required-check failure audit

This read-only audit concerns source head
`111d5773145dbe4add99a28b2d1111916a3dbd3b`, PR #5591, and blocking run
`42744408777`. It does not convert a scoped ACT-2 pass into repository-wide
acceptance. No GitHub mutation, rerun, cancellation or deployment was performed.

## Actual checkout identity

The four original decoded logs below all record the actual checkout as
`e48870d3242d0041eae7865c8a1a07cb17619d7c`, the PR merge of source `111d5773`
into base `4674a34528d0097949cc7d604f60de94585d0ba0`. The check-run's source head
is not used as a substitute for this logged checkout identity.

| Job | Actual observed failure |
| --- | --- |
| [`129601583793`](job-129601583793-decoded-log.zip), Rust format | One formatter diff in `notes_document_observer.rs:52`: the long error string's `.into()` must wrap onto the next line. This is directly in the ACT-2 delta. |
| [`129595862908`](job-129595862908-decoded-log.zip), macOS native paths | Dependency resolution failed while fetching sparse index `3/c/csv`, with curl error 16 in HTTP2 framing. `cargo test --no-run --package codex-hepta-paths --locked` exited 101 before tests. |
| [`129595863564`](job-129595863564-decoded-log.zip), Intel macOS Bazel | 12 Automation fixture failures and 7 Agentd Circuit fixture failures report `Invalid`; additional failures occur in matrix SDK migration, code-mode endpoints and app-server. |
| [`129595863651`](job-129595863651-decoded-log.zip), ARM macOS Bazel | The same 12 Automation and 7 Agentd Circuit fixture failures report `Invalid`; additional failures occur in matrix SDK migration and app-server. |

The exact formatter correction is formatting only. The native paths transport
failure does not establish a Rust or test assertion failure. Conversely, actual
Bazel assertion/fixture failures must not all be classified as infrastructure.

## Fixture path contract and published repair

The 12 Automation failures occur at the initial `AutomationStore::open_root` in
five existing fixture files. `open_root` first calls `create_private_directory`;
that function requires `path.canonicalize() == path` and otherwise returns
`AutomationError::Invalid`. These fixtures pass a path derived directly from
`tempfile::tempdir().path()` without canonicalizing the existing parent.

The six driver tests and one signed-credit test in Agentd likewise derive a
`HeptaFleetRoot` from the uncanonicalized owned TempDir, then open AutomationStore.
Their shared `checked` helper reports only `fixture failed: Invalid` and the logs
do not contain backtraces or the fixture's actual input/canonical path pair.

macOS `/var` versus `/private/var` aliases are consistent with the observed
strict path rejection. Windows has a related canonical-path-prefix concern
confirmed as a candidate by its own fixture failures. The available logs do not
uniquely prove the actual path discrepancy for each failed invocation.

[PR #5618](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5618)
now publishes a test-only path-contract repair on exact source
`8bebf0a3c207a49bfd0a99367fd6e06f52a6cb98`: seven existing fixture files and eight
owned temporary roots. It canonicalizes the existing TempDir parent before
adding `automation` or `fleet`, preserving the TempDir lifetime, assertions,
clocks, budgets and runtime path refusal. Native acceptance of that candidate is
**PENDING**; no pass count is supplied here. The original failed paths were not
printed, so this contract repair does not uniquely diagnose every historical
`Invalid`. Windows signed-credit's `Durable(Io(PermissionDenied))` is a separate
failure and is not declared repaired by canonicalization.

| Candidate fixture file | Covered historical failure locations |
| --- | --- |
| `hepta-automation/src/circuit_drain_tests.rs` | Two initial owner opens |
| `hepta-automation/src/circuit_recovery_budget_tests.rs` | Shared pending-run owner for five failures |
| `hepta-automation/src/circuit_expired_recovery_tests.rs` | Original recovery-owner store open |
| `hepta-automation/src/circuit_learning_outbox_tests.rs` | Three initial owner opens |
| `hepta-automation/src/circuit_task_readback_tests.rs` | Original owner open |
| `hepta-agentd/src/circuit_task_driver_tests.rs` | Six driver fixture opens |
| `hepta-agentd/src/circuit_credit_signed_tests.rs` | One signed-credit fixture open |

The first two columns describe failure locations, not passing results. A fixed
fixture path is not a waiver of the strict product root rule.

## Other observed failures remain separate

Both macOS Bazel logs show the ACT action-skill runtime-view regression passing.
Neither log contains the two new `notes_document_observer_clones_*` test names;
these logs are not used to qualify those new tests. Their actual qualification
must come from the separate pinned ACT-2 workflow's own command records.

Both macOS logs contain matrix SDK
`encrypted_state_identity_session_and_queues_survive_restart` failing with
`Error: Initialization`. Intel macOS also contains code-mode grpc-tcp and
websocket failures with endpoint-wait timeouts. App-server failures remain their
own targets; this audit does not assign them to the Notes delta.

The [Windows classification](windows/README.md) and [machine record](windows/RESULT.json)
retain its separate failures. These original
errors are not erased by a later successful selected run or a formatter repair.

## Retained records and limitations

The nine per-job ZIP files below hold complete decoded log payloads returned
by the GitHub log tool. Their member bytes preserve the original line endings,
leading BOM and final newline. No standalone large raw log or combined duplicate
archive is copied into this package. [ALL_ARCHIVES.json](ALL_ARCHIVES.json)
records every archive and member length/SHA-256; [RESULT.json](RESULT.json)
locates each Mac/format log as `archive` plus `log_member` and retains checkout
identities and failure excerpts. These generated ZIPs preserve decoded payloads;
they are not the original GitHub server-side compressed response bytes.


| Job | Complete log archive | Log member |
| --- | --- | --- |
| `129592960207` | [job-129592960207.zip](job-129592960207.zip) | `job-129592960207.log` |
| `129595862908` | [job-129595862908-decoded-log.zip](job-129595862908-decoded-log.zip) | `job-129595862908.log` |
| `129595863489` | [job-129595863489.zip](job-129595863489.zip) | `job-129595863489.log` |
| `129595863564` | [job-129595863564-decoded-log.zip](job-129595863564-decoded-log.zip) | `job-129595863564.log` |
| `129595863610` | [job-129595863610.zip](job-129595863610.zip) | `job-129595863610.log` |
| `129595863635` | [job-129595863635.zip](job-129595863635.zip) | `job-129595863635.log` |
| `129595863651` | [job-129595863651-decoded-log.zip](job-129595863651-decoded-log.zip) | `job-129595863651.log` |
| `129595863784` | [job-129595863784.zip](job-129595863784.zip) | `job-129595863784.log` |
| `129601583793` | [job-129601583793-decoded-log.zip](job-129601583793-decoded-log.zip) | `job-129601583793.log` |

The GitHub fetch connector rejected each requested check-run annotations URL
with `400 INVALID_ARGUMENT` before retrieving annotation content. This is an
endpoint-access limit, not evidence that the runs had no annotations.

Full required CI and ACT-2 promotion remain HOLD.
