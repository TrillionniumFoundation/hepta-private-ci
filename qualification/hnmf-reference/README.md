# HNMF deterministic reference runtime

This standalone Rust crate is a qualification-only executable specification for HNMF algorithms. It has no external dependencies and remains deliberately excluded from the main Codex workspace. Canonical V1 cognitive/memory contracts are now owned by `codex-rs/hepta-cognitive-types`; the unversioned structs in this crate are internal deterministic reference-model state only and are not wire schemas, persistence schemas, or a second contract owner.

It implements:

- nine modality classes and seven functional engram populations;
- immutable memory events with source, privacy, validity, and tombstone gates;
- bounded candidate generation over semantic, modality, seed, and associative evidence;
- recurrent sparse activation with per-population competition and inhibitory/contradictory edges;
- adaptive-threshold homeostasis and bounded eligibility traces;
- outcome-derived low-dimensional modulation;
- candidate-only weight and threshold plasticity with exact predecessor generation;
- replay selection with source-bucket quotas;
- add/split/merge/retire/rewire topology proposals that cannot activate themselves;
- source-driven forgetting that retires unsupported nodes and synapses;
- deterministic receipts containing no raw source payload.

The crate exposes no filesystem, network, model, provider, tool, secret, merge, promotion, or release capability. It is not a biological brain simulation and it does not establish production or longitudinal claims.
