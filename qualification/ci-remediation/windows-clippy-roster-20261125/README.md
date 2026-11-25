# Windows native Clippy target selection

The real Windows Clippy job `139214394339` at source
`4be2e45d4c90fe539abf61814fa9b362d8922881` reported 1,429 explicit targets,
1,272 successful builds, and 157 incompatible targets. It ended with
`command succeeded, but not all targets were analyzed`; this was a failed gate.
The complete original log is 804,633 bytes, SHA-256
`6feb50f4fcaa7cfd12a9f8076f04f15dd93382108136e3cfff897caf4a46c054`.

156 targets were the GNULLVM-only `*-windows-cross-bin` helpers. Native Windows
had neither of the selector's previous filters and explicitly requested them
under MSVC. The three corresponding generator branches in `defs.bzl` give the
native and cross helpers the same crate root, sources, features, dependencies,
data, compile data, Rust flags, and environment; only their platform execution
shape differs. Native test helpers remain explicitly selected. The remaining
incompatible target was the Agentd cognitive product process suite: its source
is `cfg(unix)` and its existing BUILD contract permits only Linux and macOS.
The selector now follows that exact existing platform contract.

The query, wildcard package scope, V8 exclusion, native test sources, Clippy
configuration, compatibility constraints, and error propagation are unchanged.
No `skip_incompatible` override or accepted partial analysis was introduced.
The real shell regressions compare the complete output roster for Linux,
macOS, Windows native, and Windows cross modes. A separate partial-output query
failure must still return exit 37 with no targets on stdout.

Local script regression and format results are recorded with this candidate.
These tests exercise the actual selector and query wrapper with a recording
Bazel process; they do not constitute a new Bazel analysis or Windows Clippy
qualification. The next normal Windows job must analyze its full selected
roster successfully.
