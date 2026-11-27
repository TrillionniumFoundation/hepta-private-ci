# Windows Rust dependency-directory executable filtering

Windows Clippy job [140378293622](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45960650092/job/140378293622)
failed while the real rules_rust process wrapper copied
`hepta-supervisor-paired_process_product-test.exe` into its private dependency
directory. The full decoded original log is retained alongside this record.

The existing temporary-output patch now also excludes case-insensitive
`.exe` suffixes. Executables beside dependency libraries are build products.
The wrapper continues to copy rlibs, metadata, DLLs and import libraries,
including names ending in `.exe.lib` and `.exe.dll`. It still reports errors
from required libraries and preserves child exit status and directory cleanup.

## Evidence

- Candidate base: `57c0f3c0c7b64c7c0015ebf1c6c127a4f52da643`.
- Patched upstream: `hermeticbuild/rules_rust@f19661ba71f77c993ce1eb082053692610fe4313`.
- Original upstream main.rs blob: `3139b45a857fe8d2baae8d7c05495360bf9b8ae7`.
- All five declared rules_rust patches apply in order. The unchanged final
  patch has zero-context hunks and was validated with `git apply --unidiff-zero`.
- The complete actual process-wrapper sources were compiled on macOS with
  `--cfg windows -Aexplicit_builtin_cfgs_in_flags`, Rust 1.96.1 and the exact
  upstream tinyjson 2.5.1 archive, whose SHA-256 is
  `9ab95735ea2c8fd51154d01e39cf13912a78071c2d89abc49a7ef102a7dd725a`.
- All 18 original/response-file unit tests passed. Four actual-process smoke
  tests passed: unchanged ordinary arguments, first dependency-directory
  precedence, child exit 37 with cleanup, and executable filtering while
  preserving import/shared libraries.
- The original temporary-only patch was built as a negative control. The
  executable-filter regression failed with the expected extra `program.EXE`.
  Its original failure output is retained.
- Linux fixture execution verified response-file paths with spaces, exact
  library bytes, child exit 37, Python syntax, and explicit non-Windows CLI
  refusal. Parsed workflow comparison confirmed that only one Windows shard 1
  smoke step was added. Repository formatting and `git diff --check` passed.
- The first macOS Python probe used Xcode Python 3.9, which could not import
  the existing BuildBuddy helper's Python 3.10 annotations. That original
  import failure is retained. The existing Python 3.14 completed the probes
  against the same already-built wrapper.

These macOS checks execute the Windows-selected source branch on macOS.
They are not native Windows or Wine evidence. The six-test native Windows
smoke additionally requires real exclusive Win32 handles around an unrelated
executable and a required library. Both lock cases, Bazel wrapper selection,
and the normal platform matrix remain pending on the shared CI candidate.

No full rewrite, release, required-platform, performance or legacy-retirement
claim is made by this record. Existing CI matrix entries, assertions and timeouts
are unchanged.
