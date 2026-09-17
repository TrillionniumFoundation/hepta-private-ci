# Immutable artifact storage boundary

This storage boundary covers the immutable V1 artifact registry, candidate payloads,
current-head witnesses, durable withdrawal/lifecycle authority snapshots and the
host-facing publication receipt contract. It is not a runtime selector, deployment
service or learning-loop executor.

## 1. Create-only artifact files

The stable artifact writer capability is `CreateOnlyArtifactFile`. Its
`create(path)` constructor opens the final path component with
`OpenOptions::create_new(true)`, read/write access and Unix mode `0600` (subject
to a more restrictive umask). Existing files, empty files and symbolic links are
never overwritten.

The public stable storage operations are:

```text
write_registry_snapshot(CreateOnlyArtifactFile, &ArtifactRegistry, Digest32)
read_registry_snapshot(File, RegistrySnapshotReceipt)
write_candidate_payload(CreateOnlyArtifactFile, &ArtifactRegistry, &StableId, &[u8])
read_candidate_payload(File, &ArtifactRegistry, &StableId)
write_registry_head_witness(CreateOnlyArtifactFile, &RegistryHeadWitnessV1, &RegistryHeadRequirementV1, Digest32)
read_registry_head_witness(File, RegistryHeadWitnessReceipt, &RegistryHeadRequirementV1)
```

`write_registry_snapshot` writes one immutable registry snapshot and syncs the file
before returning. Readback requires an independently retained
`RegistrySnapshotReceipt`, verifies exact length and digest, then rebuilds the
registry through normal semantic validation. No repair, old-snapshot fallback or
selected-pointer discovery occurs inside the reader.

The V1 snapshot encoding is `HEPTAR01`. The current-head witness encoding is
`HEPTAH01` and is bounded to 4 KiB. Candidate payloads are bounded to 64 MiB and
must match the currently eligible manifest's exact length/content digest.

## 2. Durable withdrawal and lifecycle authority files

`CreateOnlyAuthorityFile` applies the same create-new principle to the two authority
state machines that must survive process restart:

```text
write_withdrawal_registry_snapshot(CreateOnlyAuthorityFile, &DatasetWithdrawalRegistry, &WithdrawalAuthorityDomainV1)
read_withdrawal_registry_snapshot(File, AuthoritySnapshotReceiptV1, &WithdrawalAuthorityDomainV1)

write_lifecycle_journal_snapshot(CreateOnlyAuthorityFile, &ArtifactLifecycleJournalV2, Digest32)
read_lifecycle_journal_snapshot(File, AuthoritySnapshotReceiptV1, Digest32, now)
```

The current binary magics are:

- `HPTWDR01` for dataset-withdrawal state;
- `HPTLCJ02` for lifecycle state.

Each file is bounded to 64 MiB and at most 1,000,000 semantic records.
`AuthoritySnapshotReceiptV1` independently binds snapshot kind, authority/scope
binding digest, semantic head, complete file digest, record count and encoded byte
count. The receipt is deny-all authority.

Readback verifies exact length/file digest, bounded decode, no trailing bytes,
semantic replay and exact reconstructed head. Withdrawal files are bound to an
explicit registry/scope/authority domain. Lifecycle replay validates historical
records at their recorded occurrence time, so a credential that expires after a
valid event does not make durable history unrecoverable. Fresh appends still
require current actor validity.

## 3. Publication transaction boundary

Durable files are individually immutable; three successful file syncs are not a
filesystem transaction. `ArtifactPublicationTransactionV1` therefore makes the
host commit rule explicit.

A publication plan binds:

- publication scope/generation/predecessor commit;
- V2 manifest and V3 admission digest;
- V1 registry binding/head/count;
- withdrawal authority binding/head/count;
- lifecycle binding/head/count.

The transaction accepts only exact durable receipts for those three state files.
`seal()` fails until every planned receipt has been acknowledged. The resulting
`ArtifactPublicationCommitV1` hashes the plan plus each file binding, semantic
head, file digest, record count and encoded length.

The product host MUST:

1. hold its exclusive writer fence;
2. revalidate the V3 admission against the current withdrawal domain/head;
3. persist and sync the three planned immutable state files;
4. acknowledge the exact receipts and seal/verify the publication commit;
5. persist and sync that commit in the host generation record;
6. only then atomically publish the independently authenticated current-generation
   pointer;
7. sync the containing directory where required by the target filesystem.

A crash before current-pointer publication leaves the old current generation
authoritative. Unreferenced immutable files are orphans, not committed state.

## 4. Failure and retry semantics

Validation can fail after create-new reserves a path but before payload bytes are
written. That can leave a zero-length orphan. A write/sync failure is
`Indeterminate`; the caller must reconcile the exact target and expected digest
and must not truncate, overwrite or silently adopt it.

Lock contention returns `Busy`. Observed nonzero interference before a guarded
write returns `Indeterminate`. Readers reject size drift, digest drift, trailing
bytes and semantic replay mismatch.

Idempotence belongs to semantic record identity and external generation planning;
it is never implemented by overwriting an old file path.

## 5. Enrolled-root path containment and orphan cleanup

`ArtifactStorageAdminV1` provides a narrow administrative surface for a host that
has enrolled a canonical storage root.

`resolve(relative)` accepts only non-empty relative paths composed exclusively of
normal components. Absolute paths, `.`/`..`, root components and platform prefix
components are rejected. The existing parent directory is canonicalized and must
remain under the enrolled root.

`create_artifact(relative)` resolves through that boundary before obtaining a
`CreateOnlyArtifactFile`.

`cleanup_zero_length_orphan(relative)` may remove only a regular, non-symlink,
zero-length file. Non-empty files, directories, symlinks and special files are
left untouched. After removal the containing directory is synced.

There is intentionally no recursive delete, wildcard cleanup or "delete anything
unreferenced" API.

The host must still protect enrolled ancestor directories from concurrent
replacement. This crate uses safe Rust and does not claim an OS-independent
`openat2`/descriptor-walk guarantee for hostile ancestor mutation.

## 6. Host trust boundary

The host owns:

- authentication of signer/credential evidence;
- authenticated current-generation selection;
- writer fencing;
- trusted/enrolled parent directories and permissions;
- containing-directory durability;
- storage encryption and quota;
- retention, backup deletion and physical erasure;
- reconciliation policy for orphan immutable files;
- target-filesystem/power-loss qualification;
- runtime selection, activation, rollback and release.

A valid old immutable snapshot plus its old receipt is not proof of currentness.
The caller must supply current head/generation/authority requirements from an
independent trusted channel.

## 7. Verification expectations

Regression coverage includes:

- real-file registry reopen and semantic replay;
- current-head witness rollback/predecessor checks;
- candidate length/content/revocation checks;
- create-new collision and lock contention;
- withdrawal durable roundtrip and exact head reconstruction;
- lifecycle durable roundtrip after historical actor credential expiry;
- publication transaction refusal after partial durability;
- publication commit binding of all durable receipts;
- relative-path traversal rejection;
- zero-length orphan cleanup while preserving non-empty files.

Exact-head compilation/tests, strict `clippy -D warnings`, formatting, clean source
and pull-request synthetic-merge qualification remain mandatory before claiming
source closure.

Nothing in this storage layer grants selection, activation, promotion or release
authority.
