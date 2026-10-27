# Starlark 0.14.2 manifest compatibility port

The upstream release pins `blake3` to `=1.8.2`. Matrix SDK store encryption
0.19.1 requires `blake3 ^1.8.7`; Cargo cannot resolve both requirements in
one compatible-version dependency graph.

This directory retains all 685 files from the official Starlark 0.14.2
crate. The only change to an upstream file is the normalized
`Cargo.toml` dependency pin, `blake3 =1.8.2` to `=1.8.7`.
All 489 Rust files, including `build.rs`, are byte-identical to upstream.
The original `Cargo.toml.orig`, package features, target dependencies,
dev dependencies, and all four requested BLAKE3 features are retained.

The official archive SHA256 is
`9062e866918dc4c9701c98ac99f7f4fa9e4b3b4edce306e147393bc75458c4fc`.
Its VCS source is `facebook/starlark-rust` commit
`0c8d107ab963362ba47ee3ab9e0173bc39bd101d`. `HEPTA_PROVENANCE.json`
records the complete upstream file inventory and the single manifest delta.
The Apache 2.0 license is preserved from that immutable source commit.

Only `src/pagable/heap_ref_id.rs` calls BLAKE3. It wraps the stable
inherent `Hasher::default`, `update`, `finalize`, and `Hash::as_bytes`
methods in the existing `std::hash::Hasher` implementation. It does not
use the optional `digest` traits whose preview API changed in BLAKE3
1.8.4. The retained feature tuple is `default`, `rayon`, `std`, and
`traits-preview`; no feature is disabled to bypass resolution.

The candidate also selects the official `pagable 0.4.2` and
`pagable_derive 0.4.2` patch releases. `pagable 0.4.1` had the same
`=1.8.2` pin; its maintained successor accepts `blake3 ^1.8` and retains
the four features. Both published packages retain all Rust source bytes
from their previous versions. They remain registry dependencies rather
than another local port. The existing `pagable ^0.4.1` dependency in this
manifest already permits that patch release.

The Bazel library preserves the upstream build script's compiler-channel
detection and makes the complete package available to compile-time file
access. The first-party Cargo dependency requests no Starlark features,
and the explicit Bazel library uses the same empty feature set. It does
not instantiate upstream dev tests in the production dependency graph.

Source inspection and any small wrapper compatibility probe are distinct
from whole-workspace qualification. The candidate still requires real
Rust 1.96 resolution, first-party exec-policy tests, Bazel build, and the
unchanged full-scope dependency policy scan before promotion.
