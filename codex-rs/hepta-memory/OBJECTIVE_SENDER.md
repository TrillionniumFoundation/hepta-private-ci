# Original-owner Objective sender retention

This slice implements Objective submission retention inside the existing
`CognitiveStore` and `ProductionDurableWriter`. It uses the writer's original
database, lease, process lock and retained live authority verifier. It does not
open another store, allocate an effect operation or send an Objective.

The implementation base is Hepta commit
`16418ddc3416a38a122b883cee46e2d3583cbd41` (tree
`43fde98e9ea789b81b941e48bb65300c76c4292c`, PR #3398). No Cargo dependency or
lockfile change is required.

## Owning code and state

| File | Responsibility |
| --- | --- |
| `src/objective_sender.rs` | Original active-writer current-cut ACK, restricted capability on the same `Arc<ProductionDurableWriter>`, one local send transition, checked observation append, cancellation, shared post-commit checkpoint protocol and acknowledged recovery snapshots. |
| `src/objective_sender_model.rs` | Bounded structural projection of the original `AuthBusObjectiveIngress`, exact input bytes, complete transport origin and writer fence. |
| `src/objective_sender_store.rs` | Original SQLite transactions for atomic retention, immutable events and bounded private enumeration. |
| `src/objective_sender_integrity.rs` | Startup/recovery validation of raw bytes, metadata, original historical leases and the complete event chain. |
| `src/objective_sender_read.rs` | Original-owner enumeration, recovered handles and raw snapshots, with no send permission or independent checkpoint acknowledgement. |
| `migrations/0017_objective_sender.sql` | Two domain tables, original lease foreign keys, immutable rows, contiguous events and uniqueness constraints. |

The request and its initial `permit_issued` event commit in one original
`BEGIN IMMEDIATE` transaction. A deferred foreign key prevents a request from
committing without its first event. The request preserves the exact supplied
JSON and its full origin: Agent, generation, outer request ID, expected peer
UID/PID and endpoint identity. The canonical signed-body hash and raw-input
hash supplement the original bytes; neither replaces them or authenticates an
issuer. Parsing does not compile an Objective or create a new signature.

Uniqueness is stronger than the outer request ID. The same owner cannot retain
a second request for a Run, the same issuer/key-epoch/message ID, or the same
issuer/key-epoch/sequence. Reformatting JSON, changing the socket path, replacing
the peer PID, opening a new facade, changing the writer lease or advancing the
generation does not provide another opportunity for an already-retained Run.
The original RunStart publication for that Run remains the receiving owner's
responsibility.

`permit_issued` records that the opportunity has been irreversibly occupied. It
does not say that bytes reached Agentd. A process that dies immediately after
this commit leaves an unknown request with no new sending opportunity.

## Independent current-cut acknowledgement

The embedding host must implement `ObjectiveSenderCheckpoint`. There is no
default implementation. The current source tree does not contain a production
host service that independently authenticates, durably publishes and returns
this CognitiveStore current-cut acknowledgement.

After each committed request, observation or cancellation, the capability:

1. Acquires the same database's original `BEGIN IMMEDIATE` write serialization.
2. Revalidates the original live lease and captures the entire original
   `CognitiveRecoveryAnchor` with the original capture function. Any intervening
   committed writes are included in this cut.
3. Calls the external acknowledgement under its configured deadline with that
   exact cut and the actual checked original writer fence. The callback must independently
   authenticate the owner and publisher, fence stale publishers, and durably
   establish that the exact cut is current.
4. Requires an exactly matching acknowledgement, rechecks the retained live
   authority and releases the read-only snapshot transaction by rollback, then
   performs a final live-authority check.

The SQLite write lock remains held through the external callback and its first
post-ACK authority check; one final live check follows rollback. A
capability-local mutex would not serialize other original
writers and is not used. The callback must never re-enter this CognitiveStore;
it must also prevent background publication of an obsolete cut after its future
is cancelled. The supplied deadline is positive and at most five seconds.

This is a cooperative Tokio timeout, not a preemptive wall-clock limit. Each
checkpoint future poll and every synchronous verifier, protected-clock or
observation-check callback must be bounded and nonblocking. The embedding must
meet these requirements; the timeout cannot interrupt a blocked callback or
CPU work that does not yield. Cancellation must release external resources
without continuing a stale publication in the background. No extra worker,
runtime or substitute authority service is supplied by this capability.
The deadline applies only to the acknowledgement future. Waiting for the
original transaction, bounded full-state capture, synchronous future construction,
authority checks and rollback are not covered by an overall wall-clock deadline.

An error after the first commit, including acknowledgement refusal, mismatch,
deadline, cancellation or final authority rejection, grants no ticket. Returned
post-commit errors are `AcknowledgementUnknown`; the committed fence is not
rolled back or reset. Future cancellation likewise leaves the first commit and
drops the second snapshot transaction. A retry through a fresh facade finds the
existing record and cannot receive another sending ticket.

This callback acknowledges database recovery state. It is distinct from an
Objective history publication anchor and from AuthBus replay checkpoints. A
call to `recovery_anchor()` is only a local integrity witness and cannot stand
in for the external acknowledgement. A provider that simply echoes its input
does not meet the production contract.

The acknowledgement establishes a current cut at this serialized boundary.
This slice does not retrofit checkpoint publication onto every other original
writer operation. Later writes in other domains require their own host
checkpoint integration; an outdated cut must cause exact recovery to refuse.

### Current active writer without an Objective request

`ProductionDurableWriter::checkpoint_current(&checkpoint, deadline)` exposes
that same original transaction and ACK protocol without creating a request,
sender event, ticket, cancellation right or sending permission. It first
validates the positive, at-most-five-second ACK deadline and the retained live
authority, then captures the full cut with the original active lease and writer
fence under `BEGIN IMMEDIATE`. The independent ACK must match that exact cut.
The write lock remains held through the post-ACK live check; after read-only
rollback, another live check precedes returning the cut.

The sender's post-commit ACK delegates to this entry point. An acknowledged
snapshot uses the same private transaction helper without releasing its original
snapshot transaction. The returned cut describes the serialized checkpoint
boundary; another original mutation after unlock can make it stale. It is not
a claim that the cut remains current at every later observation.

This entry point requires the original **current active lease**. It refuses an
expired, superseded, released or rolled-back writer, and does not call the
publisher after a terminal lease. It cannot publish a cut after `release` or
`rollback_lease`; terminal-cut publication requires a separate original-authority
transaction design. A trusted host may use it at an active-writer success
boundary, but it does not retrofit publication onto every semantic mutation,
dispatch claim or outcome reconciliation. In particular, existing Notes terminal
receipt retirement still has its own missing independent full-cut boundary.

The strict Agentd production factory now requires an explicit `Arc<C>` of this
same checkpoint and a deadline. It preserves the independently authenticated
**initial** recovery cut, recovers the original owner and acquires its lease,
completes any original Notes handoff, then acknowledges the changed live cut
before installing either config handle. Its typed result returns an Objective
sender bound to that same writer and checkpoint Arc. It never derives recovery
authorization from the database being recovered. Notes `attached` remains a
descriptor handshake, not a persisted CognitiveStore record in the cut.

## Host call sequence

The trusted host creates the capability from its already-open original writer:
`writer.objective_sender(checkpoint, deadline)`. It supplies the original raw
issuer envelope and configured transport identity to
`ObjectiveSenderRequest::from_original`. That constructor performs structural
and size checks only.

Before any transport I/O:

1. Await `retain_before_send(request)`. Only successful retention and independent
   acknowledgement return an opaque, non-cloneable ticket.
2. Await `mark_send_started(&ticket)` on the same original writer. This first
   consumes the local permission, then rechecks the original authority, lease
   and WAL/FULL durability. Failure cannot rearm the ticket.
3. Enter the existing original Objective transport once. A transport error,
   lost reply, partial write or generation change is never a resend instruction.

The ticket retains a weak reference to its issuing original writer. A new
facade using the same `Arc` can operate on it; dropping and reopening a writer
does not make an old unused ticket transferable to the new owner instance.

Fresh retention in this production composition profile requires
`origin.spawn_generation == writer.generation()`. This is the explicit
Agentd/lease-generation binding required by the original
`production_composition.rs` factory, not a claim that process generations and
lease generations are interchangeable throughout Hepta. Recovery can retain an
old origin generation under a current writer, but the recovered handle is
read/observation-only and cannot send or claim an unused local cancellation.

`retain_observation` persists bounded exact JSON with a typed Submission or
History kind. It requires a started, previously observed or recovered ticket.
The owner preserves earlier observations when a later query is unavailable.
Only the exact same submission observation is idempotent; a conflicting second
submission observation is refused. Observation contents are data, not an
authenticated publication, a Run completion or an effect receipt. The original
transport/host adapter must validate the original response and retain a real
journal ACK before exposing a history anchor. The ordinary Objective admission
response has no journal publication sequence to synthesize such an anchor.

### Concurrent semantic observation checks

The generic `retain_observation` API preserves exact data but does not interpret
the meaning of history publications. A separate `snapshot`, application-level
check and later generic append do not make a semantic invariant atomic: two
recovered handles can both see no history and then append different first
publications. The generic API retains this existing behavior.

Trusted composition code that must enforce an invariant uses
`retain_observation_checked(ticket, observation, check)`. After the original
ticket and live-authority checks, it acquires the original database-wide
`BEGIN IMMEDIATE` transaction, validates the current writer fence and exact
retained request, reads the current observation snapshot, and invokes the
synchronous predicate. Only an accepting predicate reaches the original
immutable append and final live check in that same transaction. A rejected
predicate rolls back before append and before checkpoint acknowledgement.

The predicate receives bounded retained metadata. It must do no I/O, waiting
or store re-entry and must not grant authority. For the Session host's receipt
format, it compares the previously retained original publication against the
new one; a later response generation does not replace the original publication.
The owner does not supply this domain rule automatically. Other trusted writers
of this publication format must apply the same invariant through the checked
entry point; using the opaque generic API can still violate it.

After a successful checked mutation, the original post-commit checkpoint
protocol still applies. An acknowledgement failure can therefore leave the
observation committed with its independent confirmation unknown. An explicit
retry of the exact same observation runs the check again and, if accepted,
obtains a fresh acknowledgement without adding another event. Neither rejection nor retry
restores sending or local cancellation permission.

### Local cancellation and worker boundary

`retain_local_cancellation` atomically consumes only a still-unused live local
permission. It cannot cancel a started or recovered request. A failed
acknowledgement may be retried only to retain/re-acknowledge the same local
cancellation; it never rearms the send. This record is not a `RunCancel` request
and makes no claim about a running Objective or another sender.

Async calls belong on the trusted host's bounded worker/runtime arrangement.
The renderer does not receive this capability, the raw payload or an independent
database handle. The capability provides no network transport or signing API.

## Recovery without a second UI ledger

`retained_page(Beginning)` reads at most sixteen exact retained requests from
the same original owner. Subsequent calls use the opaque owner-bound cursor.
Every returned request is checked against its original row, original lease and
complete retained event chain in one read snapshot, with live authority checks
before and after the read. Global retention bounds are also checked. The result
contains request data only, with no ticket or sending permission.

This is live keyset pagination. New records inserted before a previously
returned key require a fresh pass from `Beginning`; a page is not presented as
a frozen whole-store snapshot. The host keeps original bytes in its private
capability boundary and must not copy them into a renderer, model or second
request ledger.

After reading a retained request, `recover_pending(request)` independently
checks its exact original bytes and full origin again. It returns a recovered
read/observation handle. Such a handle cannot enter `mark_send_started` or local
cancellation, even when the previous process died before its first socket write.
`snapshot` returns the original ordered observations and local cancellation
fact without rewriting unknown history into a completion claim. This raw read
verifies local retained contents; it does not call the independent checkpoint.
A row may exist after its mutation committed but the checkpoint refused,
timed out or was cancelled. Reading that row, or its local recovery anchor,
cannot by itself promote an unknown acknowledgement to a confirmed
`*_recorded` view flag.

### Acknowledged snapshots for recovery projection

Use `snapshot_acknowledged(&ticket)` when restored observations will be exposed
as independently acknowledged. It validates the same owner-bound ticket and
original live authority/WAL/lease, acquires `BEGIN IMMEDIATE`, verifies and
reads the exact retained request and ordered snapshot, and captures the full
current recovery cut in that same transaction. The original checkpoint helper
checks the current writer fence, requires an exactly matching independent ACK,
and rechecks live authority. Only after read-only rollback and a final live
check does the method return the snapshot.

The database-wide write serialization binds the returned observations to the
cut acknowledged by the external provider; it is not a separate read followed
by an assumption about some later cut. Refusal, timeout, mismatched ACK or loss
of authority returns no acknowledged snapshot. The original committed records
remain available for a later explicit read/ACK. This operation adds no event,
does not alter ticket state, and grants no send or local cancellation right.
It can acknowledge a previously committed cancellation through a recovered
read handle without recreating cancellation permission.

The ACK establishes a cut at that serialized boundary, not a promise that the
store never changes afterward. Other original writers can advance the state
after the transaction releases. Full-store recovery still requires an
independently protected current cut, and this API does not implement that
external production service or a new UI ledger.

The retained domain has hard caps: 1,024 requests, 16,384 events overall, 64
events per request, 32 MiB of accounted retained data, 64 KiB per original
request and 16 KiB per observation. Exhaustion refuses new retention. This
slice does not delete fences or invent a garbage-collection condition that could
permit a duplicate send.

## Schema and upgrade boundary

Migration 17 is part of the original compiled SQLx migration chain. The two
tables and five triggers are registered in `REQUIRED_SCHEMA_OBJECTS`; the new
oracle is
`55a697816bedf97c5fa3ef36a4d9d39d98f6f572d825a38541afe62e19203773`.
The original schema oracle was independently reproduced before updating it.
The original state capture includes all columns and exact TEXT/BLOB bytes of
both tables, and `verify_store` now invokes the domain semantic audit. The
existing exact migration-ledger and schema-definition checks remain in force.

An old schema anchor is refused by the original recovery profile/schema check
before recovery opens source descriptors. Production `open_with_recovery`
does not migrate an old source; a caller must not fall back to legacy `open`
after this refusal. An authorized production upgrade and independently
authenticated new current cut remain an explicit host capability requirement.
The legacy cognitive record schema version stays at 1, as in the preceding
migration chain; migration 17 and the exact schema oracle identify this layout.

### Legacy fresh initialization boundary

The actual subprocess diagnostic also exposed an existing distinction in the
original initialization paths: legacy `CognitiveStore::open` creates the fresh
database through SQLite before protecting the main file. Under the observed
umask, a crash left the main file at mode `0600` but its WAL/SHM at `0644`.
The original descriptor-bound recovery correctly refused those sidecars,
because it requires private `0600` files. This slice does not weaken that check,
chmod a crashed source, or treat legacy fresh open as production recovery.

The process-crash tests first create and close an explicit test-only genesis,
then enter the same original `open_with_recovery` path used by production
composition. Its private generation exists before SQLite opens its sidecars.
Only then do the tests exercise actual request/event commits and process death.
A general production fresh-store provisioning or schema-upgrade service remains
outside this slice and must not be inferred from this test genesis fixture.

## Verification and remaining integration

The original owning-package tests are `objective_sender_model_tests.rs`,
`objective_sender_tests.rs` and, on Unix, `objective_sender_crash_tests.rs`.
They cover exact bytes and complete binding, duplicate and changed-route
retention, generation change, a second actual process, withheld/mismatched/
revoked acknowledgements, actual SQLite write-lock contention, future
cancellation, immutable observations, local cancellation, startup semantic
tampering, stale schema refusal, bounded private pagination and same-owner
ticket affinity.

The checked-append regressions use two actual original capabilities and
recovered tickets. A barrier forces both old-style prechecks to observe empty
history: the real generic API is the negative control and retains both
conflicting records, while checked appends retain one and reject the other.
An exact retry obtains one new checkpoint ACK without another event. The
acknowledged-snapshot regressions preserve the real committed-but-unacknowledged
row as a raw-read negative control, exercise checkpoint refusal and timeout,
require fresh ACK before returning recovery data, and test the original SQLite
write lock through the callback. They also check that recovery adds no sending
or cancellation permission. These are test descriptions, not execution results;
the prior source version's passing count does not qualify either new API.

The crash tests end a real child process without Rust cleanup after the
original request, observation or cancellation commit. A test-host checkpoint
file is synced outside the cognitive directory, then the parent uses the
original `open_with_recovery`, reads the retained bytes from this owner and
verifies that no sending permission can be granted. Test verifier/checkpoint
implementations are explicitly test-only and are not production authority or
external checkpoint qualification.

Run owning tests through the repository entry point:

```text
cd codex-rs
just test --locked -p codex-hepta-memory
```

Actual execution results, toolchain and source hashes belong in the associated
validation receipt. Adding these tests or running the independent schema
derivation alone does not establish that the Rust package has passed.

The original Agentd composition exposes
`AgentdConfig::original_objective_sender(checkpoint, deadline)` only from its
installed `AgentdProductionWriterHost`. It checks the original Agent/generation
and delegates to that host's same `Arc<ProductionDurableWriter>`, retaining the
original live verifier. An uninstalled host refuses; the method opens no store
and supplies no checkpoint. `objective_sender_host_tests.rs` adds the original
composition refusal, same-owner ticket-affinity and cross-package wire-digest
tests. The latter serializes the actual original `AuthBusObjectiveBody` through
Agentd's own payload function, covering Unicode and digest spelling, and keeps
the original empty-source refusal. These tests must run
in the original Agentd package and are not covered by the memory-only command.
The explicit getter remains a trusted-embedding compatibility API: it may be
given another checkpoint. The canonical strict path instead consumes
`AgentdProductionHostAttachment::original_sender`, already bound to the factory's
writer and checkpoint. No global prohibition on other trusted callers choosing
a provider is claimed.

The no-request checkpoint regressions cover unchanged full cuts and zero sender
rows, exact original fence fields, invalid deadlines, terminal leases with zero
publisher calls, refused/held/mismatched ACKs, final live revocation, actual
SQLite write-lock contention, cancellation and later explicit acknowledgement.
Agentd adds mandatory-bootstrap and real Notes handoff refusal cases. These are
source-level test descriptions; execution of an earlier source version does not
qualify this checkpoint refactor or the Agentd factory.

Production composition still requires the real independent checkpoint
provider, the trusted adapter from the original Session owner port to this
capability, and the protected host upgrade/current-cut distribution path. None
may be replaced by a self-signed grant, an echo callback, a UI ledger or an
admission response with an invented publication sequence. This slice provides
the real original-owner persistence mechanism and keeps those remaining trust
requirements explicit.
