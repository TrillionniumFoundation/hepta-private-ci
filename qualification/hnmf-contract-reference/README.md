# HNMF canonical-contract conformance reference

This standalone, dependency-free Rust crate is qualification-only. It defines **no**
cognitive or memory protocol structs of its own.

The single canonical Rust/JSON owner is
`codex-rs/hepta-cognitive-types`. This package compile-time-binds that production
source together with `docs/hnmf/HNMF.json`,
`docs/contracts/PROTOCOL_SCHEMAS.json`, and
`docs/modules/cognitive.types/PORT_SCHEMAS.json`, then verifies that the twelve
HNMF V1 protocols, strict canonical JSON invariants, CTYPE-01 through CTYPE-04,
and the memory/learning topology namespace split remain closed.

Algorithmic HNMF qualification remains in `qualification/hnmf-reference`; its
unversioned runtime structs are internal reference-model state, not canonical
wire contracts and carry no production/effect/selection authority.
