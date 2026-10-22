# Production outbox to HOS2

The canonical product API is `hepta-cognitive-store::durable`; that module
re-exports the existing `hepta-memory::ProductionDurableWriter` and physical
`CognitiveStore`. The owner remains that writer and its `LocalLeaseOutbox` in
the already recovered database. Agentd receives its live production verifier,
FinalUse authority and grant provider from the existing host composition. The
HOS2 adapter receives a process-bound control file and the sealed bootstrap
discovery values. None of those discovery values authorizes a native operation.

## Durable identity and admission

The production K is the existing `OperationIntentV1.operation_id`; its
`scope_digest` remains a semantic constraint. It is not the separate
`DurableOperationStore` model's `(scope_id, operation_id)` identifier.

`Hos2InstallBudgetV1` is canonical JSON in the original immutable outbox. It
contains the entire D `(boot_id, cap_space_id, sequence)`, exact management
slot/generation, expected resource revision and CPU budget in nanoseconds.
Sequence JSON uses 16 lowercase hexadecimal digits to preserve unsigned u64
identity through SQLite. The original operation/event/outbox transaction binds
this payload before target entry. A unique index on that existing outbox and a
typed admission check reject a second K for the same D. Original outbox replay
still requires the same K, topic, payload and owner fence.

Admission runs inside the original `BEGIN IMMEDIATE` transaction. The first D
in a namespace must be sequence 1. A subsequent admission must be exactly the
previous admitted sequence plus 1, and the predecessor must already have a
complete matching native terminal receipt in the original source event chain.
The same predecessor condition is checked again in the dispatch and internal
reauthorization transactions. Two simultaneous admissions cannot plan different
K values for one D. A queued, proven pre-boundary, unknown, or merely rolled-back
predecessor cannot unlock the next D. An independent namespace starts its own
sequence. `expected_predecessor_sha256` is the existing destination CAS field;
it is not used as an operation-order dependency.

Migration `0016_operation_pre_boundary_rejections.sql` adds the immutable proof
table and an expression index over the original outbox's boot, space and
hexadecimal sequence fields. Original migrations 0001 through 0015 are not
rewritten. Migration `0017_pre_boundary_rejection_insert_guard.sql` preserves
0016 and rejects every proof identity collision before SQLite can perform a
REPLACE deletion, including either declared unique key and an explicit rowid.
This guard also applies with `recursive_triggers=OFF`; ordinary insertion of a
fresh proof remains in the original claim-settlement transaction. The compiled
schema oracle binds the new trigger definition as well as the four 0016 objects.
This does not create an automatic production upgrade bypass: the original
exact-cut recovery entry refuses a store whose schema/migration lineage differs
from its authenticated current cut. Existing deployments must use their
authorized schema-transition procedure before admitting the new runtime;
recovery never falls back to ordinary writable `CognitiveStore::open`.

## FinalUse and effects

The adapter implements the existing `FinalUseProductionOutboxTarget`.
`dispatch` performs the bounded native call synchronously before constructing
its returned future, inside the original FinalUse consumer-entry closure. A
revocation ordered after that entry does not retroactively cancel the admitted
synchronous effect. No background task, issuer, writer or dispatcher is added.

The real kernel continues to validate the process image, slot/generation and
original CPU owner grant. It holds only D and the native request binding. It
does not accept K, a Hepta journal, a self-signed grant or a host-generated
claim of device success.

## Unknown and observation

The original source becomes `Indeterminate` before target entry. Lost replies,
uncorrelated replies, timeouts and process death remain indeterminate. Recovery
uses only `QueryDelivery` for that same D. `NotSeen`, `Reserved`, `Retired` or
`HistoryLost` never proves that a source-unknown effect was not applied.
They do not authorize a resend, another K with that D, or a retirement claim.
Only a correlated terminal response can settle the original source outcome.

The HOS2 target serializes the full immutable request together with the original
native observation. An applied result must have a nonzero stable object,
the requested previous revision, the immediately succeeding revision, and a
valid consumed CPU time within the reported period. A native terminal rejection
must carry an allowed saved status from the original history owner. A global
ioctl error alone is insufficient because it may not have reserved D.

A successful InstallBudget acknowledgement is compared with QueryDelivery on
all four shared values: previous revision, new revision, effective time and
consumed CPU time. Only QueryDelivery contains the stable object ID; the
InstallBudget acknowledgement and current bootstrap page do not. Neither reply
contains the complete request's cap or payload digest. Query-only recovery
therefore requires the source's unique immutable D-to-request binding and
exclusive use of that native namespace by the original writer. The wire alone
does not prove payload identity.

Observation validates the complete canonical request against the retained
history domain before querying: boot and accessible namespace, fixed-profile
management slot/generation, period and budget ceiling. It deliberately permits
the recovery image to query its retained manager-history namespace. It does
not require that namespace to equal the recovery image's install namespace.
A changed boot or inaccessible history remains unavailable and unknown.
Known management-binding or ceiling contradictions are handled as local intent
disable records both at direct dispatch and at recovery observation; they are
not generic errors that a later query can turn into an older Applied result.

An explicit InstallBudget Conflict status cannot be repaired by querying D:
the kernel can reject different request bytes while retaining an older Applied
result for that D. The adapter returns a typed contradiction without issuing
that query. A correlated but invalid success acknowledgement, or disagreement
between a valid acknowledgement and its history observation, is also recorded
as a contradiction. The original target binds this evidence to K and the
complete immutable D/request. The evidence has private fields and no
deserializer; an arbitrary reason string cannot take this path.

The original reconciliation `BEGIN IMMEDIATE` transaction validates that
binding and the current Indeterminate owner/fence, then uses the existing
`rolled_back` event kind to disable the local intent. This does not undo an
external effect or prove native NotApplied. It uses no new event kind, table,
unique constraint or journal, so an earlier `reconcile_still_indeterminate`
event does not occupy its slot. Observer discovery excludes the disabled
intent. The same transaction gate rejects a later terminal append, including
an observation obtained before the conflict was persisted. Such an intent
cannot unlock the next D or enter the durable retirement prefix.

The existing retained cross-process writer lock also owns an in-process HOS2
use gate shared by every clone of that writer. Dispatch holds it from before
claiming through the synchronous effect and original SQLite outcome append.
The actual observer takes the same gate before discovery and holds it through
settlement; a busy batch returns zero and retries at the existing bounded
recovery cadence. It cannot query an older Applied receipt while a live
dispatch is handing a contradictory result to the original journal. This is
not a claim that a SQL transaction or issuer lock spans the native ioctl.

Cancellation or unwinding inside that use, or failure to persist an observed
contradiction, stops HOS2 dispatch and observation by that still-live owner.
The stop remains shared across writer clones even when database access later
recovers. Claim expiry does not clear it. A normally returned unknown native
observation still uses the original observer-only recovery path; it grants no
retry. This local interruption latch is neither a durable record nor a source
of authority or proof.

There remains a boundary between receiving the contradiction and durably
recording it if the entire process is lost. Independently authenticated owner
recovery cannot reconstruct the lost payload correlation from QueryDelivery's
payload-free history alone. The gate and marker do not remove the exclusive
namespace and immutable binding prerequisites. A contradictory namespace
requires an explicit original owner recovery decision; it is not silently
made usable by discarding D.

That complete evidence is appended by the original reconciliation transaction,
under the existing owner/fence and event hash chain. Public `apply`, `reject`,
or generic reconciliation enum values cannot write a HOS2 terminal event, even
if the caller supplies a string shaped like a receipt. Other destinations keep
their existing behavior. The explicitly attached native target remains a
trusted adapter; the public trait is not a signature verifier for arbitrary
external implementations claiming to be a native device.

## Definite rejection before native entry

The original writer alone can create the non-serializable
`PreBoundaryRejected` value, in the `final_use.claim` or synchronous
`with_verified_use` error branch, before the adapter callback was invoked.
An append-only proof in the same database binds the original operation,
payload, dispatch event, entered/settled claim heads, authority epochs and
rejected nonce. The old event remains `Indeterminate`; it is never rewritten
or rolled back to `Queued`.

Awaiting authorization is a derived owner state: the current claim is exactly
the settled head named by a valid proof, the original event remains unchanged,
and the current owner/epoch/fence still matches. A fresh external signed grant
can consume this proof by appending a new claim, retaining the same K and D.
The original attempt bound and backoff still apply. A new claim head consumes
the proof. Crash after that consumption, any effect entry without a new proof,
a terminal/reconciliation event, or owner-fence drift remains fail closed.
No reason string, timeout, NotSeen response or caller-supplied flag can create
this state. Existing generic unknown operations retain their one-shot fence.

The public dispatch entry tries this narrow path before its ordinary Queued
receipt check only for a current, non-inherited HOS2 receipt. The proof
transaction additionally joins the exact original operation, admission event
and outbox identities, topic, canonical payload and digest before consuming
the proof. A missing or raced proof returns to the unchanged Queued-only gate;
it never generally admits Indeterminate receipts.

Proof insertion and claim settlement share one `BEGIN IMMEDIATE` commit. It
compares the original outbox, semantic and request digests, original
`Indeterminate` dispatch event, exact entered claim, source authority grant,
authority and owner epochs, generation, and fence. Any intervening terminal or
reconciliation event prevents insertion or later reuse. A new claim appends
from exactly that settled head and requires a nonce absent from all rejected
grants for this K. It retains the original 64-attempt maximum and existing
backoff; it does not extend those limits. `production_hos2_proof_tests.rs` covers
both REPLACE forms against every identity, complete row preservation, an
existing 0016 proof crossing migration 0017, normal reauthorization and fresh
proof insertion, and rejection of a weakened guard on reopen.

The actual Agentd production reconciliation loop first asks the existing host
for eligible proofs. Only then does the already attached grant provider receive
the original `FinalUseBinding`. Issuer refusal preserves the pending proof.
An expired or revoked grant is never self-renewed. The same existing dispatcher
consumes a fresh externally signed grant; no retry dispatcher is added. The
separate observer then queries source-unknown operations. A proof from an older
fence does not authorize retry and does not suppress successor observation.
Shutdown cancellation is checked before requesting a new grant.

| Original source and claim | Permitted next action |
| --- | --- |
| Queued, original valid claim | Original dispatch with external FinalUse |
| Indeterminate, exact settled pre-boundary proof, backoff elapsed | Same K/D with a fresh external grant |
| Indeterminate, proof consumed by a new Claimed or Entered head | Query the same D; no resend |
| Indeterminate, no proof, NotSeen/Reserved/Retired/HistoryLost | Remain unknown; query/reconcile only |
| RolledBack after typed protocol contradiction | Local intent disabled; no observer settlement, next D or retirement proof |
| Complete original native terminal event | Next D may be admitted; eligible for contiguous retirement |
| Changed owner epoch, generation, or fence | No proof reuse; existing successor recovery rules apply |

An exhausted attempt budget or an explicitly cancelled planned operation does
not burn a kernel sequence or silently rebind D to another K. Such a namespace
requires an explicit owner recovery decision; the adapter invents no no-op,
cancellation opcode, or evidence of non-entry.

## Durable retirement

`retire_hos2_through` starts from the live original writer. In its original
database transaction it reads every D from 1 through the requested frontier,
verifies each immutable operation/outbox binding and complete terminal event,
and rejects gaps, unknown outcomes, foreign namespaces or invalid receipts.
The scan retains the existing bounded outbox capacity. A digest of those
original operation IDs and event hashes is provenance, not a new signature.

Only this path constructs the borrowed, non-serializable
`Hos2RetirementPermit`. A caller cannot provide a boolean, receipt string or
frontier digest to construct it. After all SQLite awaits, the writer checks the
original live authority verifier again immediately before the synchronous
target call; a writer without that retained verifier is refused. This is an
authorization observation at that check, not a retained issuer or SQLite lock
across the ioctl. Later revocation still follows the original authority's
entry semantics. The adapter must independently hold the kernel's
original `history.ack` capability for that exact boot and namespace; a manager's
observation slot does not acquire acknowledgement authority from the permit.

There is no second acknowledgement ledger or mutable source cursor. If the
kernel retires the prefix but its reply is lost, reopening the same original
source can rebuild the same durable prefix and repeat `RetireThrough`. The
kernel's original operation permits the same or a lower frontier and returns
its current frontier and next sequence. The adapter accepts only a returned
frontier at least as large as requested and a strictly larger next sequence.
If native history is already retired while the original source remains
unknown, no source permit can be produced.

## Source and validation map

| Implementation | Responsibility |
| --- | --- |
| `production_hos2.rs` | Canonical K/D payload and synchronous existing-target adapter |
| `local_hos2_ordering.rs` | Original admission/dispatch ordering and continuous source prefix |
| `production_hos2_terminal.rs` | Complete correlated native terminal evidence |
| `production_hos2_conflict.rs` | Typed original-request contradiction; local intent disable only |
| `production_hos2_owner.rs` | Original terminal append and private retirement permit |
| `production_hos2_execution.rs` | Live dispatch/observer exclusion inside the existing retained writer owner |
| `operation_pre_boundary.rs`, `production_reauthorization.rs` | Original claim-chain proof, CAS, and bounded discovery |
| `hepta-agentd/src/production_writer_host.rs`, `runtime.rs` | Actual attached issuer and recovery-loop composition |
| `hepta-agentd/src/hos2_device.rs` | Explicit Linux HOS2 file, bootstrap, ioctl and history capability transport |

`production_hos2_tests.rs` uses the real SQLite owner and original FinalUse
nonce store. `production_hos2_ordering_tests.rs` exercises concurrent admission,
forged terminal strings, durable terminal-prefix retirement, and lost native
acknowledgements. `production_hos2_process_tests.rs` kills the actual test
process before and after proof persistence, after fresh Claim/Enter, and after
the device's persisted effect. Both the claim-rejection and entry-rejection
branches are covered. `hepta-agentd/src/production_hos2_host_tests.rs` invokes
the actual production recovery loop with an explicit external test issuer and
checks that unknown operations are observed without resending.

`production_hos2_conflict_tests.rs` reproduces an older D receipt with a
different cap, runs the actual public observer while the contradictory
dispatch is held, records the conflict after an existing StillIndeterminate
event, reopens the real source database, and rejects stale terminal evidence,
successor admission and retirement. It aborts that held task and separately
fails the actual SQLite conflict append, checking that the still-live shared
owner never queries the older receipt even after database access recovers.
It also exhausts the real SQLite pool
after a successful authority check, revokes the original verifier during that
await, and verifies that the device receives no retirement call.
`hepta-agentd/src/hos2_device_tests.rs` runs the actual adapter and bounded frame
decoder against explicit scripted replies: Conflict followed by old Applied,
all four shared acknowledgement fields, malformed success and a lost reply.
It also checks known ceiling/slot refusals before ioctl, recovery observation
of the original manager namespace, and changed-boot history unavailability.
Those transport fixtures are not native kernel executions.

Run complete owning suites through the original recipes:

```sh
cd codex-rs
just test --locked -p codex-hepta-memory
just test --locked -p codex-hepta-cognitive-store
just test --locked -p codex-hepta-agentd
```

The proposal workflow runs the repository-pinned formatter, real Cargo
resolution, these suites, scoped Clippy fixes, and the original Bazel lock
generator. It retains exact source identity, every command status, complete
logs, differences and all changed postimages. This is generation evidence for
review. Generated changes must be committed and pass the original CI gates;
running tests on a generated worktree does not mark its input HEAD as qualified.

## Native qualification boundary

G1-d's current three-process C qualification profile and its `G1DQUAL1` history
tag do not prove Hepta SQLite durability. Production attachment must run the
real recovered writer and externally supplied grant provider in the trusted
process composition. Its discovery page is the existing 192-byte HOS2BOOT v2
page: manager/recovery have distinct D namespaces, the workload has no control
slots, and only the recovery holder has the original history acknowledgement
capability. QueryAbi and process identifiers are discovery, not authority.

The disk-backed destination fixtures and current C profile do not establish a
real recovered Hepta process executing against the native device. The Linux
adapter still needs that source-bound guest qualification, including the
externally supplied grant provider and independently authenticated recovery cut.
Callers must supply an observed resource revision when planning a budget; this
adapter does not invent current device state. No default Agentd configuration,
login path, device manager, workload sandbox or mobile deployment is enabled by
these changes. Returning a native result, copying the C qualification tag or
constructing a local receipt does not satisfy production durability.
