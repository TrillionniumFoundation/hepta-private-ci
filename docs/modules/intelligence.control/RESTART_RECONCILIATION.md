# intelligence.control restart reconciliation contract

Parent: [TECHNICAL.md](TECHNICAL.md). This contract governs the existing Agentd
learning host, kernel.operations owner and learning.ledger writer. It grants no
physical, model, promotion, release or independent-acceptance authority.

## Durable identity and publication

An append retains one schema-V2 immutable sidecar and one operation intent:
scope/run ID, operation ID, destination, payload digest, original predecessor and
owner generation. The payload retains signed evidence and the complete verified
principal/controller/credential/key/scope/epoch/authentication binding. V2 event
encoding remains unchanged by splitting the source into codec and runtime files.

The sidecar is synced before operation publication. Installation must not replace
an existing immutable object. Equal concurrent content is idempotent; different
content under the same identity conflicts. Operation state and final-use fencing
remain owned by kernel.operations, not by an intelligence shadow journal.

## Two distinct clocks

`payload.now` is immutable historical event/enqueue time in Unix milliseconds.
It is not the current verification time. A new clock read supplies verification
at enqueue, before replay evidence verification and immediately before calling
the destination writer. A signed event that was valid at enqueue but expired
before first application is not currently valid merely because `payload.now`
remains earlier.

Clock failure or current time earlier than event time is indeterminate and must
not produce a NotApplied claim. Principal/evidence expiry, current trust,
revocation and scope remain independently checked. Never renew an old signed
event by silently changing its timestamp, signature, principal or operation ID.

Historical observation is different: an exact already-applied event is read as
an immutable fact, not reapplied using expired authority. It does not thereby
become eligible for current training or execution.

## Recovery algorithm

For each visited unsettled operation, the live generation:

1. adopts it only through the existing operations generation fence;
2. loads bounded sidecar bytes and checks digest, schema and intent identity;
3. reconstructs the complete expected V2 authenticated event;
4. observes the authoritative destination before asking for new mutation rights;
5. acknowledges an exact already-applied event only under the destination's
   full acknowledgement policy, including the independent witness;
6. for an absent event, obtains a fresh final-use grant for the adopted binding;
7. re-verifies the unchanged evidence at the current host time;
8. applies only the original payload and original ledger predecessor;
9. records only an authoritative applied, rejected or quarantined result.

The current source performs full event equality and destination-first recovery.
**Independent witness catch-up is still an open acceptance requirement:** a
ledger-present event with a lagging witness must not be treated as fully
acknowledged merely because its event bytes match. This contract does not claim
that the remaining witness reconciliation is implemented or qualified.

## State and error distinctions

| Situation | Required disposition |
|---|---|
| Exact destination event and required witness acknowledgement | Acknowledged / Applied |
| Deterministically conflicting, malformed or inapplicable append | Rejected / NotApplied |
| Current revoked or expired evidence/grant | Revoked / Quarantined |
| Unknown commit, witness lag, clock rollback, unavailable authority or ambiguous I/O | Indeterminate / reconcile-only |

Missing destination evidence is never itself proof of NotApplied. A grant
provider error during unsettled recovery leaves that operation unresolved and
allows later records to be visited. An unavailable grant before initial dispatch
may defer the existing claim only while kernel.operations proves it is still
Prepared under the exact live lease. The deferral bumps the fence and preserves
identity; a Dispatching or Indeterminate effect is never requeued this way.

Other definite authority failures and corrupted state remain explicit failures;
this contract does not reinterpret every exception as success or retryable work.

## Fair scheduling and cancellation

A bounded keyset cursor orders unsettled identities by `(scope_id, operation_id)`.
It does not order repeatedly by a unchanged oldest timestamp. The cursor is
process-local scheduling state, not an authority grant; restart begins a new
traversal. Concurrently settled/removed keys still advance the traversal.

For a batch larger than one, recovery and first dispatch receive separate shares.
Unused recovery capacity can go to new dispatch. Batch size one alternates.
Each iteration is at most the configured batch and generation is checked before
and after work and before individual new dispatches. Dependent Outcome
operations still obey their Decision predecessor; fairness cannot bypass it.

Cancellation is checked between calls and while waiting for the cadence.
Synchronous learning file/grant/writer operations still need complete bounded
owner supervision; no hard-interruption guarantee is made for them. The current
service waits for the existing Running readiness gate, so drain-time/historical
recovery availability remains a separate lifecycle acceptance question.

## Files and resource policy

Payload reads check the opened regular-file metadata and cap bytes at 1 MiB.
Publication uses a unique temporary name and no-replace hard-link installation.
Existing bytes must compare exactly; payload/file and directory durability are
separate cuts. Parent-anchored no-follow/nonblocking open, replacement races,
orphan retention, disk-full/permission changes and backup rollback require
additional tests. Do not claim those are closed by an inode comparison alone.

The runtime configuration remains a 10 ms to one hour cadence and batch 1..256.
It installs no implicit writer, trust root or grant provider in the ordinary CLI.

## Required executable evidence

Preserved unit tests cover exact identity substitution and V2 round trips.
New tests cover current-time expiry, rollback classification, real SQLite
keyset traversal, Prepared-only deferral and fair budget allocation. These are
source references until executed on the exact candidate.

Default-product acceptance additionally requires process loss before/after
sidecar publication, intent commit, grant claim, destination commit, witness
advance, acknowledgement and generation adoption. Prove already-applied recovery
without a new write grant, expired first-application rejection, live grant
revocation, durable unknown outcomes and no redispatch after lost physical ACK.
Measure latency/RSS/backlog recovery and independently accept the chosen host.
Exact package CI alone does not establish this product-level fault matrix.
