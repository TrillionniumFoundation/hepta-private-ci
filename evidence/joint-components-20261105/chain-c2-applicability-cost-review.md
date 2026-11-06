# Frozen C2 applicability cost review

## Disposition

The original applicability gate remains **FAIL: 300-second command timeout** on Chain commit `03521b2f32346a49cccde8ff72e8c7b886b31222`, tree `e0235248ecae2a67717c8b9ff2e3f25774ba63d7`. This independent review found a substantial, concrete repeated parsing cost in the source checker. It does not establish the exclusive cause of the timeout or qualify a repair. C2 source, test assertions, command budget and frozen identity were left unchanged. No new candidate, Cargo command, applicability rerun or W1 sampling was performed by this review.

The machine-readable [review record](chain-c2-applicability-cost-review.json) binds the six inspected C2 files to Git blob IDs and SHA256 values, the original execution manifest and raw stderr, recomputed static call counts, and the proposed safety boundaries. Its SHA256 at creation is `e99a43622458dab4cf47ac5c649703411d8e4e092eee19ba6c5040d2df722dae`.

## What the original execution establishes

The recorded command was `python3 -B scripts/ci/test_applicability.py`. It ended with exit code `-9`, `timed_out: true`, and elapsed time `300005678623` ns under its original 300-second budget. The 1,111-byte stderr has SHA256 `a4d01ec2eb290bccb58d13b6deca0c933bbf28e1ea98acef37a11c60cb89820b`. Seven test lines completed with `ok`; the eighth, `test_factor_and_public_queue_bind_real_tests_without_execution`, started without a completion line. The C2 source identity before and after the command was equal. These are observations from `w1/C2-native-checks-manifest.json` and its retained raw stderr, not inferred results.

The eighth test first invokes `validate(self.root)` and then performs registry-field assertions. No execution stack was sampled at timeout. The log therefore does **not** show that the eighth test alone consumed 300 seconds, nor which helper was active when the process was killed. The budget covers the entire command, including earlier tests and class setup. The class copies the source once in `setUpClass`; it does not repeat that copy for each test. This rules out attributing the eighth test's start to a new per-test copy, while leaving the first copy's contribution to the total duration unmeasured. [C2 test source](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/03521b2f32346a49cccde8ff72e8c7b886b31222/scripts/ci/test_applicability.py)

The inspected test file is C2 Git blob `d823f1da8a93d748b93b7185989c43986ee8c6ba`. The older file under `w1/diagnostic-base` has a different blob and was explicitly excluded. This distinction matters because the newer registry and test suite contain additional responsibilities and selectors.

## Repeated work in one full validation

`check_applicability.validate` imports and invokes `report_module_evidence.validate_contract` at line 258. This is not `check_ci_contract.py`. It then checks each profile entrypoint and test selector, followed by current registry, configuration, documentation and delivery-status relationships. The validator itself invokes no Rust build or external test command. [C2 applicability validator](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/03521b2f32346a49cccde8ff72e8c7b886b31222/scripts/ci/check_applicability.py)

The frozen registries imply the following work for one successful, complete `validate(root)` traversal. These are static counts, not measured durations or claims about how far a failed traversal progressed.

| Work | Calls or entries |
| --- | ---: |
| Contract responsibilities | 39 |
| Applicability profiles | 24 |
| Contract test-selector calls | 779 |
| Profile test-selector calls | 324 |
| Total test-selector calls | 1,103 |
| Unique selector strings / source paths | 628 / 109 |
| Unique contract runtime symbol checks | 217 |
| Profile entrypoint symbol checks | 24 |
| Rust source-mask transformations / unique Rust paths | 1,373 / 100 |
| Python AST parses / unique Python paths | 575 / 71 |

The root of this duplication is visible in `report_module_evidence.py`:

- `check_symbol` reads the current file on each invocation. Python sources are passed through `ast.parse` via `python_symbols`; Rust sources are passed through `rust_code` before symbol or owner matching.
- `rust_code` copies the text into a character list, scans it in Python, masks comments and literals while preserving layout, and creates a new result string.
- `check_test_selector` first invokes `check_symbol`. For Rust it then reads the source again and repeats `rust_code` before checking the `#[test]` attribute. The same Rust selector therefore contributes two mask transformations.
- `validate_contract` has a local `(path, symbol)` set for runtime symbol references. It does not deduplicate selector parsing, and that set is recreated on each validation.

[C2 source-binding helpers](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/03521b2f32346a49cccde8ff72e8c7b886b31222/scripts/ci/report_module_evidence.py)

For example, one complete traversal statically entails 98 AST parses of `scripts/ci/test_work_rejection_report.py`, 81 of `scripts/ci/test_zero_locality_cost.py`, 72 mask passes over `account_archive_execution.rs`, and 72 over `authenticated_migration_tests.rs`. File sizes and parser paths differ, so these counts cannot be converted into equal-cost units. Some earlier negative controls also traverse all source bindings before rejecting a late delivery-status mutation. Repeated full traversals are consequently a concrete cost source within the original whole-command budget; their exact share of the 300 seconds was not measured.

## Minimal safe future optimization

The narrow candidate for later work is a bounded cache of **pure parsing transformations keyed by the exact freshly read text**:

1. Current text to immutable Rust mask string.
2. Current text to immutable Python symbol summary.

Every caller must retain safe-path validation and a fresh file read before looking up the transform. The key must include actual current content; path, modification time and size are insufficient. Full key equality must distinguish different texts even if their internal hashes collide. The first change should retain the existing two reads in the Rust-selector path, keeping its current refresh points intact.

`python_symbols` currently returns a mutable `set`. Caching that object directly would allow accidental mutation to contaminate later checks. A private cached `frozenset`, with a fresh copy where a mutable public return type must be preserved, avoids that new shared-state behavior. Rust's string output is already immutable. Read failures, invalid paths and parse failures must continue to reject.

No whole-validation success, selector verdict, root/path result, registry relationship or documentation relationship should be cached. Tests intentionally modify and restore those bytes at the same paths. The fake Rust test fixture specifically reuses one file while replacing its content with line comments, nested block comments and a raw string. A cached verdict by path would weaken these negative controls. [C2 mutation controls](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/03521b2f32346a49cccde8ff72e8c7b886b31222/scripts/ci/test_applicability.py)

The cache must have bounded retention, and its retained input/output bytes need evaluation. An entry count alone is not a byte budget; a large-input bypass or explicit memory cap can address that distinction. Current file reads, content-key work, Rust implementation-body scans, and every relationship check would remain. This proposal does not establish linear total cost or a pass inside 300 seconds.

Before qualifying any later implementation, its unchanged original gate should exercise warmed-cache source mutations with the same path, timestamp and length; comment/string/helper substitution; missing files and symlink escapes; registry/document/revision mutations; restoration; and eviction. Those controls are a proposed future validation scope. They were neither added nor run in this review. The current disposition is to preserve frozen C2 and complete the separate final H1 work.
