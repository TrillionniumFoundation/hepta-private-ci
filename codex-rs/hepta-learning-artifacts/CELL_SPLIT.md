# Cell split artifact owner

`CellParameterBundleManifestV1` is the child artifact manifest produced from a
validated `CellSplitV1` plan. It binds child identity, parent artifact and
bundle digests, generation, scope, definition, lineage, task objective,
compatibility, inheritance binding, payload size and the split evaluation
subject. The manifest accepts a host-supplied payload digest and never treats a
digest alone as proof that bytes exist.

`CellArtifactPublicationV1` is a fenced, all-or-nothing publication seam:

1. `begin` verifies the parent parameters artifact, exact successor generation,
   child identities and the pre-evaluation split subject digest.
2. The host creates each CAS file exclusively. `persist_payload` writes and
   syncs actual bytes, then returns a `CellArtifactCasReceiptV1` only when the
   digest and encoded size match the child manifest.
3. `record_payloads_durable` requires the complete child set and one operation
   fence. A missing, duplicated, stale or mismatched receipt leaves the
   transaction in `Prepared`.
4. `commit_registry` appends all child records to a cloned `ArtifactRegistry`
   and replaces the caller only after every append succeeds. A stale registry
   head or one failed child leaves the original registry unchanged.
5. `record_registry_durable` requires the exact snapshot receipt and current
   head witness from the existing artifact owner/storage path before the
   transaction becomes `RegistryDurable`; only then is `acknowledge` allowed.
6. `quarantine_children` stages all child quarantine events together, while
   `rollback` points back to the immutable parent predecessor. The parent is
   never silently revoked by this owner.

The compatibility projection into the old V1 registry retains the parent's
objective class because that registry enforces objective equality across a
lineage. The complete child task objective remains in the typed manifest. A
heterogeneous-objective split therefore needs the future typed sidecar registry
before it can be promoted through the old V1 index.

Filesystem writer leases, signed CURRENT witnesses, containing-directory sync,
multi-file atomic rename and target-host reopen evidence remain external host
responsibilities. The receipts are explicit inputs to the owner and are not
manufactured by tests.
