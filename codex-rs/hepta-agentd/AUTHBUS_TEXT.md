# Signed text ingress

Agentd can relay an independently signed text message through its canonical
EvidenceStore outbox into the existing private App Server thread queue. The
supervised Agent must be running and its App Server ready. The relay connects to
the Agent's configured Unix socket and verifies the initialized `codex_home`
against that Agent's home before claiming a message.

This is a narrow text-to-existing-thread integration. It does not install keys,
create threads, allocate provider quota, authorize other effects, or replace the
queue's existing capacity and dispatch rules.

## Install trust explicitly

Keep the normal supervisor-supplied Agent identity and environment. Add these
arguments to its Agentd command:

```text
--authbus-trust-file /absolute/canonical/agent/home/authbus-trust.json
```

The file must be a direct child of the canonical Agent home. Set the home to
Unix mode `0700` and the file to `0600`, with the same filesystem owner. The
loader rejects links, foreign file ownership, group/other permissions, files
over 16 KiB, and file identity changes detected during reading. This profile
requires Unix ownership checks. Without explicit configuration, signed ingress
is unavailable; no implicit registration or signing key is generated.

Install this JSON with the actual Agent ID, issuer, Ed25519 public key, epoch,
and allowed existing thread IDs:

```json
{
  "schema_version": 1,
  "agent_id": "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13",
  "issuer_id": "issuer:operator",
  "key_epoch": 1,
  "public_key_hex": "<64 hexadecimal characters from the producer's public key>",
  "revoked": false,
  "thread_ids": ["<existing thread ID>"]
}
```

One issuer/epoch and at most 16 thread IDs are supported. An empty allowlist
permits startup but no text admission; use the normal session ingress to create
a thread, then install its ID. Replace the complete file atomically while
preserving its permissions. The daemon reloads it for admission and dispatch
stages. Keep the private signing key with the independent producer.

Revocation uses `revoked: true`; removing a thread also prevents subsequent
admission/dispatch to that thread. Neither operation cancels work already
accepted by the target queue. Registry reads are current snapshots, not an
atomic transaction with the target queue. Changing epochs does not implicitly
revoke or delete old-epoch outbox rows. Recovery scans filter the selected
issuer/epoch before applying their row limit.

## Produce and submit a message

Construct `AuthBusTextIngress` with `issuer_id`, `key_epoch`, `message_id`,
`sequence`, `expires_at_ms`, `signature_hex`, and this `AuthBusTextBody`:

```text
spawn_generation: the target Agent's current process launch generation
thread_id: an existing allowlisted thread
text: the complete intended user text
```

The public `codex_hepta_agentd::authbus_text_claims(&owner_agent_id, &request)`
returns the canonical claims; it does not sign, enroll, or admit anything and
does not read `signature_hex`. Sign `claims.signing_bytes()` with the producer's
Ed25519 private key and encode the 64-byte signature as 128 hexadecimal
characters in `request.signature_hex`. The claims bind the owner, routing
domain, canonical serialized body, issuer/epoch, message ID, sequence and expiry.
Do not sign an independently reformatted JSON document.

Text must be nonempty and no larger than 8 KiB of UTF-8. The serialized body
must fit 16 KiB; JSON escaping counts toward this bound. Expiry must be in the
future and no more than five minutes from host admission time. The control
protocol's complete 64 KiB frame bound also applies. Use increasing nonzero sequences
per issuer/epoch/owner/route; lower or already-consumed sequences cannot create
new admissions.

Call `AgentdClient::submit_authbus_text(request)`, retain the returned delivery
ID, and poll `authbus_text_status(delivery_id)`. If the submit response is lost,
retry the exact signed request while it remains valid and authorized. A retained
duplicate returns the existing state. Do not manufacture a new message ID or
signature to recover an unknown delivery.

## Interpret status and recovery

| State | Meaning |
| --- | --- |
| `Queued` | Durable AuthBus admission; target queue acceptance is not yet acknowledged. |
| `Leased` | A delivery attempt has acquired ownership; recovery may follow lease expiry. |
| `QueueAccepted` | A matching target queue or persisted-turn binding was observed and its acknowledgement committed. |
| `Expired` | Signed validity ended; no further relay delivery is allowed. |
| `Quarantined` | Delivery stopped without a successful local acknowledgement; the target may already have accepted it. |

`delivery_attempts` counts committed claims, including claims interrupted before
transport. `queue_receipt_digest` hashes the validated queue response; it is
ordinary evidence. `QueueAccepted` does not establish model completion or prove
an external effect. Use the App Server thread/turn APIs for execution status.
Stored states can lag wall-clock expiry until maintenance or a worker observes
it. Missing/pruned history is an error, not a fabricated terminal result.

Only claim 1 uses `ThreadQueueReconcileMode::AllowIfAbsent`. Every subsequent
claim uses `ReconcileOnly` with the same delivery-derived client ID and complete
input digest. A matching queue item or persisted turn can be acknowledged;
`Missing`, `Cancelled`, or an inconsistent response is quarantined. Recovery
does not create an absent submission. The queue's reconciliation operation can
update binding metadata and wake an already accepted queue item; it is not a
purely read-only API.

Timeouts and lost responses never authorize resending an unknown external
effect. Even a crash after claim but before sending recovers conservatively:
if lookup finds nothing, the message is quarantined. A lease renew precedes the
transport boundary; acknowledgement requires the current issuer, signed expiry,
and current lease fence. Revocation or generation fencing after target acceptance
can prevent acknowledgement without undoing that target acceptance.

The shared outbox permits 4,096 total rows, 16 KiB per payload and 16 claims per
message. Agentd uses 30-second leases and a one-second retry delay; the owner API
caps leases/delays at 60 seconds. Active rows cannot be pruned to free capacity.
Terminal history retains at most 1,024 rows or 24 hours and may be pruned earlier
under pressure. Replay high-water records remain separately bounded at 16,384
keys and are not removed with terminal history. See
[signed admission and durable replay](../hepta-authbus/SIGNED_ADMISSION.md).

## Development and validation

Manual review covered the model-visible item that can exceed 1,000 tokens:
the 8 KiB text / 16 KiB encoded-body caps keep a single item below 10,000
tokens. Text enters the existing `UserInput::Text` queue/history path; the host
does not rewrite history, add system/developer instructions, or inject a
model-visible signature endorsement. Signer trust remains a host admission
check.

`src/authbus_dispatch_tests.rs` injects queue faults around the real signed
SQLite lifecycle: lost responses, abandoned claims, conservative recovery,
revocation during transport, and readiness/trust rejection. Evidence tests
cover reopen, leases, stale fences, terminal isolation and issuer-filtered scans.

`tests/authbus_text_product.rs` starts real supervised Agentd and App Server
processes with a local mock model endpoint. It checks queue acknowledgement,
the unique completed persisted user turn, exact model input, duplicate handling,
and rejection of invalid signatures, unlisted threads, revocation and missing
configuration. Local execution compiled both tests but stopped before readiness
with Unix control-socket bind `Operation not permitted`; native CI must still
run them. The scoped library run passed 132 tests (one existing skipped test).
Injected transport tests alone do not establish the native product result.

Run the scoped suites with
`just test -p codex-hepta-evidence -p codex-hepta-agentd`, then the repository's
scoped fix/format workflow. This
profile supplies no production key hosting, provider quota ledger, cross-backup
rollback protection, or exactly-once external-effect guarantee.

## Private consent for paired learning

Production paired-learning authorization is currently unavailable. The old
SQLite-only verifier was removed: an acknowledged delivery and a live Root
signature do not establish the original Core turn, its current persisted
queue entry, or the attached host's replay checkpoints. The complete runtime
verifier has not been connected.

The [historical API and process description](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/9917930245b184cba7ded078221fe90a2335eab7/codex-rs/hepta-agentd/AUTHBUS_TEXT.md#private-consent-for-paired-learning)
is retained with its original source identity. It is not a current invocation
guide or proof that the missing turn boundary was satisfied. See the
[current safety stage and migration limits](../../qualification/paired-consumer-integrated-20261123/BOUND_LOOP_ZH.md#原线程授权边界的安全收口).

The commitments below still define the unsigned statement format.

| Digest | Exact input |
| --- | --- |
| `study` | SHA-256 of the study protocol bytes named by both participants and independently pinned by intake. |
| `failure` | `cell_experiments.data.record_digest` of A's complete original v1 failure record, including the verifier evidence retained there. |
| `correction` | `record_digest` of A's separately retained complete corrected v1 record for the same task. Training intake checks the failure, the correction, their task relationship and training rights. |
| `freeze` | The separately retained canonical digest returned by `paired_freeze.freeze` before B's arrival. |
| `task` | `record_digest` of B's entire evaluation-only v1 confirmation record, including its verifier parameters and record metadata. |

For the original #7018 study, the raw `PROTOCOL.md` at commit
`1df26bf88c32a7c61340f1c1a93ae88d7841509b` has SHA-256
`00e43fc72bb1cc2545d6f1d13fa67c448f413343c5e0c3ce1fdd9de91086f5fa`.
[Original study protocol](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1df26bf88c32a7c61340f1c1a93ae88d7841509b/qualification/cell-cross-user-milestone-20261123/PROTOCOL.md)

`record_digest` hashes the UTF-8 canonical record JSON produced by the
existing Python data module. The training scope is
`TrainOnFailureAndCorrection { failure, correction }`. Each original UI
statement is produced by `scope.consent_text(study)`. Keep the original
signed statement and owner association private. The enrollment authority must
check distinct people. The intake log must independently witness freeze and
arrival order, and settlement must verify the payer's order separately.

### Separate host process is disabled

The legacy verification mode returns `ORIGINAL_TURN_VERIFIER_REQUIRED` before
reading stdin, SQLite paths, routes or inherited capabilities. Even a connected
Root socket and held pidfd cannot enable it. It emits no authorization receipt.
Historical native binaries and receipts retain their old identities; they
cannot reactivate production intake in this version.

### Prepare a statement on the participant's Linux machine

Save the private, custodian-supplied study and record commitments as `scope.json`.
For A its two fields are `study_sha256` and
`scope={"use":"train","failure":"…","correction":"…"}`. For an independently
enrolled B they are `study_sha256` and
`scope={"use":"evaluate_only","freeze":"…","task":"…"}`. Use the actual
64-character lowercase hex digests. B receives the separately observed freeze
before first delivering the previously unseen task.

```sh
hepta-paired-consent --print-statement < scope.json
```

The command prints the exact unsigned consent text, including its record
identities, with no trailing newline. Review the permitted use, task and
hashes against the material you intend to share. Printing, saving or submitting
this text does not activate the disabled paired-learning verifier or intake.
A future implementation must verify the same original turn through the
protected runtime before any authorization can be recognized. Never post the
private content or delivery ID in a GitHub issue.

The enrolled site supplies the actual UI and identity association. This
command neither opens a network service nor enrolls a new identity. Sites
without that physical session must first register the participant through
their existing enrollment authority.
