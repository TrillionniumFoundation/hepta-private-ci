# Objective admission history

`AgentdClient::objective_admission` reads one retained ObjectiveStart request through the existing
control socket. The objective owner advertises `objective.admission.read` version 1.0 and owns
the original RunStart journal. This API adds no store, witness, issuer or execution path.

## Request and owner binding

The existing schema-2 outer request uses the current owner spawn generation and
`method: { "type": "objective_admission", "query": { "request": ..., "anchor": null } }`.
`request` is the exact retained `AuthBusObjectiveIngress`, including its original body spawn.
`anchor` optionally contains `sequence` and `chain_digest`. Owner-only socket access and the
outer generation fence remain unchanged. Consumers must bind responses to the trusted owner,
current spawn and exact request, and retain the query anchor; both modes share a wire type.

The owner compares every stored authentication field, including signature, owner-derived scope and digest
of the canonical typed body. It also matches run identity and the configured profile digest. This is historical
record matching, not fresh signature authorization. Expiry, issuer revocation and a newer spawn do not erase
matching history. New submissions still use existing current-generation, readiness and issuer checks.

## Positive results and unknowns

The response payload is `{ "type": "objective_admission", "outcome": ... }`. `published`
contains `publication` with the original auth identifiers, signed body/profile digests
and publication sequence/digest/chain. Its nested `outcome` is `compiled`,
`explicit_abstain` or `conflict`. Conflict means a durable conflict publication, not an
admitted run. Compiled means immutable publication, even if a later readiness, trust or
runtime step failed; it proves no current run, model turn, final-use authority or effect.

Without an anchor, a positive result is only what the current trusted owner retains. With one,
its sequence and chain must exist in the recovered prefix, and the target publication sequence
must be at or before it. An earlier anchor never authenticates a later publication. Anchors must
come from a retained trusted response; deriving one from the file being checked adds no trust.

`unknown` has one finite reason: `invalid_query`, `owner_unavailable`,
`journal_unavailable`, `no_matching_publication`, `anchor_missing`,
`anchor_mismatch` or `publication_outside_anchor`. None proves non-admission.
Malformed outer frames, unavailable processes and transport failures likewise remain unknown to callers.
No result authorizes resubmission, recompilation, run restart, cancellation or an effect. `RunStatus: null` stays independent.

## Storage and limits

The query holds the original owner mutex and reads its exclusively locked, already
recovered journal projection. It performs no file I/O, append, recovery, truncation or
replay-frontier update. Startup recovery can truncate an incomplete unacknowledged tail.
An independently retained anchor detects missing or changed covered history after
recovery, never live file tampering: even an anchored query does not re-read the file.
Joint journal/anchor rollback is not detected. Corrupt storage can prevent daemon startup instead
of returning an RPC response; clients must preserve unknown in that case.

The existing 65,536-byte control-frame limit applies. Source text stays within 32 KiB and the
canonical body within 48 KiB. Anchors address at most 4,096 publications. Responses contain bounded
metadata, no source text or signature. Ledger/owner/protocol tests cover read immutability,
recovered rollback, full request-field drift, anchor coverage, distinct dispositions and strict
wire decoding; native qualification must additionally exercise actual owner restart and transport loss.
