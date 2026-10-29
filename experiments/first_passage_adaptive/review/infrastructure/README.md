# Infrastructure qualification for the frozen research branch

The frozen first-passage study, selected models, confirmation data and native
owner source identity are unchanged. These changes repair failures in the
surrounding repository gates so that the study remains reproducible while the
current production dependency graph receives separate security qualification.

## Evidence and scope

| Check | Observed result | Retained record |
| --- | --- | --- |
| Original dependency policy, all features | Advisories, bans, licenses and sources: zero errors; original policy unchanged | `security/SECURITY_MIGRATION_VERIFICATION.json` |
| AWS and Matrix owners | Actual owner library checks passed | Same security record |
| Vendored compatibility patches | Five upstream snapshots, eight modified upstream files; exact file and reverse-patch identities checked | `codex-rs/third_party/SECURITY_PATCHES.json` and `scripts/verify_security_vendors.py` |
| YAML migration | Sixteen focused source tests and 48 legacy comparison documents passed; whole-owner compilation remains a separate CI check | `OWNER_COMPATIBILITY_REVIEW.json` |
| ZIP migration | Actual extraction source test passed for both malicious special permission bits and ordinary permissions | Same security record |
| Async file descriptors | Actual PTY workspace: 27 tests; actual socket module: seven tests; scoped PTY `just fix --locked` passed | `ASYNCFD_IO_SAFETY_REVIEW.json` |
| Bazel lock | Canonical update and strict error checks passed for the final Cargo/features; native dependency patches materialized | `bazel/NATIVE_PREFLIGHT.json` |
| Fixture and FIFO changes | Independent source review; complete owner execution is checked by the new-head CI | `OWNER_COMPATIBILITY_REVIEW.json` |
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

## Acceptance boundary

Local checks and previous-head successful workflows do not establish that a
new commit has passed the complete repository CI. Acceptance uses the checks
attached to the exact pull-request head. The production ledger defaults, all
existing blocking gates and the scientific confirmation protocol stay in force.
No production activation or measured energy advantage is claimed.

`MANIFEST.json` binds the retained records and compressed raw logs. The separate
scientific evidence archive remains byte-for-byte unchanged.
