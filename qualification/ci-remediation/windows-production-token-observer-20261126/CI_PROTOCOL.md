# Proposed normal CI boundary

This layer does not alter the four reviewed observer files from patch
`5a1230f89a0d0194c11b857d018db1dd8f3307bbaffb3430bf4d90aa340856cf`.
It prepares a new, exact-source normal-push lane; it has not been published or
executed. The base is `be271ddfa2a2d519a44112e4f176d2d8c3499c25`.

The proposed unique branch is
`research/windows-production-delete-observer-20261126-87d09924`.
The existing `9d64` matrix branch and `04235` fail-closed source stay untouched.
Their factory guards must not be removed to make a production-token observation
reachable. The observer instead retains the already-existing production factory
and its two original owned-fixture failure cases on the stated production base.

The workflow has only a branch/path-limited push trigger, no manual dispatch,
no pull-request duplicate lane, read-only contents permission, and no persisted
checkout credentials. Concurrency does not cancel an in-progress run. Before any
publication, every existing push trigger must be checked against this branch and
the complete changed-path set. Uncertain extra triggers prevent publication.

The single Windows job keeps the existing independent-lane 20-minute total
budget, Rust 1.96.0/MSVC, just 1.51.0, nextest 0.9.103, two build jobs and zero
test retries. No cold-build timing claim is made. A build timeout remains an
incomplete result; it is not grounds to increase the budget or rerun blindly.

The controller records the exact push head, raw commit/tree/parents, tool outputs,
selected runner metadata, manifest metadata and source/config/lock hashes before
and after execution. The four reviewed observer blobs are fixed constants. The
entire checkout must remain clean. Rust ABI compilation and native execution
remain pending until an actual authorized run returns them.

The selected library binary is hashed after enumeration and read again from the
same path in the controller's finalization after the native command, including
command or observation-parser failure paths. Bytes and SHA must match. A changed
or unreadable binary leaves an explicit provenance error and marks the observation
incomplete; it cannot replace an earlier Clippy or native nonzero exit status.

It invokes strict production-crate Clippy once. It then enumerates the real
production library with the existing workspace manifest metadata, using the
pinned nextest JSON format. That metadata retains all workspace package names,
so the repository's package-specific overrides are not misapplied to a synthetic
one-member workspace. Cargo still builds the actual requested targets/features.

The exact selected identities are:

- `token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces`
- `unified_exec::tests::legacy_workspace_write_delete_is_limited_to_writable_roots`

Enumeration must find both, with no selected ignored case. Every excluded case
is counted by nextest's actual exclusion reason. The native command uses the
original `just test` route, local profile, one test thread and `--retries 0`.
The original 30-second-times-two nextest watchdog, 5-second child limit and
10-second output/exit wait remain unchanged. No test assertion is changed into
an Unsupported expectation, ignore, skip or expected failure.

Raw stdout and stderr are separate complete files for each tool/command. The
controller retains the first actual nonzero command status and all later status
records; an observation parser cannot turn the original failures green. A failed
build/list records native bodies as not started. A native command that has run
keeps its actual exit even if observation parsing is incomplete. Source drift,
wrong selected cases, missing/repeated attempts or missing observations also
prevent a successful controller result. Artifacts are uploaded on failure.

The native result report distinguishes two test attempts from twelve descriptor
checks. It requires the six fixed queries in each phase, actual token provenance
and the fresh post-impersonation parent SD comparison. AccessCheck denial is an
observed result, not a parser failure; an AccessCheck API error remains unknown.
There is no expected allowed/denied pattern added to the original assertions.

The source field `same_semantic_token_as_before` compares the complete captured
raw fact subset. In particular, raw privilege attributes include any
`SE_PRIVILEGE_USED_FOR_ACCESS` usage bit. A mismatch is conservative observation
uncertainty, not proof of an authorization change. The controller does not mask
usage bits to make equality succeed. This limitation applies to the source
observer regardless of whether a future run matches or differs.

A complete observation is explicitly not production confinement qualification.
The original outside-delete failures, native Win32 matrix failures, successful
controlled native-handle disposition, and fail-closed availability behavior keep
separate verdicts. This proposed workflow does not merge or deploy any of them.
