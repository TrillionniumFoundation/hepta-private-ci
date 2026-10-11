# HNMF contract qualification shim

This package deliberately defines **no cognitive/memory contract structs**.

The single canonical Rust source for HNMF V1 cognitive contracts is
`codex-rs/hepta-cognitive-types`:

- `src/hnmf.rs` — multimodal span/event contracts;
- `src/hnmf_learning.rs` — engram/recall/replay/plasticity/topology/forget contracts;
- `src/wire.rs` — strict canonical JSON V1 encoding.

This crate compiles against and re-exports those production V1 contract types;
it defines no competing contract structs. It remains an executable
negative-authority/ownership fixture and compile-time ownership check. Algorithm
qualification lives in `qualification/hnmf-reference`; cross-language wire
vectors live in `qualification/cognitive-types-v1`.
