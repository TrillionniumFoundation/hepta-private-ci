# Production terminal reconciliation

`ProductionDurableWriter` retains destination observations inside the existing
`cognitive_local_events` reconciliation row. The state transition and its
observation payload share the original `BEGIN IMMEDIATE` transaction, event hash
chain, current writer fence and predecessor-generation checks. No additional
table, database, writer or signer is introduced.

## Retained payload

Observer-only `reconcile_target_batch` and inherited queued-operation dispatch
write the `production_terminal_observation` namespace, schema version 1. Its
payload binds:

- the original lease, operation and destination identity;
- the immutable operation semantic digest and original outbox payload digest;
- the operation digest presented to the target for this dispatch or observation;
- the complete committed receipt or not-applied, rejected or quarantined reason.

The event itself binds the authoritative Agent, writer generation and fence. The
original outbox retains the final request bytes, including any destination-owned
delivery identity. An observer request can use a successor authority; its
`operation_digest` must not be relabeled as the original dispatch grant identity.

The entire encoded payload, including JSON escaping and identity fields, must
fit the existing 65,536-byte event limit. Empty, NUL-containing or oversized
details fail before a terminal event is written. Serialization or storage errors
leave the occurrence indeterminate. No bare terminal fallback is permitted.

`Indeterminate` observations retain the original idempotent reconciliation
behavior. `Unavailable` leaves the journal unchanged. Existing terminal outcomes
cannot be overwritten by later observations. The legacy local reconciliation API
and same-generation direct apply/reject payloads remain readable; a legacy state
string is not a structured terminal observation.

## Authority and integration boundary

The target observer still owns verification of its terminal result against the
exact request. Persisting an observation does not independently authenticate it
or turn a transport acknowledgement into evidence of a completed effect. This
change adds no OS adapter, redispatch, FinalUse issuer, claim rearm, history
retirement permission or physical power-loss qualification.

An OS target must retain and verify the complete delivery/target/revision result,
and its original owner must verify durable evidence before granting retirement.
This journal payload is one prerequisite for that integration, not its completion.

## Regression coverage

The package tests cover a real SQLite destination commit with a lost transport
acknowledgement, observer-only reconciliation, exact receipt retention after clean
reopen, inherited dispatch under the successor generation, rejection reason
retention, conflicting later observations, and invalid/oversized receipts that
must leave the original operation indeterminate. Run the original entry point:

```sh
just test -p codex-hepta-memory
```
