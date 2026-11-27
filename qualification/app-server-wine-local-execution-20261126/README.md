# Place the app-server Wine test launcher on the existing host runner

Base: `eb294db1b084746d3f24ae4a07c7a0d3b1bf8e19`.

The original musl job `140218309355` retained three complete failed attempts
for `command_exec_enforces_managed_deny_read_requirements`. Its managed-path
request and its subsequent allowed-path request both returned bubblewrap's
user-namespace refusal. The allowed-path assertion expected the complete
successful response containing `user secret`; the refusal occurs before that
intended sandbox behavior can be exercised. The first denial therefore cannot
be counted as proof that the managed restriction worked.

The test has an intentional host-local contract: it is Unix-only and uses
`without_auto_env()`. Although the Wine runner supplies a Windows exec-server
URL for other tests, this fixture constructs no automatic environment. The
recorded initialized server reports Linux and the two command results identify
the Linux bubblewrap failure. Redirecting this fixture to Wine would change the
behavior under test.

The original compact execution records identify all three shard-seven test
actions as remote, not cached, and unsuccessful. Their separate XML actions
exit successfully and do not count as test passes. The existing local placement
setting covers the native app-server launcher but intentionally does not flow
to its Wine launcher.

This change adds a separate optional map of tags for Wine launchers. Its only
configured entry adds `no-remote-exec` to
`//codex-rs/app-server:app-server-all-wine-exec-test`. The outer launcher has no
Rust sources. Native Rust compilation, the Windows exec-server transition,
dependencies, other Wine targets, native launchers and Windows cross launchers
keep their original attributes. The new optional macro parameter is appended
so existing positional arguments retain their positions.

The current host CI already configures user namespaces before Bazel tests.
The test's deny-read rules, host-local selection, assertions and existing
`no-sandbox` tag stay intact. Its sixteen shards, long test timeout and existing
flaky-attempt policy remain unchanged. Remote cache eligibility also stays
unchanged; a later cache hit is not evidence of a fresh local execution.

Local review binds the complete original logs, their compact execution records,
the two changed source files and the unchanged execution and compilation
contracts. No new Rust or native test execution is claimed. Normal CI must
establish the actual execution placement and test result for this source cut.
