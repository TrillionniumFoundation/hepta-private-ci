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

## Parameter-bundle seam

`CellSplitParameterBundleSetMigrationOwnerV1` binds the migration owner to one
`learning.artifacts` CAS owner per child. The selector supplies the child
bundles and their immutable selected-weight references; the bridge validates
them, stages every CAS append on cloned owners, and swaps the complete owner
set only after all child transforms pass. A receipt or lineage mismatch leaves
every owner head unchanged and lets the existing runtime seam perform the
single rollback/quarantine decision.

The migration journal persists the optional single-lineage bundle owner in the
same hash-chained envelope. `CellParameterBundleOwnerV1::snapshot_wire` and
`reopen_wire` rebuild the CAS chain and replay every receipt, so a stale or
forged acknowledgement cannot seed a reopened owner. Prepared snapshots also
have an HPTA V2 transport DTO (`hepta.runtime.cell-split-snapshot.v1`) with
strict unknown-field rejection and exact generation binding.

This remains a host-local integration seam. A real target host still must
provide independently verified candidate selection, physical CAS durability,
writer lease/stop acknowledgements, restart evidence, and external lifecycle
qualification before any production activation is admissible.
