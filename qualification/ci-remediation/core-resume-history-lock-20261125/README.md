# Core resume test-support dependency lock qualification

The explicit-environment resume fixture directly uses `codex-history`. Its
existing transitive presence does not replace the required direct dependency.
The workspace Cargo resolver generated the lock with the ordinary offline
metadata command. All 1,532 package identities and every external package
record, including versions and checksums, remained identical. The only Cargo
lock change adds `codex-history` to `core_test_support` dependencies.

The normal `just bazel-lock-update` and `just bazel-lock-check` recipes both
completed successfully. The generated `MODULE.bazel.lock` remained byte-for-byte
unchanged. The companion receipt records the commands, results and hashes.
This verifies dependency metadata and lock consistency; it is not a Rust build,
Bazel target analysis or native test pass. The changed fixtures still require
their scoped execution on this new source.
