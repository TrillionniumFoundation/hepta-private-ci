# P0 blockers: exact evidence and non-waiver migration plan (2026-10-12)

This is a read-only engineering audit, not production authorization. Source HEAD at audit: `99baf9b268095666245b9712c236cc655d16b061`.

## Exact-SHA status

- [Dedicated research CI 38189491114](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38189491114): Bazel module lock and Fleet strict Clippy/library tests succeeded. Native Worker contract test and other research jobs were not final at audit.
- v8-canary 38189491126: succeeded.
- [Global blocking CI 38189491257](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38189491257): not final at audit.
- [Older full-repo CI 38160752661](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38160752661): FAILED. The following is historical diagnosis, not a current-SHA verdict.

## Security dependency gates — older cargo-deny job 114534622884

1. **RUSTSEC-2026-0319**: `anymap2 0.13.0` is unmaintained; pulled through `matrix-sdk 0.18.0 → codex-hepta-matrix-sdk → codex-hepta-matrixd`. Advisory recommends `anymap3`, but there is no safe direct update for `anymap2`.
2. **RUSTSEC-2026-0318**: `matrix-sdk-crypto 0.18.0` can panic during `IdentityBasedStrategy` to-device encryption for recipients lacking cross-signing keys. Transitive owner: `matrix-sdk-base/sqlite → matrix-sdk 0.18.0 → codex-hepta-matrix-sdk`. Advisory specifies **>=0.19.0** crypto.
3. Separate yanked warnings involved `chacha20 0.10.0` and `spin`; review exact locked versions before touching these transitive constraints.

**Strict required fix**: vet and pin compatible Matrix SDK and crypto versions; adapt Hepta Matrix ingress and recovery callers; remove transitive `anymap2`; regenerate and verify `Cargo.lock` and `MODULE.bazel.lock`; run `cargo deny` under unchanged `deny.toml`, complete Matrix functional/crypto/revocation tests and obtain actual all-green CI on a single SHA. Do not add advisory ignores, severity downgrades or bypasses.

## Windows sandbox blockers — older Bazel job 114534623371

- Missing `codex-windows-sandbox-setup.exe` helper in runfiles.
- ACL regression failures: `partial_delete_deny_is_repaired_before_native_workspace_writes`, `workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces` and `legacy_workspace_write_delete_is_limited_to_writable_roots`.
- Required: validate helper/runfiles generation and Windows path resolution, inherited ACL policy and exact runner context; then rerun native Windows tests and Bazel shard suite without skipping security checks.

## Stem qualification

P0 is **BLOCKED** unless the final combined SHA passes Rust compile, test, fmt, Clippy, cargo-deny, cross-platform Bazel and global CI. P1 requires real signed CAS/current/final-use and restart/fence recovery, P2 approved pinned model weights, P3 target-machine 64–4096 Cell traces, and P4 independent future-window NDU/negative transfer. No mock output, digest declaration or research shadow trace counts as production success.

**Status: shadow-only, Draft PR, production authorization DENIED.**

## 2026-10-12 latest-head checkpoint: 8987efdaae7ec75f07171f159fa724dc5dab77d8

- This checkpoint is **not a release authorization**. Dedicated Stem L1: [38236387375](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38236387375), Matrix security candidate: [38236387380](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38236387380), and global blocking CI: [38236387735](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38236387735) were queued/pending at inspection. No latest-SHA green claim.
- Previous exact SHA `d55a1982d62e09ef1711774c3bd672af6a8e25d3` had **four successful dedicated L1 jobs**: [38103057957](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38103057957). That older success must not be projected onto this new head.
- The Matrix hard gate now explicitly evaluates candidate upstream source, compatibility, two SQLite resolver modes, dependency graph and an anymap3 backport. These are **diagnostic gates**, not proof of applied security remediation.
- Blocking criteria remain unchanged: actual `cargo deny check --locked` with no ignores, no resolved `anymap2`, patched compatible crypto, real Matrix E2EE/SQLite and revocation/recovery tests, cross-platform Bazel and exact-SHA global CI.
- Even after P0, L2/L3/L4 require audited actual Encoder snapshots, target-host measurements and independent future-window NDU outcomes. No Shadow result authorizes production routing.
