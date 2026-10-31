# Review and publication stages

This package is deliberately isolated from the existing Cargo workspace and
production callers. The following stages keep each code batch below 800 lines
and each production-logic batch below approximately 500 lines. Intermediate
stages are review slices of one unactivated research package, not separately
deployable services. The final combined package is the qualified artifact.

| Stage | Files | Code lines | Review focus |
| --- | --- | ---: | --- |
| 1 | `contract.rs`, `store.rs` | 474 | Typed physical/cancellation state, exact time-price arithmetic, OS lock, atomic immutable publication. |
| 2 | `native.rs`, `settlement.rs` | 459 | Real original runtime composition, original numeric profile, full settlement and outcome validation. |
| 3 | `engine.rs`, `main.rs`, `build.py`, `owner-Cargo.lock`, `fixture.json`, `rustfmt.toml` | 746 | Fenced execution, native ownership, effect boundaries, offline source-verified build and explicit entry point. |
| 4 | `contract_tests.rs`, `verify.py` | 608 | Behavioral tests and actual-process contention/SIGKILL qualification. |
| 5 | `README.md`, `CONTRACT.md`, this file, `MANIFEST.json`, `evidence/*` | Documentation/data | Scope, immutable evidence, retained failures, reproducibility and final provenance. |

Stage 3 builds the executable; its `cfg(test)` module is supplied in Stage 4.
Consequently the tests should be assessed on the combined stages, as recorded
in the evidence. The manifest supplies one final byte-level identity independent
of how the commits are split. No native crate is patched or duplicated.

## Independent review addressed

An independent read-only review identified nonregular-source blocking, dangling
link handling, genesis refractory state, untyped outcome/accounting combinations,
and a historical replay path that could open native state past an unknown effect.
The implementation now uses regular-file/no-follow checks, strict typed state
and outcomes, and a run-wide unresolved-dispatch fence before all native opens.

The first real SIGKILL experiment found that native bootstrap writes a header
before its first acknowledged checkpoint. Moving **all** native opens after the
dispatch fence made the prepared-only case resumable without changing the native
recovery algorithm. The failure is retained in `evidence/INITIAL_FAILURE.json`.

Credit review then identified zero-time WAIT decay and integer truncation. The
price now uses trusted physical elapsed time and an exact fractional residue.
A subsequent review found that a single combined projection could bank idle
allowance, while gating on the previous price made an explicit WAIT change
admission. The final implementation uses idle projection, current-price admission,
and endpoint charging in order. The reviewer also identified a hit accepted at
the exact refractory-release instant; it is now rejected, with a defined minimum
one-microsecond active interval. The preceding binary's actual counterexamples
are preserved in `evidence/COUNTEREXAMPLES_BEFORE_FIX.json`.

The reviewer checked the final price ordering, exact residue comparison and
idle semigroup, full three-pair history validation, integer overflow bound, and
strict refractory-release inequality without rerunning or manufacturing tests.
The new final binary was then exercised by the recorded qualification suite.

## Final gates

- `cargo build --offline --locked` in a declared derived workspace: passed.
- Repository `just test`, limited to this standalone package: **10 passed,
  zero skipped**, with original native dependencies linked.
- Actual process harness: **21 tests passed**, **108 subprocess invocations**,
  **9 external SIGKILLs**, and no rerun of an indeterminate effect.
- Canonical repository `just fmt`: passed; final compiled-source digests checked
  after formatting. No whole-workspace testing or production activation occurred.

The final source digest and exact binary hash are in `MANIFEST.json` and
`evidence/BUILD_REPORT.json`. The process evidence binds that same binary hash.
