# Rama DNS alpha.4 with the maintained Hickory resolver

This directory starts from the published `rama-dns 0.3.0-alpha.4` crate.
The original archive is 24,600 bytes with SHA256
`e340fef2799277e204260b17af01bc23604712092eacd6defe40167f304baed8`,
matching the exact Hepta security-branch Cargo lock at
`52591dba2de2b5bd48bb48cab03f9bef195b141a`. Its Cargo VCS record identifies
upstream Rama commit `4733273a10a791762e2b7727850032b0c9b8536d`.
The original published crate's internal Cargo.lock is omitted here because the
Hepta workspace lock is the build input. The original archive and file hashes
are retained separately as provenance; Cargo.toml.orig is unmodified upstream.
MIT and Apache licenses are exact files from that upstream commit.

## Scope

Only the published Cargo.toml and src/hickory.rs implementation receive
functional changes. The repository's required formatter normalizes the other
original Rust files; their implementations and all existing tests are retained.
The local BUILD.bazel uses the existing codex_rust_crate macro, which includes
the Rust source and sibling test module. No new non-Rust compile-time input is
introduced. The new real DNS tests live in src/hickory_tests.rs.

The manifest selects Hickory resolver 0.26.3 and pins Rama core/net/utils to
the original alpha.4 release. Hickory 0.26.3 declares Rust 1.88 support, and the original Rama alpha.4
manifest declares Rust 1.91. Hepta currently uses Rust 1.96. The original
backport was qualified on Rust 1.95 in PR #2887; that historical toolchain
constraint does not apply to the current candidate. Retaining alpha.4 here
limits the change to the existing DNS dependency edge and its adapter. This
patch does not lower an upstream MSRV declaration or change Hepta's toolchain.

The API adaptation follows Rama's official Hickory migration
`d8ff199a47ec0e034fbf0b8617d8c21890004cf2` (whose Rama root declared Rust 1.93),
TXT update `ada85e5c4f451456fbe3bb355322da0ab7cb954e`, and the final published
Hickory 0.26.3 source. It moves the runtime provider and DNS name imports,
uses the new nameserver groups, propagates fallible resolver construction, and
extracts A/AAAA/TXT data from complete answer records. The final 0.26.3 Record
and TXT APIs expose their data fields; those are used instead of older beta
accessors.

Alpha.4's DnsResolver trait and constructor signatures, global resolver, domain
conversion, chain, overrides and first-party network-proxy/authorization code
are retained. The public Hickory re-export and builder configuration types now
come from Hickory 0.26.3; no first-party network-proxy source consumes those
foreign configuration APIs. Existing infallible constructors retain an initialization error
and return it from all later lookups. They do not panic or silently choose a
different resolver. The existing default system-to-Cloudflare fallback is
preserved; an explicit configuration does not gain a new fallback. The builder
also exposes try_build for callers that need an immediate construction error.

## Required verification

The current candidate must run real Cargo 1.96 resolution and scoped compilation/tests,
then the repository's original `just bazel-lock-update` and
`just bazel-lock-check`. Their actual generated Cargo.lock and MODULE.bazel.lock
must be reviewed and committed. A source-only patch is not security closure.
The existing strict cargo-deny/cargo-audit policy remains in force. Only the two
Hickory exceptions may be removed in both policy files after the frozen
RustSec database and actual graph demonstrate that their affected versions
are absent; no new exception is introduced. The generated graph
must contain Hickory proto/net/resolver 0.26.3 and retain every Rama package on
alpha.4; a remaining 0.25 Hickory path is a failure.

The new tests use real loopback UDP and TCP to exercise CNAME+A, AAAA, segmented
binary TXT and NXDOMAIN through the original, cloned and boxed APIs. Socket
futures share a bounded timeout without detached listener tasks. Initialization
errors are checked through each lookup family. These tests support the adapter
change; upstream advisory remediation is supplied by the real maintained
Hickory implementation and verified dependency graph, not a test-only shim.

Upstream references:

- https://static.crates.io/crates/rama-dns/rama-dns-0.3.0-alpha.4.crate
- https://github.com/plabayo/rama/commit/d8ff199a47ec0e034fbf0b8617d8c21890004cf2
- https://github.com/plabayo/rama/commit/ada85e5c4f451456fbe3bb355322da0ab7cb954e
- https://github.com/hickory-dns/hickory-dns/tree/v0.26.3
- https://rustsec.org/advisories/RUSTSEC-2026-0118.html
- https://rustsec.org/advisories/RUSTSEC-2026-0119.html
