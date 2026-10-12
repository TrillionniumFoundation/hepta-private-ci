# Matrix SDK dependency security remediation probe

## Confirmed global blocker

In blocking-ci #38205575679 at commit ae12ba67, cargo-deny rejected
RUSTSEC-2026-0318 for matrix-sdk-crypto 0.18.0 and RUSTSEC-2026-0319
for unmaintained anymap2 0.13.0 via matrix-sdk 0.18.0. The upstream
matrix-sdk-crypto fix is in version 0.19.0 and newer. Upstream's latest
matrix-sdk 0.19.1 still directly depends on anymap2, so a simple 0.19.1
version bump alone CANNOT establish passing cargo-deny or be accepted.

Do not ignore, downgrade, suppress, reclassify, or self-sign the advisory.

## Read-only, exact-source upgrade qualification

The related GitHub workflow checks out an exact SHA with contents:read
permissions. In an isolated temporary CI checkout it pins the workspace
Matrix requirement to exactly 0.19.1, resolves dependencies and generates
a candidate Cargo.lock. It tests Matrix SDK and Matrixd all targets,
runs the existing repository cargo-deny action WITHOUT policy exceptions,
and retains resolver output, the actual candidate lock, source diff and
resolved dependency tree. It cannot push, deploy, promote or switch Neuron.

The workflow is deliberately red if any resolution, compile or unignored
advisory gate fails, even when all Rust test fixtures happen to pass.
The candidate lock and manifest are NOT committed automatically.

## Correct remediation path

First obtain actual 0.19.1 upgrade/compatibility evidence. Next eliminate
anymap2 at the originating Matrix SDK dependency, preferably with a
maintainer-supported release migrated to a maintained map abstraction;
alternatively review a separately maintained, provenance-pinned and
license-audited vendor fork. A fork still requires exhaustive API, cargo-deny
and security review; name aliasing or advisory exceptions are NOT fixes.

Finally commit a real resolver-produced Cargo.lock and source changes,
re-run native Matrix/Matrixd tests (including encrypted room and Synapse),
cross-platform Bazel, strict Clippy and cargo-deny on the exact final SHA.
Until then, global CI is not accepted and PR #1494 remains Draft. The
Matrix dependency issue is independent from real Neuron no-change/NDU proof.

## Verified October 12, 2026 resolver failure and separated follow-up

The actual probe run [#38215586235](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38215586235) **failed before compilation**: `matrix-sdk-store-encryption 0.19.1` needs `blake3 ^1.8.7` while `starlark 0.14.2` fixes `blake3 =1.8.2`. Cargo cannot produce the joint lock. This is a true workspace-wide solver conflict, not a Matrix unit-test failure.

The updated workflow retains that strict workspace probe and separately
resolves a **disposable, nonworkspace Matrix 0.19.1 dependency graph** using
the upstream crate's Rust 1.96 compiler. That isolated run records the
transitive crypto version and presence of `anymap2`, while comparing the SDK
declared MSRV against the **unchanged production Rust 1.95.0** from
`codex-rs/rust-toolchain.toml`. Isolation is diagnostic only; it is explicitly
red whenever any of MSRV incompatibility, unmaintained `anymap2`, or
unpatched crypto exists.

Other known lock blocker: global cargo-deny also reported yanked
`chacha20 0.10.0` through the existing `rand` graph; replacing an SDK does
not by itself establish an accepted lock or transitive security compliance.
No advisory exceptions, policy suppression, fake lockfiles, production key
material or release authorization are added.

Remediation must use a maintainer-reviewed compatible Starlark/BLAKE3 policy,
a supported Matrix SDK without `anymap2`, a coordinated toolchain and
Matrix-sqlite migration, then a **real** pinned Cargo.lock with native
encrypted Matrix tests and full cross-platform blocking-ci.
