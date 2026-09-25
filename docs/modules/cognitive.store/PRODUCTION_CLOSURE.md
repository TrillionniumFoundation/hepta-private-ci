# cognitive.store production convergence

Status: implemented owner boundaries and outstanding product qualification.
This document describes the current compiled API, not a deployment approval.

## 1. One owner and the actual module tree

`codex-hepta-cognitive-store::DurableCognitiveStore` re-exports the existing
`hepta-memory::CognitiveStore`. The only physical database is the cognitive
SQLite owner. `src/lib.rs` compiles `durable` and `v2`; the obsolete
`ProductionCognitiveStore` implementation and its disconnected tests are removed.
V1/V2 in-memory ledgers are semantic qualification models, not another writer.

The product write chain is:

```text
AgentdProductionWriterHost
  -> ProductionCognitiveMutationCapability
  -> ProductionDurableWriter + current external authority use guard
  -> existing CognitiveStore transaction
  -> source + Memory revision + revision-bound fact set + KG projection
     + local operation admission and committed provenance
```

Facts have no independent writable head. Corrections and tombstones advance the
Memory lineage and its complete fact-set subledger atomically.

## 2. Revocation, cancellation and expiry ordering

`ProductionAuthorityVerifier::enter_use` must atomically validate the current
grant and retain a verifier-owned hold. Its default rejects the request; an
implementation of point-in-time `verify` alone cannot authorize semantic writes
or writable recovery. A trusted verifier must not return an empty hold for
mutable revocation state. Revocation prevents new holds and acknowledges only
when earlier holds have drained. This contract does not mint a trusted issuer.

Semantic writes acquire `BEGIN IMMEDIATE` first, then acquire the external hold
and verify the exact local lease inside that transaction. A request revoked
while waiting for the writer lock cannot mutate the owner. A request that entered
first may finish before revocation acknowledgement; it is not retrospectively
reported as unauthorized. The hold covers terminal commit. The owner retains the
transaction and hold in a commit task when the waiting caller is cancelled, so
an in-flight SQLite COMMIT cannot outlive the hold merely because its response
was abandoned. Observe the operation result before retrying an uncertain commit.

Creating or taking over the production lease is itself a durable mutation.
Live writer startup obtains the same external hold before calling the lease
owner. A point-in-time-only verifier fails without leaving a lease behind.
The startup task retains that hold even when its response waiter is cancelled.

Receipt validation and the lease deadline check precede final commit. Recovery
checks expiry again before publishing the active generation. A revocation hold
does not extend the signed absolute expiry. Process shutdown, physical storage
failure and an unavailable trusted authority remain separate recovery cases.

## 3. Durable reopen versus authenticated writable recovery

Ordinary `DurableCognitiveStore::open` opens and verifies the database but has no
independent proof that it is the latest state. It is not a recovery fallback.
`AgentdProductionWriterHost::open` uses `open_with_recovery`, requiring the
independently retained exact current cut and external production authority.

Writable recovery retains source descriptors under an exclusive store fence,
materializes database/WAL/journal bytes into a private generation, compares the
current cut, verifies schema and integrity, checkpoints and reopens the copy,
then publishes the active pointer. SQLite never recovers the suspect source by
reopening its path. The authority hold spans this ceremony. A pointer rename
whose following synchronization fails remains Indeterminate; its potentially
active generation must not be deleted. This is implemented source, not a missing
VFS placeholder, and not proof that a deployed host has retained the latest cut.

## 4. Deterministic result observation and retry

Before dispatch, retain the operation digest computed by the semantic capability.
Input digesting streams the existing canonical JSON into SHA-256 instead of
allocating a full second payload. Source bytes retain the existing 1 MiB owner
bound; encoded request hashing stops at 8 MiB, before transaction admission.
This resource bound does not replace the owner field/identity validation.
Valid accepted inputs keep their existing JSON bytes and operation identities.
`ProductionDurableWriter::cognitive_mutation_result` and the Agentd host's matching
read-only method return the durable admitted intent identity and terminal result
metadata. Committed results bind the actual Memory/source revisions, projection,
write digest, grant/owner epochs and original writer generation. Observation uses
one coherent transaction and validates the event/outbox pair and operation digest.

An identical semantic retry does not execute again. It returns the typed
`ProductionCognitiveMutationError::ObservedResult` instead of an error string
that callers must parse. This is a committed-result disposition, not a second
successful write or a recreated full Memory payload receipt. Historical results
remain queryable after expiry/release subject to exact owner and writer-handoff
fences; result observation never revives execution authority. Reusing source or
Memory identity with different semantic content still conflicts.

## 5. Shared experience and long-lived history

Migration `0016_shared_experience_active_capacity.sql` projects current policy
heads from immutable policy events. Only non-revoked, unexpired heads consume
active admission slots; reactivation must reserve a slot again. Time is sampled
after writer-lock acquisition. Reopen verifies the head projection against the
immutable event history. The ordinary per-policy revision limit and reserved
withdrawal revision remain deliberate, separate bounds.

No destructive history archival is claimed. A digest-only segment is not a
recoverable archive and does not justify deleting authorization history.
Whole-scope snapshot bounds still apply. Paged reads now verify ancestry in
512-revision batches, with at most 16,384 citations materialized per batch and
262,144 total revisions/citations of work per page. The complete head-set and
current-cut binding are unchanged. Paging still scans global counts and heads.
Arbitrarily long lineage,
historical identity churn, authenticated archive storage and bounded tail
recovery remain work in the existing owner, not reasons to create another store.
Logical tombstones are not physical erasure, backup purge or model unlearning.

## 6. Trusted bootstrap and restart requirements

Normal runtime can receive `AgentdProductionWriterHost`, but it cannot self-issue
its lease, revocation verifier or independently current witness. Deployment must
supply those trusted inputs. A current-cut digest captured from a suspect backup
is not evidence that the backup is current.

The independent witness protocol must serialize admitted mutations and coordinate
pending intent, SQLite commit, witness persistence and acknowledgement. Required
cases are: no commit, committed with acknowledgement lost, witness update failed,
old backup, fresh writer handoff, and process death in each interval. A host may
not repair a pending witness by accepting arbitrary newer database bytes. The
repository does not yet claim this complete normal-daemon protocol; configuration
or hand-assembled qualification objects do not establish it.

## 7. Executable qualification

Use repository `just test` from the root, not disconnected test files:

```sh
just test --locked -p codex-hepta-memory -p codex-hepta-cognitive-store --lib
just test --locked -p codex-hepta-agentd --test cognitive_store_product_writer
just test --locked -p codex-hepta-supervisor --test writer_handoff_production
cargo clippy --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-memory -p codex-hepta-cognitive-store --all-targets -- -D warnings
python3 scripts/hepta-implementation-maps.py verify
```

The dedicated read-only cognitive qualification runs owner, crash, lint, product
and performance checks without depending on the unrelated whole-workspace test
step. Each record binds the actual source or deterministic merge candidate.
The existing PERF-DURABLE executable uses 256 and 16,384 record profiles on
both the exact source and deterministic merge where applicable. Strict lint also
covers the Agentd product test and supervisor handoff targets. A timeout,
skipped step or build failure is not a measurement. Host-specific performance
acceptance and independent release decisions are not inferred from CI.

## 8. Claim boundary

Keep `productionImplementation=false` and deployment/acceptance/release claims
unchanged until the relevant current-candidate execution and trusted bootstrap
requirements are actually met. A committed source fix, passing static navigation,
unit test, product fixture and operational acceptance are distinct facts.
