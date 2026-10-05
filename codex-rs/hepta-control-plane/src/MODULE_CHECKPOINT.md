# Runtime module registry checkpoint V1

This bounded library captures **recovery bookkeeping** for a host to own. It does
not commit a file, provide a journal transaction, load code, migrate product
state, select a daemon generation, or activate a production writer.

`checkpoint()` includes retained ABI/lifecycle/evidence rows, all selected writer
reservations (including quiescing and quarantined generations), and first/greatest
admitted generations even after every payload for an identity is compacted.
Restore validates bounds,
ABI and predecessor consistency, duplicate identities, evidence shape, fences,
selected lifecycle membership and exclusive authoritative domains before returning
a new registry. A failure never mutates a caller's live registry.

## Trust and current history

The restore entry point requires `expected_current_checkpoint_digest`. The host
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
