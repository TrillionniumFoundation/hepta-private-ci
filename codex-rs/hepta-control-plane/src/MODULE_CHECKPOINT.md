# Runtime module registry checkpoint V1

This bounded library encodes **recovery bookkeeping** for a host to persist. It does
not commit a file, provide a journal transaction, load code, migrate product
state, select a daemon generation, or activate a production writer.

`checkpoint()` includes retained ABI/lifecycle/evidence rows, all selected writer
reservations (including quiescing and quarantined generations), and first/greatest
admitted generations even after every payload for an identity is compacted.
`checkpoint_bytes()` provides a deterministic encoding. Restore validates bounds,
ABI and predecessor consistency, duplicate identities, evidence shape, fences,
selected lifecycle membership and exclusive authoritative domains before returning
a new registry. A failure never mutates a caller's live registry.

Restore checks each published handoff witness against both the successor
and its retained predecessor. A successor that declares itself stateless does
not erase the predecessor's state, authoritative domains or external effects.
Registered, shadow and canary candidates do not need a handoff before publication;
genuinely stateless replacement and bootstrap retain their existing fast paths.

## Trust and current history

Both restore entry points require `expected_current_checkpoint_digest`. The host
must supply this from its separately authenticated, current durable owner state,
not copy it from a backup. The library only compares that value: it does **not**
authenticate it, durably advance it, observe freshness or detect two caller-supplied
stale values. A stale valid checkpoint fails against the actual current root,
including when the newer checkpoint differs only by quarantine or retirement.
Current immutable selection, revocation/deletion history and writer leases stay
with their existing owners and must be reconciled before dispatch or effects.
No checkpoint checksum or evidence digest grants authority.

`Quarantined` historically represents both unselected candidates and selected
writers. V1 retains that representation; the reservation list and independently
current digest bind which kind it is. Lifecycle alone cannot recover a missing
bootstrap-quarantine reservation. A self-rehashed backup is never a trusted root.

## Encoding and compatibility

The bytes are the exact canonical checksum preimage defined in PR1303 commit
`9d3c9f5bc33bf58a8c4afa77696956eaa6d14f4b`, followed by its 32-byte SHA-256 digest.
That source had no byte decoder or deployed storage format. The two frozen
`fixtures/pr1303_*_v1.bin` fixtures reconstruct its active-successor and compacted
retirement examples; they test historical digest interpretation, not a claimed
production backup migration. Changing this schema requires a distinct version.
Decoding historical state does not reauthorize unsafe digest-only rollback:
stateful restoration retains its original bytes and generations, while rollback
still requires the current owner's real state-preserving handoff. The stateless
emergency rollback and its full-capacity checkpoint remain supported.

The preimage starts with ASCII `hepta.runtime-module-registry-checkpoint.v1` and
NUL. Counts, UTF-8 ID byte lengths and generations are big-endian u64. Digests
are 32 raw bytes; option tags are 0/1 followed by the value when present. Each
list has its count followed by elements. Top-level lists are records sorted by
(module ID, generation), reservations sorted by module ID, and fences sorted by
module ID. ABI fields and record evidence follow Rust declaration order; state
class tags are Stateless=0, Stateful=1, ExternalStateful=2; lifecycle tags are
Registered=0, Shadow=1, Canary=2, Active=3, Quiescing=4, Retired=5, Quarantined=6.
Domain/effect sets are ascending unique IDs. Vector order remains significant.
Unknown tags/versions, noncanonical ordering, duplicate sets, trailing bytes,
truncation and oversized declarations fail closed.

The byte limit is 20 MiB, sufficient for 513 retained rows at maximum ABI bounds,
128 reservations and 4,096 fences. Counts are checked before allocation and IDs
before string allocation. The extra retained row permits the existing emergency
rollback path at full working-set capacity; ordinary pending capacity remains
128. The lifetime 4,096-identity cap does not reclaim retired fences. Existing
identities can advance at the cap, but admitting identity 4,097 fails atomically.
A future fence-history migration requires a separately reviewed owner protocol.
