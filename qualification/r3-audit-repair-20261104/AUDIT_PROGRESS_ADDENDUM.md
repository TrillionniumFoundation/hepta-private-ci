# Audit follow-up: final native composition and concurrent work

This addendum records source and target-level observations after the 2026-11-04 16:58:59 UTC inventory. It does not certify release readiness.

## Final composed source

The 48 source changes relative to e729 reconstruct GitHub tree `edcc50b93a0b95342567bdfe98e5c0d96c85e52f`, exactly equal to the final native tree. Required scoped `just fix` returned zero in 783.970634715 seconds, final `just fmt` returned zero in 4.734201176 seconds, and `git diff --check` returned zero. The only automatic change removes a redundant clone from one new test. See `COMPOSED_SOURCE_MANIFEST.json` and `FINAL_NATIVE_CHECKS.json`. Earlier tests remain attributed to their own fixed trees in `SECOND_BATCH_QUALIFICATION.md`.

## First-batch canonical fixtures

The original AuthBus, kernel-evidence and terminal-cell Bazel targets passed on all applicable original platforms on merge `6b280676de379d002735d713d8ac1f64850df508`, whose tree equals e729. AuthBus/kernel files are Unix-only; their Windows targets do not demonstrate Unix testcase execution. The terminal-cell suite retains one existing ignored local-history case. Complete passed-target stdout/JUnit was not printed with the original `test_output=errors` setting, so the conclusion is target-level. See `B06_ORIGINAL_PLATFORM_TARGETS.json`. Later TUI repair qualification remains separate.

## New PRs do not replace the qualified candidate

- [#4800](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4800), head `6b715d2c92ce8ab74f0829ce6926fe8dfc8d7f5f`, has nine paths and two commits on A39. Its native G2 socket publication component preserves peer checks and uses guarded pending-name publication. Five prerequisite native G2 files are absent at e729. The large e729 comparison is divergent and truncated; the nine-file PR cannot be treated as an independent patch for this candidate. Its six new Root fixtures are explicitly ignored. It neither selects the ordinary joint Desktop producer nor closes B16.
- [#4801](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4801), head `79eed5dd57b34af8861313397f13a05fa7a806d2`, changes one recovery test file on #4799. Its per-TurnStart UnlessTrusted fixture differs from this candidate's supported configuration plus exact Python prompt rule. The tested source blob here remains `43cd9b0c2d1ba3a6560ade3f3a85616674fcd4c8`; its qualification does not transfer to the other PR's `9727b00ddff87b5255021a16167588ec078104bf`. No other PR was closed or merged.

The latest-entry review verified nineteen complete fetched source blobs. Its final local patch-reconstruction command did not execute because the cloud workspace became unavailable; no patch-apply or compilation success is inferred. Publication below uses the already-created immutable GitHub objects and the original native final receipts, without replaying Cargo.

## Project gates

Keep one fixed product candidate and finish its original platform matrix. Normal trusted product entry still requires the complete Root/Session, registry/arg0, checkpoint/verifier, FinalUse/issuer, listener-custody and ordinary UI caller cohort, together with the paired Desktop producer migration. Real completion, cancellation, lost-ACK and restart acceptance still require the original trusted inputs and physical-effect observations. External Bao/Chain/HIA acceptance and independent scientific adoption remain separate gates; unchanged negative scientific conclusions are retained.
