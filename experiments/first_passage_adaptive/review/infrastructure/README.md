# Infrastructure qualification for the frozen research branch

The frozen first-passage study, selected models, confirmation data and native
owner source identity are unchanged. These changes repair failures in the
surrounding repository gates so that the study remains reproducible while the
current production dependency graph receives separate security qualification.

## Evidence and scope

The table below records the earlier qualification retained at
`9b71cf4e65194593d5e0fb2a507026d21527a740`. Its successful local runs are historical
evidence, not results for the later runtime repairs.

| Check | Observed result | Retained record |
| --- | --- | --- |
| Original dependency policy, all features | Advisories, bans, licenses and sources: zero errors; original policy unchanged | `security/SECURITY_MIGRATION_VERIFICATION.json` |
| AWS and Matrix owners | Actual owner library checks passed | Same security record |
| Vendored compatibility patches | Five upstream snapshots, eight modified upstream files; exact file and reverse-patch identities checked | `codex-rs/third_party/SECURITY_PATCHES.json` and `scripts/verify_security_vendors.py` |
| YAML migration | Sixteen focused source tests and 48 legacy comparison documents passed; whole-owner compilation remains a separate CI check | `OWNER_COMPATIBILITY_REVIEW.json` |
| ZIP migration | Actual extraction source test passed for both malicious special permission bits and ordinary permissions | Same security record |
| Async file descriptors | Actual PTY workspace: 27 tests; actual socket module: seven tests; scoped PTY `just fix --locked` passed | `ASYNCFD_IO_SAFETY_REVIEW.json` |
| Bazel lock | Canonical update and strict error checks passed for the final Cargo/features; native dependency patches materialized | `bazel/NATIVE_PREFLIGHT.json` |
| Fixture and FIFO changes | Independent source review; canonical `just fix --locked` compiled the default test targets of memory and automation successfully, with no automatic edits | `OWNER_COMPATIBILITY_REVIEW.json` and `owner-fix/SUMMARY.json` |
| Spelling preflight | Original Codespell rules passed for changed first-party and new review text | `CODESPELL_PREFLIGHT_RESULTS.json` |
| Earlier SDK worktree failure | Both baseline and prior research head changed only the stale Bazel lock; five suites / 47 tests had passed | `SDK_CLEAN_WORKTREE_FINDING.json` |

`bazel/REPAIR.json` records the earlier successful lock regeneration. The later
`bazel/NATIVE_PREFLIGHT.json` supersedes its final-lock identity after actual
repository materialization found the zstd patch mismatch and Matrix compilation
required anymap's `std` feature. Both original records and raw archives are
retained, including the unsuccessful attempts. The final lock SHA-256 is
`36e52d219967278c1c1d29bf760a41a4c0af5a01dd7f91a5410c89ae552c1e94`.

The ZIP 9 `unix_mode()` API already removes special permission bits. The explicit
ordinary-permission mask documents the same owner contract; it is not evidence
of a separate vulnerability surviving that dependency upgrade. Keyring review
establishes the synchronous API and SecretService credential namespace from
source. It does not establish live desktop unlock, legacy-entry access or
restart persistence; see `KEYRING_FEATURE_COMPATIBILITY_REVIEW.json`.

## Runtime repairs after full repository CI

The first full CI run exposed additional compiler, platform and lifecycle
failures. The follow-up changes preserve the original security policies and
scientific evidence. They repair CLI crate entry attributes, current Matrix
test APIs, qualification feature wiring, native binary/runfiles discovery,
descriptor ownership, queue completion ordering, current migration fixtures,
private temporary paths and Darwin release publication permissions.

The transient workspace reset removed unpublished local logs. Published
records were restored unchanged; new runs and newly retrieved original CI logs
are identified separately. Reconstructed source is not presented as a recovery
of missing raw logs.

| Record | Contents and boundary |
| --- | --- |
| `ci-recovery-20261030/` | Actual Bazel update/strict lock checks, 12-target feature query, wrapper regressions, Windows operator type checking and Unix operator execution. The initial operator Clippy attempt stopped at ENOSPC before compilation. Supplements retain platform fixture and path-order reviews. |
| `runtime-math-20261030/` | Actual Matrix owner type checking, the subsequent ENOSPC failure before behavioral execution, five bounded child-process diagnostic probes and independent runtime-owner review. Mac startup diagnostics are not a claim of root-cause closure. |
| `runtime-holder-20261030/` | Protocol generation, platform contracts, queue and PTY observations. Each attempted command retains its actual result; an environment failure is not a test pass. |
| `runtime-root-20261030/` | Historical source materialization, restored scientific audit, CAS ownership, migration/recovery fixtures, Darwin release publication and final local verification records. |
| `linux-ci-9b71-20261030/` | Complete deduplicated GNU/musl failure inventory and the original Architecture job logs, with a source-owner mapping for every observed failure category. Coverage is distinct from successful new-head execution. |

Fresh local checks include 303 protocol tests after both canonical schema
generators, 27 PTY tests, 286 platform-contract owner tests, 128 holdout owner
tests, 24 Unix operator tests and 42 Fleet tests. The selected memory and
automation regressions also pass. These counts describe their recorded Linux
executions; they do not qualify Windows or macOS execution. Scoped canonical
Clippy and formatting completed, and all 39 frozen scientific source hashes
still match after formatting.

The test launcher canonicalizes temporary paths for unit tests and sharded
integration tests that use its workspace wrapper. Unsharded native integration
tests can be direct Rust tests and need self-contained canonical fixtures.
The authorized-read repairs address those fixtures without changing production
path authorization. Seatbelt tests compare complete exclusion path collections
and verify each parameter's literal/subpath denial; exclusion numbering alone
does not define authority.

The existing source policies still reject unsupported platform authority and
unqualified directory durability. Added Windows tests exercise that refusal;
they do not manufacture an implementation of a missing platform capability.

## Acceptance boundary

Local checks and previous-head successful workflows do not establish that a
new commit has passed the complete repository CI. Acceptance uses the checks
attached to the exact pull-request head. The production ledger defaults, all
existing blocking gates and the scientific confirmation protocol stay in force.
No production activation or measured energy advantage is claimed.

`MANIFEST.json` binds the retained records and compressed raw logs. The separate
scientific evidence archive remains byte-for-byte unchanged.
