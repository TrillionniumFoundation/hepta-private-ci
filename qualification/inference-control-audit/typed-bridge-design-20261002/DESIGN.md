# Additive Agentd/inference bridge: transition specification

Status: full bridge remains design-only. Shared DTOs, opaque source-proof admission
and the sealed writer reservation port are implemented as inactive prerequisites;
see VALIDATION.md for their separate, bounded test evidence.
Baseline: fe4b945b259c1bf1367c107a36994786b8e56cc1, stacked draft PR 1329.

## Existing product gap

The V2 worker currently asks Agentd to observe a terminal inside
`native_app_server::commit_intelligence_terminal`, before the caller's protected
`settle_native_authorized` transaction. Raw provider completion can therefore be
published before output-policy or economic qualification is normalized. The
legacy callback is not a durable outbox, and a lost acknowledgement does not
carry an immutable publication identity. The replacement must move publication
after authoritative settlement, without moving provider execution into the writer.

## Facts that must remain separate

1. Provider outcome: exact thread/turn/provider/model/correlation and observed
   Completed/Failed/Interrupted. Once terminal, conflicting provider outcome is
   rejected. Unknown remains unknown; no replay or invented NotDispatched.
2. Qualification: output-policy validation, owner authority and budget evidence.
   V2 may retain terminal truth while monotonically lowering qualification.
   Late usage never retroactively changes the actual provider outcome.
3. Primary Agentd publication: an immutable logical result computed from the
   first durably normalized source observation, plus exact owner/run/execution
   binding. Its digest and original destination acknowledgement never change.
4. A later qualification conflict: a separate sticky notice tied to that primary
   digest. It can deny qualified success without publishing a second,
   contradictory terminal effect or rewriting the original acknowledgement.

## Compatibility and admission

Existing AgentRunReceipt denies unknown fields. Its wire shape and legacy
unbound-run semantics remain unchanged. Add distinct versioned bound-dispatch,
bound-status, proven-abort, primary-publication and qualification-conflict
methods/payloads under a new explicit capability. An old owner lacking the
capability is rejected before new bound dispatch.

Legacy terminal/status/release methods must refuse a new bound run with the
existing typed error payload, rather than returning a success receipt that
omits qualification obligations. New bound status explicitly separates provider
outcome, original logical terminal, current qualification and pending notices.
Existing unbound runs continue through their original methods.

Persist the exact Agentd generation/fence, run/context/envelope tuple, execution
plan digest, native dispatch digest and source request identity in the same
inference dispatch event that creates the one-shot local pre-effect token.
Agentd atomically binds that tuple to its own revision before physical send.
An idempotent destination response is reconciliation, never a new send permit.
The existing signed-plan actor time checks and final-use guard remain mandatory.

## Source transitions

| Current bridge state | Input | Durable result | Capacity/publication rule |
| --- | --- | --- | --- |
| Unbound/reserved | Authorized bound dispatch | Exact binding and abort commitment co-committed with dispatch; one live non-cloneable token | Hold capacity; no effect before destination binding ACK |
| Prepared dispatch | Proven pre-effect stop with matching live owner token | Consume token; persist immutable abort proof/outbox | Hold until exact destination abort ACK; never recreate token on replay |
| Prepared/running | Transport/process uncertainty | Preserve dispatch and uncertainty | Hold; reconcile only |
| Prepared/running | First normalized provider terminal | Persist protected observation and immutable primary outbox atomically | Hold until exact primary destination ACK; do not publish raw callback first |
| Primary pending | Duplicate identical source observation | Preserve identical publication digest | Redelivery only; no physical effect |
| Primary pending | Later usage that does not change logical qualification | Persist permitted monotonic V2 usage | Keep original primary; no second terminal publication |
| Primary pending | Later qualification downgrade conflicting with original logical result | Persist source audit plus one immutable sticky-conflict notice | Never replace primary, which may already be committed remotely; do not report qualified success while required notice remains pending |
| Primary pending | Exact destination ACK | Persist ACK bound to publication/owner identity | Release physical reservation only with existing actual terminal or proven-abort evidence; never double release |
| Primary acknowledged | Late usage, same logical qualification | Persist permitted V2 correction | Preserve original terminal and ACK; no new terminal effect |
| Primary acknowledged | Late downgrade conflicting with logical result | Persist audit and one sticky-conflict notice bound to original digest | Do not recall/release capacity a second time; retain reconciliation obligation and deny source-qualified success |
| Conflict notice pending | Exact notice ACK | Persist notice ACK separately | Destination keeps historical primary plus sticky denied qualification |
| Any published state | Different provider terminal, reused publication identity with payload drift, wrong owner/binding/revision | Reject without publication | No mutation of acknowledged truth |

The ordinary model-slot budget is held through the primary obligation. A late
conflict cannot silently reoccupy a released slot after newer work has consumed
capacity. Instead it uses retained bounded reconciliation state, with at most
one primary and one sticky-conflict notice per retained request. The existing
retained-identity bound applies. Retirement/removal cannot discard an unacknowledged
obligation; exceptional retirement still requires its independent authorization.
Further late corrections remain in the V2 source audit and cannot clear the
sticky conflict or create an unbounded series of notices.

Destination publication and qualification notices are asynchronous. This bridge
does not claim an atomic cross-process revocation lease or instantaneous
cross-owner qualification visibility. Source output remains denied while its
required conflict notice is pending. Consumers of bound status must use its
explicit qualification/freshness contract, not the historical phase alone.

## Caller results and data delivery

A destination timeout is a delivery obligation, not a permanent V2 qualification
failure. Do not persist a transient "publication pending" string into the
normalized observation: existing V2 rules correctly prevent later clearing of
real success-denial reasons. The bound product caller returns a typed pending
error until the required durable acknowledgement exists; replay redelivers only
the outbox before it may return the retained observation. It must not take the
existing early `record.observation` return before checking bound obligations.
Unbound callers retain their existing result contract.

Any new await between protected settlement and live-text return requires another
current output-policy check immediately before disclosure. Expired data delivery
is rejected without inventing a new provider outcome or changing historical
terminal acknowledgement. Transport errors and read-time policy expiry are not
silently converted into source-authoritative late-usage corrections. Sticky
qualification conflict is triggered only by a durably accepted V2 qualification
change that actually contradicts the original logical publication.

## Destination transitions

- Bound dispatch validates the complete frozen tuple and persists binding with
  the run reducer transition in one retained image. Exact duplicates return
  idempotent acknowledgements; drift is a conflict.
- Proven abort verifies the live token's previously committed nonce commitment
  and exact binding. Durable source abort proof may be replayed after source
  process loss, but a nonce/token is never regenerated from history.
- Primary publication has an immutable digest including owner/run/binding,
  source identity/revision, logical outcome and actual provider evidence class.
  Duplicate delivery returns the original semantic acknowledgement, even after
  later unrelated run revisions. A competing primary digest is rejected.
- A sticky qualification notice names that exact primary, records its own
  source-audit identity and can only deny qualification. It never changes the
  original actual provider outcome or terminal acknowledgement. Duplicate
  notices are idempotent; conflicts reject. There is no implicit upgrade path.
- Bound retained-store schema changes are explicitly versioned. Old records
  remain readable but cannot acquire proof fields they never possessed.
  Changed process generation still requires independent restart admission.

## Required implementation tests (not executed yet)

- Legacy receipt serialization remains byte/field compatible; legacy callers
  cannot consume incomplete status for a new bound run.
- Real V2 actor signs/binds before dispatch and normalizes policy before primary
  publication; output-policy expiry/over-quota never publishes raw success first.
- Crash cuts before/after source intent, destination commit and source ACK for
  dispatch, abort, primary and sticky-conflict notice. Replay does not resend a
  provider call, create a token, change a digest or release capacity twice.
- Exact duplicate and wrong digest/run/request/generation/fence/context/revision
  tests at both owners, including concurrent senders and dropped replies.
- Late usage before publication, while primary ACK is unknown, and after ACK;
  same-qualification correction, downgrade, wrong provider terminal and attempted
  re-upgrade. Historical terminal remains unchanged; current qualified success
  stays denied after a sticky conflict.
- Dropped destination ACK never becomes an irreversible provider failure; replay
  does not return an observation before required ACK. Output-policy expiry during
  ACK delay denies live-text disclosure without changing historical terminality.
- Pending primary retains capacity; late notice retains identity but does not
  overfill the model-slot budget. Retry count and retained obligations stay bounded.
- Compaction/reopen validates every new event/record combination and preserves
  pending obligations. Corrupt or unsupported state fails closed without repair.

Independent source review and executable tests are required before claiming this
bridge implemented. Actual ingress generation fencing, independently authorized
restart migration and Windows retained-file support remain separate stages.
