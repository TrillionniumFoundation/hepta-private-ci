# CellSplit migration owner

`cell_split.rs` is the small state-owner implementation behind the existing
`OrganStateMigrationV1` runtime seam. It accepts an already committed parent
checkpoint and a bounded, independently selected candidate list. It prepares
all children before publishing any child state.

The parent recurrent state, eligibility state, optimizer state, cache and
in-flight message inventory are included in the snapshot. The snapshot refuses
to start while messages remain in flight, and each child must return the exact
parent selected-weight digest plus a candidate-generation-bound cache and
message fence. The owner never changes the selected digest and has no selected
child or activation field.

Persistent owners use a logically append-only JSON journal envelope with a
hash-chain head and a witness digest. Each envelope is replaced atomically
after writing a temporary file, calling `sync_all`, and renaming. A stale
reopen or writer uses compare-and-swap on the journal head. A prepared,
migrating or failed envelope is quarantined on restart; it is never inferred to
have committed. Child failure leaves the predecessor available for the seam's
rollback callback. Rollback restores the complete parent state, while an
uncertain rollback quarantines the owner.

This is a deterministic state-transfer reference. It does not execute a model,
publish topology, select candidates, or provide target-host durability evidence.
