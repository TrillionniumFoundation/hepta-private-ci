# Continuation fixtures and real dependency-lock verification

This continuation starts from `fa0e8457ca5a3995e00ecec6534c1c68aa82fb28`.
That local chain includes the independently reviewed Git wrapper and closed-ledger
fixtures, plus the Exec index-loss fixture and native send oracle. It does not
replace qualification of any published source head or base.

## Optional Cargo binaries

The original Queue package command completed with 19 passing tests and 25 failures
before Queue behavior was reached. Its optional `codex` lookup panicked inside
assert_cmd 2.2.2 instead of returning the helper's declared `Result` error. The
complete command, failures, original retry policy, and resource observations are
in `queue-terminal-fence-native.json` and its full log.

The new regression launches a real relocated test executable in a Cargo
`debug/deps` layout. It verifies both a sibling binary and an absent optional
binary. The original implementation failed this assertion with the actual panic;
the fixed implementation passed all three package tests, including the two
existing Bazel undeclared-binary cases. Only the child environment is changed.
The helper preserves explicit environment resolution and Bazel's declared
runfiles boundary. It removes the panicking assert_cmd fallback and its dependency.

`cargo-fallback-original-negative` is the original failing run;
`cargo-fallback-native-pass` is the successful run. The negative run's new test
file was then untracked, so the generic runner's tracked-diff hash inventory did
not include that file. The final positive run included it. No missing prior
source hash is reconstructed or presented as an observation.

The narrow original `just fix -p codex-utils-cargo-bin --locked --allow-staged`
completed successfully. The final original `just fmt --base fa0e8457...` also
completed successfully. Tests were not rerun after fix/format.

## Real Cargo and Bazel commands

`exec-cargo-fallback-lock-resolve` records actual offline Cargo resolution of the
two changed workspace packages. Cargo.lock changes only the Exec dev edges
`codex-state` and `sqlx`, and the Cargo binary helper's dependency edges. No
external package version was changed.

The first cold `just bazel-lock-update` failed with a missing V8 requirements
path. Its entire raw log and nonzero exit remain in
`continuation-bazel-lock-update`. Bazel's contents cache subsequently held the
complete archive and patched module while its external path still contained an
empty temporary directory. The cached archive was verified against the module's
pinned SHA-256. The patch relocates `pip.parse`; it does not remove Python
dependencies. No repository input, lock bytes, or cache contents were manually
altered to resolve this boundary.

The same original command then succeeded, succeeded a second time, and the
original `just bazel-lock-check` succeeded. `continuation-lock-stability.json`
verifies both locks byte-for-byte across all three successful commands. The real
Bazel generator required no MODULE.bazel.lock delta for these internal workspace
edges; its unchanged hash is recorded rather than manufacturing a change.

## Admission and platform fixtures

The Queue manual second idle notification now waits for the actual completion
fence outside the callback, preserving the exact-one-dispatch and persisted
dedup assertions. The two existing gated Queue integration cases already ran
in the original Windows jobs; their results belong only to those original
heads. Queue was not rerun locally after fixing Cargo binary lookup.

Matrixd retains a platform-independent exact health response test. The actual
authenticated socket success case remains on Unix. Windows exercises the
production unsupported peer-identity result before any frame is read and asserts
that no control action ran. This does not implement Windows peer authentication.

The TUI preview fixture retains its original 10-second overall budget and fresh
attempt IDs. It retries only the two exact pre-admission errors, with the expected
error code and absent error data. Unknown errors are not resubmitted.

The App Server helper is used only by explicit successful sequential-turn
fixtures. It matches Response/Error IDs, leaving server Requests and notifications
buffered even if their independent ID namespace overlaps. The single deadline
covers sending, reading, and backoff. Only exact `-32603`, absent data, and the two
known pre-admission refusal messages permit another request. Disconnect, timeout,
malformed success, and every other error end the attempt without resubmission.
Ordinary request/read methods and negative admission tests remain unchanged.

Call sites with explicit suite budgets retain those budgets. The shared
`start_turn_and_wait_for_completion` helper previously relied on callers for its
admission bound; it now adds the existing common 10/25-second default bound.
This is a tighter bound, not a timeout increase. The 39 original failing case
names and their actual response diagnostics are preserved in
`app-server-admission-original-cases.json`. An independent source review found
the server/client ID collision and verified the corrected routing. Its receipt
predates formatting and is not a native-test result.

The current Queue, Matrixd, TUI, App Server, Exec, native oracle, and evaluated
shadow changes still require their original native/hosted qualification. Local
disk pressure prevented a new broad compile; the successful small helper tests
and dependency checks are not substitutes for those gates.
