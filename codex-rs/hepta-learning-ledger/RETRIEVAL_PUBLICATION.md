# Retrieval publication V2

This owner-native protocol separates a durable assignment plan from an observed
Agentd Unix-control full-frame write. It uses the existing `LedgerWriter`, journal,
predecessor CAS and independent witness. It does not introduce another writer or
change the external `AgentdResponse` JSON schema. Its Rust records are not a
registered canonical cross-module JSON adapter.

## Evidence and identity

| Record | Durable tag | What it establishes |
|---|---|---|
| `RetrievalAssignmentFact` | 9, unchanged | The original owner assertion; never automatically upgraded to transport confirmation |
| `RetrievalAssignmentIntentV2` | 10 | A bounded assignment and exact planned success response, committed before the first response byte |
| `RetrievalPublicationConfirmedV2` | 11 | The trusted host observed successful `write_all` of that exact frame |

An intent has no `context_exposed` field. `planned_candidate_indices` describes
the proposed subset, not an already published subset. It retains the cue, policy,
source-completeness, candidate-union, recall-packet and assignment-support digests;
canonical enumerated candidate identities; legal and selected indices;
assignment and delivery propensities; omitted count; and the downstream policy
that contributed to this plan. Empty context still has an exact snapshot digest.

The transport binding includes owner, body generation, request correlation ID,
control schema version, complete response JSON plus newline digest and byte count,
and the serialized snapshot digest. The current native transport profile supports
Agentd control schema 2 and a maximum 65,536-byte frame. The success snapshot
retains the stricter four-item/8 KiB context envelope and private original deadline.
Unknown transport versions fail admission.

A request correlation ID is not globally unique: separate client instances can
reuse it. V2 therefore uses its own identity domain and namespace and binds the
complete canonical intent payload, excluding its own record identity. This binds
owner/body/request, the exact frame and snapshot, the complete assignment and
the planned subset and downstream policy. A frame alone would not distinguish
different queries or policies producing identical context. Different complete
plans with the same correlation ID retain distinct identities. An exact replay
is idempotent; retaining its identity while changing semantics rejects. No second
legacy assignment with a fabricated false/true exposure transition is written.
Content identity and confirmation establish at least one observed full write;
they do not count repeated physical writes of an identical plan.

A confirmation identity is derived from the intent record identity and canonical
intent event digest. Admission requires the historical intent to exist and checks
its event digest, frame digest and frame length. A caller-selected alternative
confirmation identity, orphan or altered binding fails. The confirmation is
another event kind referring to one assignment, not another assignment.

## Host sequence

1. Read and validate the actual owner cut and CURRENT providers; privately issue
   the bounded ordered snapshot under its original monotonic deadline.
2. Prepare the response; serialize the complete success frame and check its bound.
3. Commit the intent through the witnessed product writer before writing bytes.
4. Recheck lifecycle, body generation, owner/CURRENT and private issuance after
   the awaited append. A rejection retracts issuance and writes no success frame.
5. Write the exact frame. Consume the private pending handle and start confirmation
   only after a complete successful `write_all` observation.
6. Start committing confirmation before shutdown. Shutdown failure does not undo
   an already observed full write. Confirmation failure cannot be replaced by
   an error frame after sending a success frame.

A private 32-slot reservation bounds publication work before it enters the
blocking pool. It follows the actual append worker, pending transport handle and
confirmation worker until completion or drop. Connection timeout cannot release
a slot still owned by a running worker. Capacity rejection is local and does not
poison a healthy writer; owner/witness failures require explicit recovery.
Before the first byte, rejection returns the existing bounded unavailable error.
After any partial or complete success-frame write, failure is close/log only.

The writer's typed host-observed admission remains a trusted-host boundary.
Digest linkage does not independently authenticate a physical socket operation.
The Agentd production path carries private pending/completion state; a naked
public digest or a prepared response alone cannot trigger that path's completion.
Direct owner-writer callers remain trusted to report the actual host observation.

## Failure and recovery

| Failure point | Durable interpretation |
|---|---|
| Before intent acknowledgement | No confirmed publication; no success-frame byte is permitted |
| Intent acknowledged, then owner/CURRENT/deadline/lifecycle rejection | Intent only; publication is `Unknown` |
| Partial write, write error, timeout or cancellation before full-write observation | Intent only; `Unknown` |
| Full write, then crash before confirmation commit | `Unknown`; actual exposure might have happened |
| Timeout/cancellation after confirmation work starts | Read the actual canonical state; the blocking worker may still commit truthful confirmation |
| Confirmation committed, witness acknowledgement failed | Existing writer poison, exact retry and witness recovery rules apply |
| Confirmation acknowledged, shutdown failed | `HostTransportWriteCompleted` remains a truthful historical fact |

`Unknown` must not become non-exposure, zero reward or a confirmed outcome. Recovery
must not infer a write from intent, silently confirm it, or resend an old snapshot.
A blocking append can finish after cancellation; an intent completed this way
does not establish a write. Confirmation work may start only after the full-write
observation and may finish after cancellation. Cancellation does not erase an
already committed full-write fact. A confirmation failure closes the connection and makes subsequent
learning-required publication unavailable until the writer is safely recovered.

`LearningLedger::retrieval_publication` and the corresponding writer view expose
`LegacyOwnerAsserted`, `Unknown`, or `HostTransportWriteCompleted`. Historical
confirmation remains readable after withdrawal. Its separate
`ledger_lineage_active` eligibility flag requires both intent and confirmation
to remain active. An intent can remain an active *assignment plan* in the generic
ledger projection; generic source membership or freeze does not establish
publication. Publication consumers must use the typed projection and independently
check memory-source currentness and downstream evidence.

## Compatibility and proof limits

Tags 0..9, their original digest preimages, `HEPTLR01`/`HEPTLS02` framing and
witness formats retain their meaning. New readers can replay mixed journals.
Old readers reject tags 10/11; rollback cannot reopen a new journal with an old
writer and discard its unknown records. Checkpoint event-kind navigation includes
the two new tags; anchored replay still verifies the canonical journal.

Legacy tag-9 true or false assertions are never converted into new confirmations.
V2 intent identities have a new domain; they do not reinterpret legacy IDs.
Migration must preserve historical records and use readers supporting the complete
persisted event set before new writers append V2 publication records.

A host full-frame write proves neither peer parsing nor model attachment. Existing
inference `NativeDispatch.owner_context_digest` and reconciled `native_started`
evidence are still required for actual turn/start attachment. None of these
records proves that the model read specific tokens or that a learned policy
improved outcomes. The send-to-confirm crash window cannot be removed by a
single-frame socket protocol: a stronger consumer acknowledgement/gate needs a
separately versioned transport contract. Scientific, canary and release gates
remain independent.
