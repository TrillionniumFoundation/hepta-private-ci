# Native Agent convergence: isolated Rustfmt CI failure patch (2026-10-24)

## Exact provenance

- Parent source: `77d25b6d1dda5d0718f226960a5cf85ea69f8be7` (Draft PR #3603).
- Original hosted workflow: [blocking-ci run 40014746382](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40014746382), job [120768295842](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40014746382/job/120768295842).
- The runner checked out `refs/remotes/pull/3603/merge` (observed merge `6c04853`, parents printed by checkout). This is *not* a source-head result.
- Executed command: `cargo fmt -- --config imports_granularity=Item --check` (CI recipe `fmt-check`). It exited 1 and printed `Formatting failed: Rust`.
- This patch applies the 32 Rustfmt diff hunks emitted by that real job, across 16 Rust files, to the exact #3603 source head. Every old-text hunk was matched exactly once in that source head before replacement. No Rust statements, authority checks, deadlines or dependency manifests were intentionally changed.
- The hosted Rustfmt command has **NOT** been rerun against this new commit. Because the original failure came from a prospective merge, the new merge SHA also requires a separate test. Nothing in this note is a PASS receipt.

## Independently observed outstanding failures

- Same blocking-ci run's `cargo-deny` job [120768295811](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40014746382/job/120768295811) performed dependency auditing and **failed** on real RustSec advisories including `RUSTSEC-2026-0387`, `RUSTSEC-2026-0346`, `RUSTSEC-2026-0347`, `RUSTSEC-2026-0382`, and `RUSTSEC-2026-0383`. These are **not** fixed, ignored, or suppressed here.
- Runtime #29's zero-step Hosted CI failure is unrelated to this formatting patch and remains open.
- P0–P7 admission, independent signed Final-use, model/host/observers and production Canary remain `HOLD_NO_GO / DENY_ALL`. No merge, deployment or cutover is authorized.
