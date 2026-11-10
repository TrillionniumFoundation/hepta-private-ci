# ACT-2 Windows required-CI failure classification

This is a read-only review of existing decoded job logs. No job was rerun,
cancelled or modified; no code or GitHub metadata was changed.

Source head is `111d5773145dbe4add99a28b2d1111916a3dbd3b` (#5591).
The four blocking Bazel shards checked out the PR merge
`e48870d3242d0041eae7865c8a1a07cb17619d7c`, which merges that head into
`4674a34528d0097949cc7d604f60de94585d0ba0`. Their results must not be
relabeled as direct source-head tests. The separate private-state qualification
checked out exact source `111d5773...`.

## Confirmed issue from this delta

Private-state job `129592960207` (run `42744408754`) completed five native
commands with 15, 2, 3, 2 and 11 tests passed respectively. They cover
private-state Windows paths, durable prompt registry, FinalUse, authority lease
and prompt runtime. Skipped cases are separate in the original summaries.

The job then failed only its final `cargo fmt --check` step. Lines 2802-2811
show a diff in `notes_document_observer.rs:52`: the long error string's `.into()`
must be moved onto the next line. The same difference occurs in Linux Rust
format job `129601583793` reviewed by the parent agent. No native failure is
inferred for the earlier successful commands, and the overall job remains failed.

## Other observed failures

| Blocking shard / job | Observed failure | Boundary |
| --- | --- | --- |
| 1/4 `129595863635` | Twelve Circuit automation tests fail at original store opening with `Invalid`; `remote_windows_sandbox_process_accepts_process_write` is rejected by the current Windows isolation guard. | The Circuit opening failures match the Mac symptoms; exact path values are not printed, so root cause is not uniquely established. |
| 2/4 `129595863489` | Windows sandbox desktop/token/legacy execution tests fail; some subsequent process tests encounter a poisoned test lock. CLI managed-profile enforcement and two app-server tests also fail. | Exact guard refusal, assertion differences and MCP 404/transport events are recorded. They are not all relabeled as an environmental failure. |
| 3/4 `129595863610` | Perception fixture byte equality fails; six Circuit driver fixtures return `Invalid`; one signed Circuit fixture returns `Durable(Io(PermissionDenied))`; evaluation file fixtures report Windows error 33; generation/control/episode fixtures fail; TUI SQLite path equality differs by the extended Windows path prefix. | The signed Circuit failure is not the same `Invalid` observed on Mac. A uniform path-only explanation would be incomplete. |
| 4/4 `129595863784` | Seventeen exec-server filesystem tests fail, chiefly at the existing isolation guard; core workspace-root tests report OS error 2, and subagent-notification and hard-link policy tests also fail. | Existing guard refusal is a real product result, not permission to remove or weaken that guard. |

The Notes-only code delta does not by itself explain these other failures.
No controlled base/head regression experiment was performed here, so the review
does not claim that every failure was proven pre-existing. `RESULT.json` records
the exact deduplicated failed test names for each job; duplicate log tails and
Bazel retries are not counted as additional independent tests.

## Preserved evidence

Five complete decoded logs are preserved byte-for-byte as members of the
[per-job archives](ARCHIVES.json), including original CRLF line endings and the
initial UTF-8 BOM. [SHA256SUMS.json](SHA256SUMS.json) records each relative
archive path, member name, byte count, SHA-256 and CRLF count. [RESULT.json](RESULT.json)
locates the same members alongside exact failure classifications. These are
returned decoded payloads in newly generated ZIPs, not original GitHub
server-side compressed archives. Read the complete member with the result
record before interpreting an excerpt.

Full required CI and complete ACT-2 promotion remain HOLD.

The subsequent [fixture repair PR #5618](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5618)
uses source `8bebf0a3c207a49bfd0a99367fd6e06f52a6cb98`; native validation remains
PENDING. It repairs the test-owned path contract and does not uniquely establish
the unprinted original failed path values. In particular, signed-credit's
`Durable(Io(PermissionDenied))` remains a separate failure, not a path-repair pass.
