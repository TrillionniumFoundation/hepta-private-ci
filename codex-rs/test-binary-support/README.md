# Test helper entry points

Linux musl initializes Rust command-line arguments after native constructors.
Tests that launch sandbox, filesystem, exec-server, or delayed-output helper
modes therefore use the codex-test-helper binary, whose normal main dispatches
the same helper implementations. Other targets retain their existing test
executable dispatch.

Bazel exposes the helper as an explicit test binary or as transitive library
data for core_test_support. An explicitly configured invalid binary path is
an error. The runfiles lookup names the declared helper target and never
searches build directories.

For Cargo musl tests, build codex-test-helper from the
codex-test-binary-support package for the same target, then provide its absolute
path through CARGO_BIN_EXE_codex-test-helper (or nextest's equivalent binary
metadata). Missing helper metadata remains an error.
