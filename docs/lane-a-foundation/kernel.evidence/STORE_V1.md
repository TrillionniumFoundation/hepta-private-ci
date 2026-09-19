# Kernel evidence SQLite store V1

## Physical lineage

The current database filename is `hepta_evidence_2.sqlite`. Its migration set
is ordered and checksum-bound:

1. `0001_governance.sql`
2. `0002_provider_evidence.sql`
3. `0003_provider_host_binding.sql`
4. `0004_memory_mutation_shadow.sql`
5. `0005_channel_ingress_evidence.sql`
6. `0006_provider_ephemeral_input.sql`
7. `0007_provider_effect_evidence.sql`
8. `0008_provider_effect_ack_source.sql`
9. `0009_authbus_replay.sql`
10. `0010_authbus_outbox.sql`
11. `0011_qualification_evidence.sql`

Unknown, missing, incomplete, failed or checksum-mismatched migration rows
cause store open to **fail closed**. They are never treated as an empty,
current or repairable evidence lineage.

## Core integrity model

Governance decisions and receipts use unique identities, phase constraints,
payload hashes, foreign keys and update/delete denial triggers. Provider effect
intent, acknowledgement and uncertainty rows are separate immutable facts.
Transport acceptance is not inferred as terminal application; uncertainty is a
first-class record.

Qualification evidence is append-only and stores canonical envelope/issuer
JSON, exact candidate commit/tree, payload digest, predecessor/revocation
lineage, authenticated issuer material, a record digest and a global hash-chain
link. `IndependentDecisionReceiptV1` has a typed immutable projection whose
payload digest must equal the authoritative qualification evidence payload
digest. Reopen re-verifies canonical encoding, Ed25519 signatures, typed
projection agreement and the chain frontier.

`open` performs SQLite quick-check, migrations and current-schema validation.
`open_existing_read_only` requires an existing complete lineage and never
creates or migrates it.

## External checkpoint and rollback detection

Migration `0011` creates one immutable random store instance identity and one immutable provisioned qualification trust policy. The trust policy must be provisioned before the first qualification receipt and cannot be replaced in place.
`export_checkpoint` returns that identity, the provisioned trust-policy digest, receipt count, maximum qualification sequence and the chain digest at that sequence.

`verify_external_checkpoint` fails closed when:

- a replacement database has a different store instance identity;
- the current database is behind the retained receipt count or sequence;
- the retained sequence exists but its chain digest differs.

A retained checkpoint may be older than the live store: later append-only
evidence is allowed as long as the retained frontier still matches. This makes
the checkpoint monotonic without requiring every read to carry the latest
generation.

The checkpoint is useful only when retained independently from the SQLite
database. Copying/restoring the database and its checkpoint together does not
provide anti-rollback protection.

## Production writer boundary

`hepta-evidence-writer` is the named checkpoint-guarded writer:

- `bootstrap-trust-policy` provisions the immutable trust policy on an empty qualification chain and emits the first checkpoint bound to that policy;
- `signing-bytes` emits the canonical envelope bytes an issuer signs;
- `admit` verifies the prior checkpoint, trust policy and Ed25519 issuer
  signature before append, then emits a new checkpoint;
- `prepare-independent` produces `IndependentDecisionReceiptV1`, the
  evidence envelope and exact signing bytes without signing on behalf of the
  reviewer;
- `append-independent` verifies the independent signature, appends the typed
  receipt atomically and emits a new checkpoint plus terminal receipt;
- `verify-checkpoint` performs read-only rollback/replacement verification.

Checkpoint outputs are create-new files rather than in-place rewrites. The
operator owns durable rotation/retention and may place generations in WORM or
another independently protected store.

## Concurrency

A transaction encloses each logical append and content-equivalence check.
Qualification evidence and provider-effect append boundaries use
`BEGIN IMMEDIATE` where a unique append/hash-chain frontier must be serialized.
Provider-effect operations also use one process-local mutex for clones of one
store. This mutex does not serialize other processes or independent opens.

AuthBus signed admission uses `BEGIN IMMEDIATE` to serialize replay and
capacity checks across independent handles. Its sequence update commits before
a receipt returns. `enqueue_authbus_message` replaces direct admission for
durable delivery: one transaction advances that replay registry and inserts
the immutable message. Its fenced lease/retry/ack operations redeliver
messages, never unknown provider effects. See
`hepta-authbus/SIGNED_ADMISSION.md` for retention and delivery semantics.

## Backup, restore and retention requirements

A production operator must:

- copy a transactionally consistent database;
- retain the last accepted checkpoint in an independently protected location;
- verify the checkpoint before admitting restored evidence;
- verify migration checksums, qualification signatures/hash chain and foreign
  keys after restore;
- reject restoration behind the independently retained frontier;
- retain supersession/revocation lineage;
- never delete rows in a way that turns missing evidence into positive proof;
- retain exact-candidate CI and independent-review receipts according to the
  qualification retention policy.

The repository implements checkpoint generation/verification, not the external
storage service, WORM policy or operator ceremony itself.
