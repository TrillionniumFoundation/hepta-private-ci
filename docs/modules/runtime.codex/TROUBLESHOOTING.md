# runtime.codex troubleshooting guide

The first rule of runtime.codex troubleshooting is **preserve uncertainty**.
When the physical-send boundary may have been crossed, do not retry the original
operation, release its capacity or rewrite it as failed merely to restore
service health.

## 1. Triage snapshot

Before changing state, capture:

```text
exact release/source/tree and configuration digests
host boot id and service process start identities
Agent id, generation, health and App Server ingress identity
operation id, request digest and dispatch digest
local journal state/revision
Agentd run state/revision and dispatch digest
thread/session/turn/client-message identities
final-use signer, epoch and revocation-head digest
provider audit query result
oldest unresolved/quarantined age
```

Copy evidence to an owner-private incident directory and hash it. Never paste
private keys, complete prompts or raw provider responses into a general ticket.

## 2. Decision tree

### No durable local dispatch exists

The effect boundary was not prepared by this caller. Investigate admission,
capacity, request validation or store failure. A new admission may be considered
only under the normal idempotency rules.

### Local dispatch exists; Agentd is still `ContextAttached`

The server-owned effect-entry fence did not commit. If the same live worker still
owns the non-reconstructible pre-effect proof, it may execute the exact
owner-first abort protocol and then release the local reservation. After process
loss that proof is gone; do not reconstruct it from serialized fields.

### Agentd is `Dispatched` or fence acknowledgement is unknown

The effect-entry CAS may have committed. Post-fence abort is forbidden. A fresh
physical send requires the original caller's fresh non-idempotent acknowledgement;
an idempotent status or recovered receipt cannot mint another send permit.
Reconcile the same operation.

### A turn id or exact started event exists

Observe the exact thread/turn to terminality. Do not create another turn. Keep
owner loss, cancellation and timeout as boundary facts even if a late provider
completion is later observed.

### App Server history is unavailable

Quarantine. Provider absence cannot be inferred from missing ephemeral history.
Follow `QUARANTINE_AND_RELEASE.md`; only an independently signed exact resolution
may close ownership or authorize a distinct replacement operation.

## 3. Symptom table

| Symptom | Likely meaning | Safe action | Forbidden action |
| --- | --- | --- | --- |
| `turn/start` timeout or transport reset | ACK unknown | same-connection exact started-event reconciliation, then durable reopen/read | send another `turn/start` |
| Agentd `RunMarkDispatchedExact` ACK lost | effect-entry fence may have committed | query exact owner state; retain local slot; no send without fresh ACK | abort/release or treat idempotent receipt as send permit |
| idempotent Agentd dispatch receipt | another caller already committed the fence | reconcile only | physical send |
| wrong dispatch digest/revision | stale or competing caller | hard conflict; fence attempt; investigate duplicate owner | overwrite owner state |
| App Server overload explicitly before handler admission | typed non-admission fact | settle both owner and local journal through exact rejection path | leave owner active or reinterpret as provider failure |
| invalid request/method/params | deterministic pre-admission rejection | terminal rejection settlement, no retry of same semantics | label as transient transport error |
| provider event stream lag/disconnect | observation incomplete | quarantine/reconcile; retain operation ownership | infer failure or success |
| owner readiness/generation/ingress lost | success authority lost for this attempt | sticky quarantine/non-success; preserve provider facts | restore success after later healthy ping |
| final-use issuer unavailable | no final-use authority | reject before fence; keep existing unknown operations unresolved | local signer fallback |
| revocation frontier advances before entry | token stale | obtain a fresh independently issued claim only while pre-fence proof still exists | enter with old token |
| revocation/epoch/frontier moves backward | anti-rollback failure | fence admissions and page security/operations | reset local state to match old frontier |
| durable journal write/fsync fails | outcome cannot be safely owned | close admissions; preserve external evidence; recover store | continue effect or delete journal |
| same client message id, different input | correlation conflict | quarantine and page | choose either turn |
| multiple exact matching turns | duplicate-effect evidence | quarantine, preserve all provider facts | settle one and ignore others |
| orphan-thread counter grows | cleanup/lifecycle failure | inspect pre-effect exits, unsubscribe and App Server retention | bulk delete unknown threads |

## 4. Lost acknowledgement procedure

1. Stop any automatic retry mechanism.
2. Confirm operation/request/dispatch digests and original connection identity.
3. On the same live connection, consume only an exact `turn/started` event for
   the bound thread/request.
4. After restart, authenticate the original Agentd/App Server generation and
   invoke `thread/read(includeTurns=true)`.
5. Match both the stable `client_user_message_id` and original `UserMessage`
   content.
6. Treat mismatch, multiple matches, provider/session drift or missing history
   as conflict/indeterminate, not as “not sent”.
7. Persist reconciliation evidence before releasing capacity.

## 5. Pre-admission rejection procedure

A typed App Server rejection can prove that the provider effect was not admitted
only for registered error classes. The settlement must be cross-owner:

1. verify exact request and response digests;
2. verify the rejection class is explicitly pre-admission;
3. terminally settle Agentd for the exact dispatch revision/digest;
4. only after a matching owner acknowledgement, release the local reservation;
5. retain the response digest and reason code;
6. if owner settlement acknowledgement is unknown, keep the local slot and
   reconcile; do not release only one owner.

## 6. Issuer identity failures

If UID matches but PID/start time, executable, cgroup or boot digest differs,
treat this as issuer replacement, not a harmless restart. Close admissions and
verify:

- the selected release and service unit;
- the current host boot and process start identity;
- socket inode and protected ancestry;
- key custody and signer identity;
- authority epoch and revocation frontier;
- anti-rollback checkpoint.

Planned issuer restart requires a new independently attested instance record.

## 7. Quarantine release failures

Reject a resolution when any of these differ from the quarantined record:

- operation, request or dispatch digest;
- evidence digest;
- authority epoch or monotonic resolution sequence;
- signer or signature;
- validity interval;
- nonce replay state;
- replacement operation or provider idempotency key.

A replacement must be a distinct operation. A release signature never grants a
retry of the original operation.

## 8. Capacity exhaustion

Do not solve unresolved-capacity exhaustion by dropping the oldest entries.
Instead:

1. stop new admissions before the hard limit;
2. classify entries as definitely-unsent, started, terminal, or unresolved;
3. execute exact owner/local compensation only for definitely-unsent entries;
4. reconcile started entries;
5. quarantine entries whose effect remains unknown;
6. escalate policy/authority capacity separately from execution capacity.

Capacity pressure is an operational signal that the resolution path is not
keeping up, not evidence that old effects are safe to forget.

## 9. Evidence or CI failure

- A missing, skipped, cancelled or timed-out command record is failure.
- A passing historical SHA is not evidence for the current head.
- Source-head evidence does not cover the ordered synthetic merge.
- Target-host evidence does not cover a different binary, host boot, issuer
  instance, Agent generation, provider account or configuration digest.
- An attestation validates producer/workflow identity and bytes; it does not
  promote a failed manifest.

Keep the PR Draft until the exact candidate has a complete green evidence set.

## 10. Escalation information

An escalation must include bounded, redacted facts:

```text
incident id and start time
exact release/source/tree
operation/request/dispatch/correlation digests
local and Agentd revisions/states
fence acknowledgement class
provider physical-request count
thread/read reconciliation result
issuer process/frontier identity
journal and evidence bundle digests
current capacity and quarantine age
last safe rollback target
```

Do not ask an operator to choose success/failure from model prose or an
unverified screenshot.
