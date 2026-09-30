# SQLite owner and registered runtime: development contract

This guide describes the implemented library boundary. The canonical
`MODULE_MANIFEST_V1.json` and exact-source receipts determine qualification;
this document grants no deployment or acceptance authority.

## Placement and ownership

`secrets.heptabao` owns secret metadata and lease history. HeptaBao supplies
the secret value; `kernel.authority` owns final-use grants, approvals and
revocation; `auth.authbus` owns policy decisions, quota reservations and
settlements. The adapter stores references, digests and immutable outcomes.
It does not persist provider tokens or raw secret values.

The supported provider operation remains an exact-version KV-v2 read. Lease
issue/renew/revoke records describe metadata transitions and observations;
their existence does not enable unqualified provider mutation endpoints.

## Entry points

| Surface | Contract |
|---|---|
| `SqliteBaoOwnerV1::open` | Private local storage; compiled migration schema and integrity verification; optional externally trusted checkpoint comparison |
| `import_reference_snapshot` | Validated schema-4 JSON import with an immutable receipt; conflicting imports fail |
| `claim_consumption_for_execution` | Atomically create exact operation identity and a generation-fenced forward claim |
| `transition_consumption` | Expected-revision and optional execution-claim checks before a metadata transition |
| `claim_due_reconciliation` | Bounded, fair, expiring worker claims; claim generation prevents stale updates |
| `archive_terminal_before` | Bounded move of terminal history into an immutable archive; retains operation identity |
| `checkpoint` | Hash the authoritative snapshot under one read transaction |
| `publish_checkpoint_with` | External compare-and-swap callback while holding a local writer reservation |
| `SqliteBaoProductRuntimeV1::consume_kv_v2_with_authbus` | Approved, registered forward ingress with durable hooks around AuthBus and consumer boundaries |
| `reconcile_consumption` / `reconcile_due` | Observe and settle original work; never fetch the secret or repeat the consumer effect |

`BaoFinalUseHost` retains the registered consumer configuration digest and
observer. Recovery requires that same registration. Historical success is
returned as metadata and is not a fresh grant to consume the secret.

## Schema and invariants

The compiled migrations are `0001_bao_owner_v1.sql` and
`0002_reconciliation_claims.sql`; the current SQLite schema version is 2.
The imported reference-owner format is version 4. These versions describe
different storage formats and are not interchangeable.

| Table | Durable fact |
|---|---|
| `bao_owner_meta` | Schema identity, owner revision and monotonic time frontier |
| `bao_operation` | Cross-domain operation identity and immutable semantic digest |
| `bao_consumption` | Consumption state, AuthBus reservation and bounded metadata receipt |
| `bao_lease` / `bao_lease_operation` | Lease generation and operation-bound provider observation |
| `bao_transition` | Append-only transition history |
| `bao_reconciliation_queue` | Due work, attempts, errors and operational execution claims |
| `bao_terminal_archive` | Immutable historical terminal result |
| `bao_reference_import` | Immutable import lineage |

Unsigned 64-bit values use fixed-width big-endian blobs. SQL constraints,
compiled schema comparison and decoded-record validation complement one
another. A lease projection must exactly equal the terminal operation's
resulting lease; its kind, provider observation, reference, scope, consumer
and generation must agree. Denied operations cannot update a lease.

All mutable writes use a transaction and expected revision/generation. An
uncertain commit fences the owner. Idempotent mutation retries must also
honor that fence; reopening and validating durable state is the recovery
boundary. A queued writer rechecks the fence after acquiring the SQLite lock.

Database, WAL, SHM and rollback-journal paths are checked before SQLite opens
them. Unix storage is owner-only and unsafe symbolic or hard links are
rejected. A private parent directory is part of the storage boundary; this
does not defend against an attacker already controlling the process account.

## Recovery, resource bounds and checkpoints

The library runtime claims each recovery row immediately before executing
it, using a fresh authority-clock observation. `recovery_batch_limit` caps
work performed per call. Later rows do not spend their lease waiting behind
an earlier observer. Cancellation or failure leaves generation-fenced durable
work available for subsequent reconciliation; it never authorizes redispatch.

| Resource | Implemented ceiling/default |
|---|---|
| Active operations / reconciliation rows | 65,536 each |
| Archived terminal rows | 1,048,576 |
| Encoded record | 128 KiB |
| Worker claim batch API limit | 1,024 |
| Forward lease default | 180 seconds |
| Recovery lease default | 60 seconds |
| Lease maximum | 300 seconds |
| Recovery backoff default | 1 second, capped at 60 seconds |
| Process-local latency sample history | 256 observations |

Checkpoint and metrics scans consume rows incrementally. Checkpoint SHA-256
preserves the existing framing and row ordering without concatenating the
database in memory. Archival reads bounded identities and processes records
individually. Total scan time and archive growth still require target-host
capacity measurements; streaming is not constant-time qualification.

The checkpoint includes authoritative rows, transition history, import
lineage and reconciliation scheduling. Operational claim owner, expiry and
generation are excluded, so worker coordination alone cannot change the
authoritative checkpoint. The external service must retain the trusted
predecessor and reject stale compare-and-swap publication. A local file or
caller-provided boolean cannot establish independent anti-rollback trust.

## Verification and remaining integration

Run `just test -p codex-hepta-bao-adapter -p codex-hepta-types
-p codex-hepta-authbus -p codex-state-sqlite --locked` from `codex-rs`.
The read-only qualification workflow separately binds the source candidate,
deterministic merge, command logs, Cargo lock and canonical manifest to one
workflow run and attempt. Verify all log digests and actual test counts.

The library exports `compose_hepta_secrets_runtime` from
`product_bootstrap.rs`, so a host can import the composition and recovery
helpers. The `hepta-secrets-runtime` binary exposes description/configuration
validation. The lexical constructor is source evidence; `main` does not
start a selected secret-consuming product process. Product
composition, independent time/settlement services, consumer deadlines,
checkpoint operation, shutdown draining, metrics export and target-host
power-loss/restore qualification remain explicit integration work.

Unsigned external receipt declarations may be structurally complete while
remaining unqualified. Independent acceptance requires authenticated evidence
from an independently provisioned trust boundary. Source tests cannot confer
operator acceptance, activation, promotion or release.
