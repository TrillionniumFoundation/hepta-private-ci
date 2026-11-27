# Exec Server native filesystem test placement

The observed GNU failure ran the filesystem integration test on a remote
executor. Its complete test log contains 49 failed cases, all reporting that
`bwrap` could not create an unprivileged user namespace. The compact execution
record identifies the actual test action as remote, not a cache hit, with exit
101. Its separate XML generation action exited zero and is not a passing test.
The musl record has the same action digest and remote start as GNU, and its
failed log is byte-identical. Those records are not two independent executions.

This change applies `no-remote-exec` only to the native
`exec-server-file_system_unix-test` launcher. It reuses the existing
`workspace_root_test` launcher and its runfiles environment handling. The Rust
test binary is a separate manual helper, whose compilation remains eligible for
remote execution. A tag on the previous direct `rust_test` would also propagate
to its Starlark compilation actions under Bazel's tag propagation contract.

The launcher-tag option now also supports tests without sharding. The existing
Core and App Server callers only change the option name; their generated rule
attributes remain unchanged. The new Exec Server launcher receives no shard
count or `flaky` attribute. Its original single-thread argument, test cases,
assertions, permissions, timeouts, and retry settings are retained. Unit tests,
other integration tests, Wine launchers, and Windows cross wrappers keep their
existing attributes. No host policy or namespace setup is added.

The selected target now uses the launcher's existing Cargo-like working
directory and resolves the same three executable environment bindings to
absolute runfile paths. This is an explicit launcher change; it is not a claim
that the old process environment or executable artifact path is byte-identical.

The tag applies to this native target on every platform. Linux CI already
prepares user namespaces on its existing hosted runner. macOS and Windows keep
their existing local execution strategies. Remote test caching remains enabled;
a cache hit must not be reported as a new local test execution.

Actual loading-only queries compared all Exec Server rules plus thirteen Core
and App Server controls. The baseline has 80 rules and the candidate has 81:
79 existing rules have identical attributes, one public test becomes a launcher,
and one manual Rust helper is added. Its compilation attributes equal those of
the former direct test. The queries did not analyze or execute Rust actions.

Source and rule-shape checks do not qualify this candidate's behavior. The
original remote failure remains failed. A subsequent normal CI run must show
the actual test action's placement and result before this change is qualified.
