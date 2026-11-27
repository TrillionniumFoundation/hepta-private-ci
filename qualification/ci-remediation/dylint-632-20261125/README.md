# Dylint 6.3.2 qualification

The main CI at `804ac018433ff08dfd195e93eed936394baf5053` failed before its
argument-comment UI tests could run. Job `138723341148` in run `45458387224`
built Dylint 5.0.0, whose driver bootstrap tried to resolve Clippy's removed
`master` branch. The original decoded job log is retained in `evidence.zip`.

The fix pins `dylint_linting`, `dylint_testing`, `cargo-dylint`, and `dylint-link`
to 6.3.2. That released version includes the upstream
[Clippy branch rename fix](https://github.com/trailofbits/dylint/commit/f1ed83623faead3799afd91533f8647715272c33).
The existing nightly compiler, Clippy revision, lint rules, UI fixtures, and
workflow checks remain unchanged. The dependency lock was generated with the
actual `nightly-2025-09-18` Cargo.

## Observed local results

| Check | Actual result |
| --- | --- |
| Original nightly installation | Rust 1.92.0-nightly, commit `4645a7988`, with rustc-dev, LLVM tools, and rust-src |
| Library and driver bootstrap | Exit 0 in 145.08 seconds; both lints registered |
| Bootstrap source lookup | Upstream default Clippy clone; no supplied-repository override |
| Existing tests through `just test` | 8 passed, 0 skipped, across 2 binaries |
| UI harness | Passed in 23.942 seconds |
| Existing Python wrapper tests | 6 passed |
| All tracked lint package inputs | 30 files matched their Git blobs after execution |

The eight tests include the strict-lint promotion checks and the existing UI
harness. The inner compiler fixtures are not counted again as independent
outer tests. Source and lock digests before and after each successful run are
in the receipts.

The first local test invocation stopped before running any test because the
main workspace's nextest configuration names packages absent from this
standalone tool workspace. That failure is retained. A local configuration
projection removed only overrides proven not to match this package, while
preserving the original 30-second slow-test period, two-period termination,
one retry, JUnit output, all test inputs, and all assertions. The production
nextest configuration and CI commands were not changed.

## Scope

This qualifies the fixed lint package and driver on local Linux. It does not
declare the consolidated unpublished source tree, macOS, Windows, or the next
GitHub CI run successful. Dylint resolves a separate temporary driver
dependency graph upstream; the evidence does not claim that graph is hermetic.

`evidence.zip` retains the original CI failure, successful bootstrap and test
logs, failed local configuration attempt, input digests, official tool archive
digests, and configuration projection receipt. Its `checksums.json` records
every other member's byte length and SHA-256. No compiled executable or
private account evidence is distributed.
