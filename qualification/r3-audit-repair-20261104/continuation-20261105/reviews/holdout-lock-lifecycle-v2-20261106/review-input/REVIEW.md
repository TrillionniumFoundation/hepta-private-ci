# Independent review — holdout file-lock lifecycle

**Decision: REQUEST_NARROW_TEST_LINT_REVISION. The lock-ownership implementation passes this source review; the frozen candidate has one concrete normal-CI lint issue in added test code.**

This review covers author freeze `b86d33c1f8f550decc9f15020142880dcf2f9bb7`, registry `6b1f56cdb8a80535a916a7ed23e09d1bd5108824`, and complete candidate tree `7c18622c5c1b69826f7103dd2b2fec5bf572ae3a` against source commit `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed` / tree `3982ba56dc5a3f1da0c1de7ea57992f88125c359`. The reviewer did not edit author inputs, refs, PRs or CI, and did not trigger or rerun workflows. Publication is reserved for the root reviewer.

## R1 — annotate the new positional `None` arguments (P2)

The appended test `dropping_store_unlocks_while_a_duplicate_file_remains_open` contains `let first = owner(store, None);` at candidate test line 302. Its local helper's second parameter is named `minimum`. The fixed repository guidance requires `/*minimum*/ None`. More than style is involved: the fixed Bazel lint aspect passes `-Duncommented-anonymous-literal-argument`; the lint checks direct local function calls, identifies `Option::None`, and requires a matching parameter comment. The target listing explicitly includes the manual Rust unit-test binaries. Neither the crate's BUILD file nor its module source supplies a relevant opt-out. This ordinary, non-macro helper call is therefore a concrete source-level incompatibility with that gate, although the lint itself was not executed here.

**Requested revision:** use `owner(store, /*minimum*/ None)` in the new test. Also annotate the two new `recover(..., None)` arguments at candidate test lines 352 and 359 as `/*minimum*/ None`, as required by the same source guidance. Preserve the original 10,243-byte test prefix, all assertions, and all original test budgets. No production-logic change is requested. Re-freeze the changed test blob and tree; this review must not be represented as accepting a different candidate identity automatically.

Evidence is preserved in `lint-source/` and its immutable base-tree identities in `VERIFICATION.json`. The relevant fixed source is [the strict Bazel flags](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed/tools/argument-comment-lint/lint_aspect.bzl), [the call and literal checks](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed/tools/argument-comment-lint/src/lib.rs), [the unit-test target discovery](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed/tools/argument-comment-lint/list-bazel-targets.sh), and [AGENTS](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed/AGENTS.md).

## Ownership and error-path findings

- The private `FileLock(File)` is constructed only after successful `try_lock`. Binding, metadata, non-regular-file and failed-acquisition exits do not construct that guard or call its explicit unlock. The `WouldBlock` to `Busy` mapping is preserved.
- Both constructors immediately own the guard. Every subsequent `?` or early return drops it, including already-initialized creation, missing/corrupt headers, capacity, replay, retained-minimum validation and final synchronization failures. Normal store destruction also drops it. Its `Drop` attempts `File::unlock`, after which normal field destruction closes the file. Unlock failure remains unreported in `Drop`; the candidate does not establish infallible release under OS errors.
- The outer store and generic owner do not acquire a `Drop` implementation. The existing `into_store(self) -> S { self.store }` therefore retains its move semantics. No move out of the inner `FileLock` occurs, no clone is added to production code, and no new public API is introduced.
- The exact-delta proof reconstructs the original production file byte for byte when the ownership wrapper/access changes are reversed. File encoding, header and checksums, nonblocking acquisition, fence and anchor checks, rollback rejection, CAS transitions, size limits, append/fsync order and poison behavior are retained.
- All original three tests remain an exact 10,243-byte prefix. The three appended tests exercise a duplicate kept alive across normal store destruction and across two distinct constructor-error paths. Their fresh opens and Busy controls test exclusion while the new holder is alive. The first also exercises `into_store` and retained-anchor recovery. These are meaningful lifecycle regressions, not a weakened original assertion or a sleep/retry workaround.
- No source-level ownership, borrowing, dependency or API-stabilization issue was found beyond R1. `pretty_assertions` is already a development dependency. This is not a compiler or formatter result.

These findings concern the intended sole owning store. As already permitted by the `File` API, callers retaining another handle can deliberately interfere with the file or its lock. The change does not create an additional production clone or expose a new handle.

## Independent evidence verification actually performed

Fresh immutable full GETs were obtained for the actual registry, both candidate blobs, both base blobs and the candidate root tree. Their full decoded bodies were retained. Each blob identity was recomputed and compared with the frozen local bytes; the candidate root's 53 entries recompute to its stated Git tree ID.

| Object | Immutable ID | Bytes |
| --- | --- | ---: |
| Actual registry | `6b1f56cdb8a80535a916a7ed23e09d1bd5108824` | 21,800 |
| Candidate production file | `603d36b01f6f8fe7472c72588e793f8ef169a08b` | 16,163 |
| Candidate test file | `2c451a3c110288ca06eb43724329c48c39bb8f1e` | 13,010 |
| Base production file | `d496f6865d39e98d7b92ed62ebf130945cd8266c` | 15,770 |
| Base test file | `e6cb964c82d7aea02acae338c739ac1e5158dd3a` | 10,243 |

The registry's recomputed SHA-256 is `388c7b8ae6e8458046206192069fe53249ef22a87d75d3371c2066a99f8aaaad`. All 108 frozen payload identities and all 24 local registered-object payloads match. The packet was restored into a new isolated reviewer directory: 109 members, exact member bytes, original freeze identity retained. Its archive is 1,520,354 bytes.

The inspected static verifier then ran independently with the complete existing source archive. It exited **0**, with **0 stderr bytes** and **2,776 stdout bytes**, exactly equal to the frozen final stdout; Git blob `fbc2e4f75bb22e74a4b3ff8367e8fad711e95541`, SHA-256 `bc897af35779e56e67f5ae3c5a44c2a2591795a5f47157cc448380fb89aa6cf3`. This includes the full 4,832-file Rust search replay (112 matching lines in 11 paths), two changed leaves, 10,580 unchanged leaves, exact patch round trip, source identities, original-failure receipts and author mechanism-receipt consistency.

The reviewer fully read both changed Rust files, their full patch, applicable AGENTS, the author README, verifier/helpers and packet restorer. `verify_independent_review.py`, `VERIFICATION.json`, the fresh GET envelopes and replay outputs preserve the independent checks.

## Acceptance boundary

`rustc`, `cargo`, `rustfmt` and `just` are absent here. **No candidate compilation, Rust project test, argument-comment lint or formatter execution occurred.** The author executed four controlled Python/Linux dup/fork mechanism cases; this reviewer only checked their frozen receipts and did not convert them into Rust or Mac acceptance.

The original Mac ARM job `127679861749` / run `42123581385` / artifact `13474454125` remains **114 passed, 1 failed**, with final `Busy` where `Rollback` was expected. The filtered child `1 passed` segments are not extra parent cases. The actual original holder, duplicated/inherited handle and scheduling timeline remain unknown; the posix_spawn caveat remains valid. No exact original-cause proof, original-platform pass, B15 closure, runtime activation or product-readiness conclusion is granted by this review.
