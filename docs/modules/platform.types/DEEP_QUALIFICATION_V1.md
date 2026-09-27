# platform.types deep qualification

## Status and claim boundary

This document defines repository-controlled qualification for the authority-free
`platform.types` contract surface and its product-owned strict codecs. It grants
no runtime authority, production activation, independent acceptance, promotion
or release.

A PR source head and its deterministic synthetic merge are different candidates.
Their receipts are not interchangeable. Failed candidates retain diagnostics,
but only a job in which every required outcome succeeds may emit an
authoritative receipt.

## Rust-owned protocol catalog

`codex-rs/hepta-types/src/protocol_catalog_v2.rs` is the typed normative catalog
for protocol IDs, versions, semantic encodings, schema paths, codec owners,
compatibility policy and field tables. Qualification compiles a generator from
the same crate, verifies every referenced executable schema contains each Rust
descriptor field, and emits candidate-bound JSON and Markdown projections.

The projections are included in the candidate document bundle and receipt. They
are not separately editable protocol sources.

## Public API and semver gate

The legacy exact-`pub use` inventory remains an ownership projection. Complete
public API evidence is generated from rustdoc JSON for the base and candidate.
The normalized snapshot covers public modules, types, methods, fields, enum
variants and signatures. Existing-path removals or fingerprint changes fail;
additive paths are reported without mutating every old item through the crate
root.

## Exact Git provenance

Qualification enumerates tracked source, schema, consumer, documentation,
verifier and workflow files. It records the candidate SHA/tree, root tree IDs
and exact blob IDs and rejects a working file whose bytes differ from HEAD.
Committed observation-base metadata therefore cannot stand in for actual
candidate byte identity.

## Strict transport and cross-language conformance

Prompt V2 and Topology V1 use product-owned strict JSON codecs with a 64 KiB raw
bound and depth 16. Unknown fields, duplicate keys, missing required nullable
fields, overlong/non-canonical generation strings and native semantic failures
reject.

Python, JavaScript and Rust consume the same golden vectors and independently
compute the HPTC semantic commitment. The three manifest protocols retain their
existing Rust/Python/Node vector set and strict schemas.

## Deterministic properties and coverage-guided fuzz

`scripts/platform_types_property_checks.py` performs deterministic field
removal, semantic mutation, JSON-order invariance and bounded mutation
properties over the manifest protocols.

A separate pinned `cargo-fuzz` lane runs actual libFuzzer instrumentation over:

- arbitrary HPTC raw bytes through `canonical_validate_v1`;
- arbitrary product JSON bytes through both Prompt V2 and Topology V1 decoders.

The fuzz workspaces and corpora are created in candidate evidence directories so
qualification does not mutate the repository. Runs are bounded and reproducible
as evidence; they are not described as exhaustive proof.

## Toolchain gates

The crate declares Rust 1.95 as its minimum supported version. Deep
qualification checks exact-candidate MSRV build/tests, current native tests and
strict Clippy, and pinned `nightly-2026-09-20` Miri. The same pinned nightly is
used for rustdoc JSON and libFuzzer unless explicitly reviewed and changed.

## Consumer and owner matrix

The consumer lane executes 24 independent checks and preserves every log. It
covers generated bindings, canonical vectors, manifest vectors, Prompt/Topology
wire vectors, product codec tests, complete types/NDU tests, prompt producer and
ledger paths, topology admission, the NDU random-stream owner, Supervisor
external/sensor owners, and strict lint for types, wire and NDU.

No failed command suppresses later diagnostics. Aggregate qualification remains
failed if any command fails.

## Exact-candidate document bundle

The bundle wraps each stable source document with candidate kind, exact commit
and tree, source SHA-256 and explicit non-activation boundary. It also copies the
Rust-generated protocol projections and hashes all protocol, source, owner,
verifier, fuzz and workflow anchors.

## Receipt rule

The receipt is emitted only after these same-candidate outcomes succeed:

1. truth, generated protocol catalog, deterministic properties and consumers;
2. exact Git provenance;
3. rustdoc API/semver comparison;
4. declared MSRV;
5. native tests and strict lint;
6. pinned Miri;
7. bounded coverage-guided fuzz;
8. exact-candidate document bundle.

The receipt hashes each evidence class and preserves the module non-claims.
