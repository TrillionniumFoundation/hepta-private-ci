# Windows Clippy configured target selection

The original Windows Clippy job requested 1,491 targets. It built 1,322 and
failed because 169 explicitly requested helpers were incompatible with native
MSVC. The preserved source and checkout commits have the same tree. Of the
169 helpers, 166 are GNU cross binaries and three are Unix owner fixtures.

Native Windows now queries the same manual Rust test set under its existing
MSVC target, host platform and Clippy configuration. Bazel's declared
`IncompatiblePlatformProvider` determines compatibility. Every compatible manual
helper remains explicit; the existing workspace patterns and V8 exclusion stay
the same. Linux, macOS and the explicit Windows cross branch retain their
existing selection. The shared query wrapper defaults to ordinary `query`.

Query failure propagates before any build target is printed. Each native
Windows record loses only its trailing CR, and incompatible empty records are
removed. An empty compatible manual helper set fails before printing workspace
patterns. No lint severity, target declaration, workflow gate or timeout changes.

## Evidence and limits

- The complete original Windows failure is losslessly stored in
  `windows-clippy-127966826186.log.gz`.
- `local-validation.tar.gz` contains an internal per-file SHA-256 index, exact
  repository context, candidate sources, original failure and success logs from
  local checks, the four-platform Bazel fixture and all five query outputs.
- The six new regression methods run through both actual shell scripts. Their
  fake launcher supplies controlled query output; the independent real Bazel 9
  fixture checks the provider semantics, including transitive incompatibility.
- The original sources fail two methods in both LF and CRLF forms. The final
  candidate passes all 52 wrapper methods with no skips. The earlier partial
  mirror's two missing-script failures remain in the archive.
- Bazel's small fixture uses a declared rule without compilation actions.
  A successful full native Windows Clippy job on the integrated head is still
  required. These local results do not establish that result.

The archive contains regular files only; its SHA-256 and the original log's
SHA-256 are recorded in `VALIDATION.json`. Inspection can read members directly
with Python `tarfile` without extracting them. For fixture replay, use the
official Bazel 9 binary with the recorded hash, place the supplied verified
platforms archive contents in `bazel-fixture/platforms`, and use the exact
arguments recorded under `bazel-results/RESULT.json` after adjusting local paths.
The original runner and fixture-specific ignore file are retained as evidence;
they do not add build targets or ignore rules to the product workspace.
