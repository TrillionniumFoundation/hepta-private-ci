# platform.types current implementation

## Current executable contract

`codex-rs/hepta-types` is an authority-free Rust primitive library. Its public
surface includes bounded bytes/text, `StableId`, `Digest32`, nonzero generation
and revision types, fixed-point probability values, numeric profiles, numeric
signals and `rescale_signal`. The crate forbids unsafe code and owns no clock,
network, filesystem, credential, process-global registry or durable writer.

Identifiers, digests, revisions and authority-bearing fences are exact values.
Numeric conversion is limited to registered native profiles, checked integer
arithmetic and the target profile's explicit rounding rule. Conversion receipts
have deny-all authority and do not certify statistical correctness or production
admission.

## Target-only design

Cross-language generated bindings and a broader unit/profile registry may be
added only through versioned contracts and golden encodings. They are not
current capabilities merely because downstream modules consume shared types.

## Known limits and non-claims

The library is not a schema registry, state store, compatibility daemon,
authority issuer or runtime. Rust type equality does not by itself establish a
stable external wire representation. Any cross-language claim requires a
separately frozen encoding and independent vectors.

## Verification

The Lane A verifier binds the exported symbols to `src/lib.rs` and the numeric
rules to `NUMERIC_SIGNAL_CONVERSION.md`. Native tests remain responsible for
bounds, overflow, rounding, digest stability and invalid-profile rejection.
