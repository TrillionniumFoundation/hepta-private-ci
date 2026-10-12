# Matrix SDK advisory remediation feasibility (isolated, no production changes)

This branch is an intentionally read-only probe based on ae12ba67a8a82c3d60b954aebea5662003df6cd8, leaving
Neuron PR #1494 at its exact SHA to finish heavyweight blocking-ci. The
ephemeral GitHub Actions runner tests Matrix SDK 0.19.1 using Rust 1.96
without committing a Cargo.toml, Cargo.lock, vendored SQLite or dependency
change. It retains actual Cargo resolver/compiler output, dependency tree,
unapplied patch and an explicit summary.json with safe_to_merge=false.

The observed original blocking-ci #38205575679 fails because
matrix-sdk-crypto 0.18.0 has RUSTSEC-2026-0318 (patched in >=0.19.0)
and matrix-sdk 0.18.0 includes unmaintained anymap2 0.13.0
(RUSTSEC-2026-0319). Upstream matrix-sdk 0.19.1 still lists anymap2,
so upgrading alone cannot clear both advisories.

Additional incompatibilities must be checked: Hepta pins Rust 1.95 while
upstream Matrix 0.19.1 requires Rust 1.96, and Hepta currently uses a
vendored matrix-sdk-sqlite 0.18.0 patch to align libsqlite3-sys with SQLx.
The actual resolver/compile results, not this document, decide feasibility.
No RUSTSEC ignore or blanket downgrade, no production grant, no model
deployment. An Actions success means only that diagnostics were retained.
