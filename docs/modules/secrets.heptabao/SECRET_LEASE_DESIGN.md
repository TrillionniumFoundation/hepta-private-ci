# secrets.heptabao SecretLease design

## Security invariant

A lease operation is identified by a caller-chosen bounded `operation_id` and
a canonical request digest. Reusing the same operation ID with different
semantics is a conflict. Network retries are never an implicit recovery policy.

Authority and provider state are separate facts:

1. `FinalUseAuthority` decides whether this exact operation may dispatch.
2. `BaoLeaseRegistry` decides whether this operation identity is safe to
   dispatch, already terminal, or requires reconciliation.
3. HeptaBao/OpenBao is authoritative for provider lease existence and TTL.

None of those facts may be substituted for another.

## State machine

Effect operations use the durable state machine:

```text
              authority denied
Prepared ------------------------------> Prepared
   |
   | durable mark_dispatched
   v
Dispatched ---- confirmed success ----> Succeeded
   |  \
   |   \ confirmed provider rejection -> Rejected
   |
   +---- transport/timeout/5xx/
         malformed-or-ambiguous success -> Indeterminate

Indeterminate -- signed NotApplied -----> Prepared
Indeterminate -- signed Applied --------> Succeeded
Indeterminate -- signed Rejected -------> Rejected
```

A process crash while the durable record says `Dispatched` is interpreted as
indeterminate when that operation is next prepared. This is intentional:
whether the provider applied an effect cannot be reconstructed from process
memory.

## Issue semantics

V1 issuance performs exactly one GET to:

`/v1/{mount}/{issue_path}`.

Before that GET:

- request shape and bounds are checked;
- a durable operation record is prepared;
- the independently signed final-use grant is verified and its nonce burned;
- the operation is durably transitioned to `Dispatched`.

A successful provider response must have a valid lease ID, a non-zero bounded
TTL, renewable flag and non-empty string-field data. Lease metadata is persisted
before dynamic secret material is delivered to the registered consumer.

A provider-created lease can therefore remain active even when final delivery is
subsequently denied by revocation or the consumer returns an indeterminate
result. That is not converted into "issuance failed"; operators should revoke or
reconcile the recorded provider lease.

## Renew and revoke

Renew and revoke only operate on leases already known to the registry.

Renew dispatches once to `/v1/sys/leases/renew`. Confirmed success increments
the local generation and replaces TTL/renewable observations.

Revoke dispatches once to `/v1/sys/leases/revoke`. Confirmed success increments
the generation and records `Revoked`.

A timeout or ambiguous result for either operation is not retried under the same
operation identity.

## Reconciliation

Known lease IDs may be inspected with `lookup_secret_lease`; this is a
read-only provider operation. Its result can refresh observed Active/Missing
metadata, but it cannot prove that a particular prior renew/revoke caused that
state.

An issuance timeout is harder: if the response containing a newly created lease
ID was lost, the generic provider API has no operation-id lookup in this V1
profile. Automatic re-issuance is therefore forbidden. A trusted reconciliation
process must establish whether the original effect happened and submit a signed
`BaoLeaseReconciliationObservation`.

This design intentionally prefers an explicit unknown state over duplicate
dynamic credentials.

## Consumer boundary

A grant binds `consumer_id`, but that string never authenticates executable
code. The host selects executable consumers through `TrustedConsumerRegistry`
at composition time. Final-use calls resolve the signed ID through that registry;
there is no public per-request closure parameter on the consuming APIs.

The trusted consumer remains privileged native code. It can copy bytes by side
effect, so admission to the registry is equivalent to granting access to secret
material and must be controlled by the host/security owner.

## Versioning

The current dynamic profile is intentionally narrow. New provider engines that
need POST issue bodies, nested secret values, batch credentials or different
renew/revoke semantics must use a new typed profile and signing domain instead
of silently widening V1.
