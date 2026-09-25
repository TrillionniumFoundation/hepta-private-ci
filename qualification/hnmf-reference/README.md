# HNMF algorithm qualification reference

This package is an **algorithm oracle**, not the owner of cognitive/memory
contract structure.

Canonical HNMF V1 contracts and canonical JSON wire semantics live only in
`codex-rs/hepta-cognitive-types` (`hnmf.rs`, `hnmf_learning.rs`,
`wire.rs`). Values in this package are deliberately named `Reference*` and
represent algorithm-local feature/state projections used to exercise bounded
candidate generation, recurrent settling, sparse competition, contradiction
handling, replay, plasticity and forgetting. Modality, privacy, engram-population
and synapse-relation taxonomies are re-exported directly from the production
crate; event projections can be built only through the canonical
`MemoryEventV1` adapter when exercising the contract boundary.

A `Reference*` value must never be serialized or registered as a production
protocol, passed as a substitute for a canonical V1 contract, or used to mint
authority. Cross-language contract conformance is checked separately by
`qualification/cognitive-types-v1/verify_vectors.py`.
