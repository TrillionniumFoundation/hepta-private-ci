# codex-utils-cargo-bin runfiles strategy

We disable the directory-based runfiles strategy and rely on the manifest
strategy across all platforms. This avoids Windows path length issues and keeps
behavior consistent in local and remote builds on all platforms. Bazel sets
`RUNFILES_MANIFEST_FILE`, and the `codex-utils-cargo-bin` helpers use the
`runfiles` crate to resolve runfiles via that manifest.

Function behavior:
- `cargo_bin`: first reads `CARGO_BIN_EXE_*` environment variables (set by Cargo
  or Bazel), then `NEXTEST_BIN_EXE_*` runtime variables when Cargo/Bazel metadata
  is absent. It resolves runfiles through the manifest. Outside runfiles it only
  accepts an existing absolute path; an invalid explicit value returns an error
  without falling back to another key or guessing a build-directory path.
  Nextest exposes binary paths only to integration tests and benchmarks from
  the same package. This lookup does not supply missing cross-package helpers.
- `find_resource!`: used by tests to locate fixtures. It chooses the Bazel
  runfiles resolution path when `RUNFILES_MANIFEST_FILE` is set, otherwise it
  falls back to a `CARGO_MANIFEST_DIR`-relative path for Cargo runs.

Background:
- https://bazel.build/docs/runfiles
- https://bazel.build/docs/runfiles#runfiles-manifest
- https://nexte.st/docs/configuration/env-vars/
