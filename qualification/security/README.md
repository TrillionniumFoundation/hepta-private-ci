# Matrix SDK 0.19.1 / Rust 1.96: unpromotable RustSec investigation

**Shadow trial only.** This does not change `codex-rs/Cargo.toml` or
`Cargo.lock` in Git, migrate the production Matrix service, load Jina weights,
bypass a security advisory or authorize a Cell/Worker action.

## Why a dedicated migration probe?

At the 2026-10-12 full-repo `cargo-deny` run the existing Matrix SDK 0.18.0
pulled in `matrix-sdk-crypto 0.18.0` (RUSTSEC-2026-0318), `anymap2 0.13.0`
(RUSTSEC-2026-0319) and separately `serde_yaml` pulled in archived
`unsafe-libyaml` (RUSTSEC-2024-0449). Those were **real blockers**.

The official Matrix SDK 0.19.1 crate (September 18, 2026) includes the
crypto fix, but its published `Cargo.toml` declares
`rust-version = "1.96"` and still requires `anymap2 = "0.13.0"`.
Hepta's current owner CI is Rust 1.95. Therefore simply replacing
`matrix-sdk = "0.18"` with `"0.19.1"` would give a false sense of
resolution: it requires a toolchain/Bazel upgrade, a real API regression test,
a new exact locked dependency graph and a separate replacement/removal path
for the unmaintained dependency.

References:
- https://rustsec.org/advisories/RUSTSEC-2026-0318.html
- https://rustsec.org/advisories/RUSTSEC-2026-0319.html
- https://rustsec.org/advisories/RUSTSEC-2024-0449.html
- https://docs.rs/crate/matrix-sdk/0.19.1/source/Cargo.toml

## What the scratch job actually does

The path-scoped GitHub workflow
`.github/workflows/hepta-matrix-rustsec-0191-shadow.yml`:

1. Runs pure-stdlib tests for input pinning, toolchain compatibility and
   strict **unwaived** advisory interpretation.
2. Checks out a disposable copy of the exact PR SHA without persistent
   credentials. Only **inside this checkout**, `prepare` replaces the
   one exact manifest line for Matrix 0.18 with `=0.19.1`.
3. Installs Rust 1.96, runs an actual `cargo update -p matrix-sdk --precise
   0.19.1`, builds/tests the *real* Matrix SDK and Matrixd owner crates and
   runs strict Clippy. Any compiler/API mismatch remains a CI failure.
4. `inspect` reads the **resolved, not invented** scratch `Cargo.lock`,
   verifies 0.19+ for the Matrix SDK family, then marks RUSTSEC-2026-0319
   and RUSTSEC-2024-0449 as blockers if still present. This step exits
   nonzero when any of the three known advisories remains.
5. Uploads the proposed scratch `Cargo.toml` and `Cargo.lock`, plus a
   machine-readable verdict when available, as a short-lived artifact.
   It **never** pushes these changes back to protected branches.

The workflow being red when `anymap2` remains is intentional and safer
than advisory ignores. It must not be given the same label as a production
repair. A future migration must separately remove all unsafe/abandoned
transitive crates, regenerate and review the exact lock, run platform CI and
only then be proposed for production.

Run source-only policy tests without a Rust toolchain:

```bash
PYTHONPATH=qualification/security python3 -m unittest discover \
  -s qualification/security -p 'test_matrix_sdk_0191_trial.py' -v
```

## Non-negotiable release criteria

The new version is **not** production-ready until all of these happen:
- Rust 1.96 is approved for all relevant Cargo and Bazel toolchains.
- Real Matrix SDK integration tests pass on Linux, macOS and Windows.
- A reviewed, checked-in `Cargo.lock` is compatible with every workspace
  caller, including cryptographic state/checkpoint formats and downgrade
  behavior.
- `cargo-deny` succeeds **without** any advisory ignore, both for
  `matrix-sdk-crypto` and `anymap2`, as well as `unsafe-libyaml`.
- Exact final SHA global CI is green, and independent production
  authorization, CAS, WAL/fault recovery and NDU/real learning/resource
  qualifications are not conflated with dependencies.

All generated reports explicitly deny production promotion.
