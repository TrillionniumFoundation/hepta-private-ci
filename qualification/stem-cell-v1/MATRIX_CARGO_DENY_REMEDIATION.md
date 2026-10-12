# Matrix SDK cargo-deny remediation (fail closed)

This is a blocker report, NOT a security fix or permission to merge.

**Exact evidence:** Hepta PR #1495 at `993ec78366ea7d88fc14a3bc4547086a81b07942`,
blocking-ci run 38193301602, cargo-deny job 114632441761 failed:
- RUSTSEC-2026-0318: matrix-sdk-crypto 0.18.0; patched upstream >=0.19.0.
- RUSTSEC-2026-0319: anymap2 0.13.0 unmaintained, via matrix-sdk 0.18.0. RustSec recommends anymap3.
- Also review yanked chacha20 0.10.0 observed in the dependency graph.

**Critical pitfall:** The published `matrix-sdk 0.19.0` manifest still depends on
`anymap2 ^0.13.0`; an SDK upgrade alone cannot be called full remediation.

References:
- https://rustsec.org/advisories/RUSTSEC-2026-0318.html
- https://rustsec.org/advisories/RUSTSEC-2026-0319.html
- https://docs.rs/crate/matrix-sdk/0.19.0

## Strict migration prerequisites

1. Pin candidate SDK family versions and inspect full Cargo feature/dependency graph.
   Account for the local `third_party/matrix-sdk-sqlite-0.18.0` fork and
   `codex-hepta-matrix-sdk` / `codex-hepta-matrixd` API/test compatibility.
2. Upgrade matrix-sdk-crypto to a vetted >=0.19.0 release *with matching
   compatible SDK family crates*. Remove every resolved anymap2 dependency
   through upstream migration or independently reviewed source change.
   Do NOT add advisory ignores, disable cargo-deny, substitute an imposter crate,
   or declare success solely from a new version number.
3. Regenerate Cargo.lock using the repo's pinned toolchain; update MODULE.bazel.lock
   with `just bazel-lock-update` and verify with `just bazel-lock-check`.
4. Verify `cargo tree --locked -i anymap2` has no remaining roots,
   `cargo tree --locked -i matrix-sdk-crypto` resolves to a patched release,
   and `cargo deny check --locked` passes. Check the other yanked transitive crates.
5. Execute real Matrix federation/device/identity/to-device tests, including
   recipients without cross-signing keys, along with store restart/recovery.
   Run locked Rust builds, fmt, Clippy, Bazel and global blocking-ci on one SHA.
6. Keep Hepta production promotion disabled until the full exact-SHA
   blocking-ci is green. Passing Stem L1 CI is a *separate* and insufficient gate.

This document does not change dependency versions or security posture.
