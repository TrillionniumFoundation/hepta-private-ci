# HNMF multimodal contract reference

This qualification crate no longer owns a parallel contract model. It is a
compatibility façade over `codex-hepta-cognitive-types::hnmf_v1`, which is the
single canonical Rust/JSON owner for HNMF event, span and related cognitive
contracts.

The crate retains only qualification aliases and negative-authority checks. New
contract fields, validation rules, canonical JSON, digests and version changes
must be implemented in `codex-rs/hepta-cognitive-types` first.
