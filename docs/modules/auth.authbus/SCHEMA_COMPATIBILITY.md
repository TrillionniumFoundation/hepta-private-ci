# auth.authbus schema compatibility

Status: normative migration and rollback contract

## Compatibility dimensions

A release is compatible only when all of the following are compatible:

- SQLite migration set and resulting schema digest;
- authority checkpoint JSON schema and generation semantics;
- signed message, trusted-time and settlement signing domains;
- issuer-registry file schema;
- policy, quota, reservation and settlement enum/state semantics;
- product caller protocol and recovery receipts.

Source compatibility alone is insufficient.

## SQLite migration policy

1. Migrations are append-only and have immutable contents after merge.
2. A changed historical migration is a release blocker even if the final schema
   appears equivalent.
3. Every open performs pre-migration integrity checks, migrations, exact schema
   verification, post-migration `quick_check` and `foreign_key_check`.
4. New columns first appear as nullable or with a deterministic default that old
   rows can satisfy. Backfill and enforcement are separate migrations when the
   data set can be non-trivial.
5. Destructive table/column removal requires an export/verification release,
   one full retention window and an explicit activation decision.
6. State-machine values are never reinterpreted. A new meaning receives a new
   enum value or schema version.
7. Index creation and backfill are bounded and tested against the maximum
   supported database size.

## Version support matrix

| Component | Reader rule | Writer rule |
|---|---|---|
| SQLite schema | current release reads the immediately previous qualified schema only through migrations | only current schema writes |
| Checkpoint document | reject unknown schema version and unknown fields | write current schema version only |
| Issuer registry | reject unknown top-level/record fields in product parsers | atomic current-version publication only |
| Signed message | exact versioned domain | signer emits current domain only |
| Trusted-time attestation | exact versioned domain and monotonic source revision | signer emits current domain only |
| Settlement evidence | exact versioned domain and exact reservation/operation binding | signer emits current domain only |
| Qualification receipt | reader may retain historical receipts | current workflow writes current receipt schema |

There is no best-effort downgrade parser for security-sensitive records.

## Checkpoint compatibility

Checkpoint schema version, owner ID, generation and digest are authoritative.
An upgrade may preserve the current checkpoint format only when digest semantics
are unchanged. If frontier serialization changes:

1. introduce a new checkpoint schema version;
2. provide an offline converter that takes a verified database/checkpoint pair;
3. emit old/new digests and a conversion receipt;
4. qualify interruption before write, after file fsync, after rename and after
   parent-directory fsync;
5. forbid mixed-version active/standby startup.

A newer checkpoint is not downgraded in place.

## Signing-domain compatibility

Canonical signing bytes are protocol. Field order, length framing, enum encoding
and domain separator are immutable within a version. Adding or changing a field
requires a new domain version and explicit dual-read/single-write transition.
Signatures from one purpose or version must fail verification in every other
purpose/version.

## Issuer-registry compatibility

The production registry permits either the documented single-record profile or a
bounded `issuers` array profile. Every record requires issuer ID, non-zero epoch,
fixed-width Ed25519 public key and explicit revoked state. Product-specific
metadata may be present only when its parser uses `deny_unknown_fields` and the
verified AuthBus loader selects only the exact issuer/epoch record.

Registry migrations use atomic replacement and a monotonic publication revision.
Consumers never synthesize missing fields.

## Rollback policy

Application rollback is supported only when the older binary is known to read
the current schema and protocol versions without losing semantics. Otherwise:

- restore the last database/checkpoint pair written by the older release;
- preserve the newer pair for audit;
- reconcile externally visible provider effects before resuming;
- never run down-migrations against the sole production copy.

Rollback must not reduce checkpoint generation, policy/issuer revision, trusted
source revision or replay frontier.

## Migration qualification

Every release candidate must test:

- clean database to current schema;
- each supported previous schema to current;
- restart at every migration boundary;
- migration with maximum bounded rows;
- disk-full and I/O error during migration;
- post-migration schema and foreign-key verification;
- old checkpoint/current database and current checkpoint/old database rejection;
- current binary against old/new registry and signing versions according to the
  matrix;
- backup/restore of the database and checkpoint as one pair.

The receipt records migration file digests, final schema digest, source tree and
artifact digest.
