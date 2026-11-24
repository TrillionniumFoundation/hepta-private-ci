# Windows dependency consolidation: transient Rust archives

The Windows clippy job for parent commit
`07c8994f2402a58f6b59eb648c801fc40c6e2b96` failed while the Rust process wrapper
copied a temporary archive from a concurrently compiling target:

- Job: <https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45104012523/job/137461937915>
- Target: `//codex-rs/thread-store:thread-store-unit-tests-bin`.
- Missing source: `app-server-protocol-unit-tests-bin.lib.temp-archive-a28219a.a`.
- Error: `unable to copy ... into unified dependency dir ... (os error 2)`.

The existing patch excluded temporary executables and code-generation objects,
but missed Rust's temporary archive naming pattern. The change excludes only
the additional `.temp-archive-*.a` pattern, including case variants. Stable
`.rlib`, `.rmeta`, `.lib`, and `.a` inputs keep their existing behavior. The
wrapper still reports ordinary input I/O errors.

## Local verification

The regression test runs the real upstream consolidation function against
directories containing final libraries and the transient names observed in CI.
It compares every retained filename and file byte, checks first-search-path
precedence, checks the returned compiler arguments, and verifies failure for a
missing explicit response file. The parent implementation admits the temporary
archives and fails this test. The candidate passes it and the 13 existing wrapper
tests: 14 passed, zero failed. The parent control has 13 passed and one failed.
Applying the existing response-file patch as well gives 19 passed and zero
failed; its corresponding parent control has 18 passed and one failed. All five
repository patches apply in their declared order to the pinned upstream tree
(the existing zero-context target-flags patch needs `git apply --unidiff-zero`).

This local verification ran on Linux with Rust 1.95.0. The replay tool enables
the Windows-only, standard-library filesystem code in a **test copy**. It does
not change the production platform conditions and is not a native Windows run.
Native Windows CI remains necessary. The test checks which files are admitted;
it does not try to reproduce the scheduler timing of the original disappearing
file race.

Reproduce with the pinned upstream sources and dependency:

```sh
git clone https://github.com/hermeticbuild/rules_rust.git /tmp/rules-rust-replay
git -C /tmp/rules-rust-replay checkout f19661ba71f77c993ce1eb082053692610fe4313
git -C /tmp/rules-rust-replay apply "$PWD/patches/rules_rust_windows_process_wrapper_skip_temp_outputs.patch"
python3 qualification/ci-transient-archive-20261124/replay.py \
  --rules-rust /tmp/rules-rust-replay \
  --rustc /absolute/path/to/rustc \
  --patch patches/rules_rust_windows_process_wrapper_skip_temp_outputs.patch \
  --output /tmp/process-wrapper-replay
```

The tool downloads `tinyjson` 2.5.1 from the source already pinned by upstream,
checks its SHA-256, compiles directly with `rustc`, preserves complete stdout and
stderr for every command, and writes a receipt. No Cargo dependency or security
policy changes are needed for this patch. This build correction does not resolve
the independent cargo-deny advisories, Linux test failures, or cancelled macOS
jobs, and does not claim any improvement to model weights or trading outcomes.
