# Native stdin UTF-8 consumer evidence

Source commit `cad201d43ff0bb7495a72f496a859a16474b2af0` preserves the exact
pre-format tree `55663ab8e80b5caf32da71eb557a2140b2a8597c` used by the Linux
consumer and complete stream-parser runs. The macOS default package runs use
the same production Rust inputs; their earlier tree and input hashes are kept
in the records. All six original decoder tests remain intact.

| Gate | Actual result |
| --- | --- |
| Pinned native37 build | All 37 modules built; B1/B2/B3 match the configured compiler hash |
| Raw HIA UTF-8 ABI | 25 cases, 200 native calls passed |
| Production Rust decoder | 11 original/new unit tests in each selection passed |
| Decoder stdin cases | 18 cases in each selection passed; native symbol selection checked |
| Linux native stream-parser | 87 passed, 0 skipped |
| macOS default stream-parser | 67 passed, 0 skipped |
| macOS default exec package | 158 passed, 0 skipped |
| Scoped strict Clippy fix | Both changed packages passed with `-D warnings` |
| Formatter | Passed; only one assertion was rewrapped, with no production byte changes |
| Bazel dependency lock | Actual update and check passed; the existing module lock stayed identical |

`linux-native-gates.json`, `macos-fix-format.json` and `bazel-lock.json` are
byte-for-byte copies of the actual result records. The compressed archives
preserve the complete original logs, the native caller's artifact and command
bindings, and the recorded failures. The macOS archive's manifest binds each
file's bytes. The original compile failure, resolved by moving the six existing
tests beside their extracted implementation, is retained. The offline metadata
precondition and unsuccessful macOS Bazel download are also retained; the latter
is not counted as lock qualification. The successful lock check ran on Linux.

Fix/format ran after tests. Its only diff rewraps an assertion in
`codex-rs/exec/tests/suite/prompt_stdin.rs`; its condition and expected text are
unchanged. No tests were repeated after that formatting step.

The full native exec package and relocated full CLI still require their normal
CI gates. This record does not qualify the whole capability, default release,
required platform matrix, performance, or legacy retirement.
