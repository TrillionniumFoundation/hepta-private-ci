# Inactive publication outbox model

Baseline: `5f724cca24cb9b43986f868c9f7b52c3507119b6`.

This stage adds a pure source-side transition model in hepta-contracts. Its
private fields preserve the original primary and acknowledgement and at most one
sticky qualification conflict and acknowledgement. A transition returns a new
candidate; conflicts do not mutate the prior value. A late downgrade does not
rewrite provider outcome or the original acknowledgement. Delivery facts do not
release actual capacity or authorize output.

Untrusted JSON hydration uses `RunBridgeOutboxV1::from_json_slice` with a 16KiB
input ceiling. Its visitor also limits maps to 16 entries, keys to 64 bytes,
strings to 512 bytes, and objects to three levels. Positional arrays, duplicate
keys, unknown fields, missing nullable fields and inconsistent acknowledgement
relationships fail closed. Direct serde is only for caller-bounded inputs; its
visitor cannot bound an external parser's input allocation.

## Verification

- 15 focused tests passed: eight new outbox tests and seven existing bridge DTO
  tests; 174 unrelated tests were filtered. No AuthBus qualification was run.
- Tests cover early notice ACK refusal without losing the notice, both orders of
  downgrade versus primary ACK, pending and completed snapshot reconstruction,
  immutable duplicate delivery, conflicting ACK/notice atomicity, invalid owner
  revision ordering, malformed object shapes and bounded decoding.
- Strict contracts library Clippy passed. Repository `just fix` also inspects
  tests and reported 16 inherited final-use/test warnings; its unrelated automatic
  edits were restored. Strict whole-test lint is not claimed or suppressed.
- `just fmt` completed; 53 unrelated inherited Python formatting changes were
  restored. Diff whitespace check passed.
- Parent independent source review found a material intermediate JSON allocation
  bound gap. The explicit byte boundary and visitor limits closed that finding;
  final source re-review found no other concrete blocker. This is not a second
  independent Rust execution.

## Completion boundary

No production caller selects this model. There is no journal integration, atomic
write/sync/ACK implementation, authenticated destination capability, Agentd schema
or method activation, legacy response-shape change, or actual capacity mutation.
Serialization round trips are not process-crash durability evidence. The caller
must authorize source facts and persist a returned candidate before adoption.
Acknowledgement data alone is not authority or proof of persistent delivery.

The destination must still implement typed bound dispatch/abort/primary/notice
methods. A notice arriving before its primary must be rejected for retry without
losing the source obligation. The source model's early-ACK test only checks its
own side of this ordering; it is not a destination wire test. Integration must
retain actual provider truth, durable normalized qualification and immutable
primary history separately, recheck final-use authority, and prohibit replayed
physical sends. Atomic ingress fencing and Windows support remain separate open
work. Full design: ../typed-bridge-design-20261002/DESIGN.md.

Exact-head hosted checks are pending. This source model does not add an executable
owner to any implementation map or change existing false qualification gates.
