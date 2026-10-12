# Stem + Matrix Security · Isolated Qualification Candidate

This is a **draft, fail-closed integration candidate**, not a release, activation, or
claim of a passing combined CI run.

## Exactly pinned source parents

- Matrix advisory remediation source: `ffa1f2b11f5769268157b514395e15b53196cd5e` (the existing, independently reviewed [PR #1372](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1372)).
- Stem/Cell research source: `a0bb71865b93eafeb31987ba46d60034ecbd4d6e` ([PR #1495](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1495)).
- Both include canonical main `78fdb0cf8537e3a84fc6e0a849707559c80881e8`.
- The created integration commit has **two exact parent SHAs**; its security
  base tree is `39c6aa68c547583b778d242cde14e9f411b7a6fc`.
- Of the 60 Stem changes relative to main, 54 non-overlapping files are
  copied by **exact source blob SHA and mode**, never retranscribed.
- Four overlapping Fleet files are blob-identical. The single overlapping
  automation test differs only in two explanatory comments; the existing
  security-qualification source was retained.
- The overlapping `codex-rs/Cargo.lock` starts from the security-remediated
  lock and adds **only** the direct first-party
  `codex-hepta-learning-artifacts` dependency for the Worker crate. All
  SDK 0.19.1, anymap3, crypto and SQLite lock versions remain pinned from
  the reviewed security baseline.

## Non-negotiable validation

- Confirm `anymap2` and vulnerable `matrix-sdk-crypto 0.18.0` are absent
  from the combined resolved lock graph; never ignore RustSec advisories.
- Rust 1.96 toolchain, locked Cargo check/tests, scoped and global rustfmt,
  Strict Clippy, Bazel dependency lock, cargo-deny and full cross-platform CI
  must pass on **this exact combination SHA**, not on either parent alone.
- Matrix encrypted storage upgrade and Synapse send/sync/reopen must be
  requalified because dependency/layout changes can invalidate earlier receipts.
- A genuine independently authorized signed CURRENT, final-use and generation
  fence remains mandatory for native production inference. Synthetic encoders,
  mock signatures and fixture 4096-Cell tests do not meet P2/P3/P4.
- Keep this candidate **Draft** and separate from both owners until independent
  CI and review. No changes to deny/audit policy or production deployment.
