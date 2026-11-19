# Original Root Source capture and durable terminal handoff

## Scope and authority

This stage connects the original Root Initial session to fixed, preheld Source
inputs and a terminal notification. It preserves Source data after its writer
has quiesced. It does not authenticate completed A experience, issue a historical
read grant, freeze a Dataset, select a model, or authorize a new writer.

The new `--historical-source-deployment` Root CLI argument requires the original
Initial deployment and handoff. Its bounded Root-owned 0600 metadata fixes the
single-published-Q24 configuration and the existing Source journal and witness.
The loader opens original readonly descriptors, derives Agent identity from the
actual registration, and retains the unique capability in that same Initial
runtime. It cannot create Source files, substitute serialized observations or
pins, or manufacture a retired publisher. TaskFlowFence and the original Cell
types do not acquire a general Deserialize implementation.

`CaptureSource` and `CaptureAck` are separate-purpose unit commands on the
original authenticated Initial stream. Neither carries paths, source metadata,
observations, pin digests, identities or completion claims. The original profile,
sequence, process lifetime and deadline remain binding. Root releases its
original writer context and CURRENT lock before waiting on the capture worker,
then checks that context again. The source worker independently reads the real
physical journal and witness through its preheld descriptors.

This candidate publishes the Root side only. The ordinary production launch
hook and companion daemon capture client were local work in progress; their
manifest was retained, but six first-stage files could not be recovered exactly.
The companion group is not included here. There is no complete compilable companion source group
in this candidate, no published daemon quiescence/half-close behavior, and no
ordinary main learning assembly. The later Initial Artifact readview work is
also outside this stage's source manifest.

## Durable states and their exact meaning

| Persisted state | Meaning | Recovery behavior |
| --- | --- | --- |
| Missing | No original handoff record was retained. | Refuse; never create a replacement from current files. |
| Pending | Root captured the exact data pin and registered its original publisher/profile/target. | Refuse. |
| PeerAcknowledged | The original peer's CaptureAck was received and its CAS persisted inside the original context. | Refuse; never infer that the context's postchecks completed. |
| Finalized | That context returned Ok, the same receipt deadline was checked, and a separate finalization CAS was attempted and retained. | Read only the existing record and exact matching, unfenced Source pin. This is still data, not learning authority. |
| Fenced | An observed failure or uncertainty made the attempt unusable. | Refuse; exact repeat fencing is idempotent and a different binding is never overwritten. |

The second transition closes the Root-crash window between the peer-ACK CAS and
the original context's postchecks. A crash there leaves PeerAcknowledged, which
cannot be admitted by `open_finalized`. Recovery does not call initialization,
acknowledgement, finalization or Source reconstruction.

Finalized records the preceding completed context stage. It does not prove that
the final reply reached A, that the last post-finalization deadline check ran,
or that A retired. If those later live checks report failure, Root attempts to
fence the handoff first and then the data pin, including when one fence attempt
fails. The returned error does not claim a failed durable fence succeeded.

After successful live finalization, normal EOF or the original process's exit
does not revoke that data. The Root protocol expects a future companion client
to consume the reply, half-close its write side, and keep the original process
and five-lane connection alive until Root closes. That companion behavior was
a local design and implementation attempt; it is not present in this candidate.
The Root handler preserves its original channel policy and waits for terminal
EOF. A later transport failure remains an error to its caller and cannot become
a learning grant.

## Required future joins

Source bytes and a Source witness owned by the same original owner do not alone
prove authentic execution. A later historical admission still needs the
original independently pinned Root data, actual publisher retirement, an exact
new Starting registration, authenticated RunStart, physical Cell decisions, and
the required Ledger Decision/terminal Outcome chain. Dataset freezing and
`with_learning_profile` follow those joins. Reading A does not depend on first
executing C or manufacturing a successor profile.

This stage introduces no proof against coordinated rollback of the entire Root
state and all of its external evidence. The existing protected-store and
freshness assumptions remain explicit.

## Verification and source identity

New source mutation checks protect Reserve-only capture, original descriptor
custody, the unique same-session capability, zero-payload terminal requests,
Pending/PeerAcknowledged/Finalized ordering, existing-only recovery, and fence
ordering. They preserve all original guards and closed caller sets, adding only
actual callers. A frozen first-stage full caller run had exited 1 on an undeclared
`original_broker_head` call in the pin module; the current inventory explicitly
registers that caller and the two actual `original_initial_record` callers.

The execution environment became unavailable before the final local
`git hash-object -w` freeze completed. Seventeen of the nineteen owned files
were reconstructed byte for byte against the last recorded local SHA256 and
uploaded as Git blobs. This establishes their recovered bytes, not a completed
local Git freeze or an exact-source CI result.

The final candidate deliberately uses five new postimages: the Initial parent
module with unused wire re-exports removed, Initial transport, CALLERS, its
exact-digest allowlist entry, and this qualification note. The
transport restores the known terminal dispatch and three refusal arms, using
new diagnostic strings and reviewed whitespace. Its original publication
context remains identical after reversing that layout, the moved request parse,
and the three refusal arms. Its read/current/freshness helpers and original
post-CAS test fault are unchanged. CALLERS preserves all 497 original boundaries,
364 protected rows, their order, and their forbidden guards. Only five existing
caller sets and five protected rows change; seven boundaries and five protected
rows are added. The two upstream native-archive allowlist entries remain intact.

The earlier 21 source mutation methods passed on the then-current shared local
checkout. That is a development observation for the old file-hash set, including
transport SHA256 `b8d8ac945ac33d7630a8db6d45cbb7c783362244d7dd70d2df577cedf8ecc325`
and CALLERS SHA256 `8929f1d2bbb901566f48a031b2a6f942099c76e5189ff50bb86cb642dd6cef13`.
It is not attributed to this reconstructed candidate. The local shared checkout
also contained independently owned work; no exact-source full-checker, Rustfmt,
native compilation, or native test pass is claimed for this new candidate.
Qualification must use the assembled Git tree and retain its original command,
complete test identities, JUnit and owner receipts. The ordinary main learning
path and complete A-to-B-to-C cold recovery remain unproven.

### New native test identities

All tests below belong to package `codex-hepta-agentd`.

- `authority_host_service::generation_initial::transport::source_capture::tests::original_source_capture_commands_reject_peer_chosen_material`
- `authority_host_service::generation_initial::historical_source_handoff::tests::root_source_handoff_recovery_never_promotes_missing_pending_or_fenced`
- `authority_host_service::generation_initial::historical_source_handoff::tests::root_source_handoff_observed_conflict_stays_refused_after_restored_bytes`
- `authority_host_service::generation_initial::historical_source_handoff::tests::root_source_handoff_recovery_rejects_peer_ack_without_context_finalization`

The three store tests are explicitly ignored by default and require actual UID0
and a private Root-owned directory. Their synthetic binding metadata exercises
real protected-store transitions, exact conflicts, restoration after an observed
conflict, and reopen at the unfinalized ACK stage. They are not original A
execution, real publisher retirement, a killed-and-restarted Root host, or a
complete positive/NoUpdate/cold-restart acceptance test. Their exact names belong
in the explicit Root native roster; the wire parsing test is an ordinary lib test.
