# auth.authbus service objectives

Status: production activation baseline

These objectives apply only after the module passes exact-head qualification and
an activation decision names the production owner, signers and deployment
paths. Security failures are not traded against availability.

## Availability and latency

| Objective | Target | Measurement |
|---|---:|---|
| Authorization availability | 99.99% monthly | valid requests served while the authority is healthy |
| Authorization p99 latency | <= 25 ms | host entry to durable decision, excluding caller network |
| Reservation p99 latency | <= 50 ms | host entry through checkpoint synchronization |
| Settlement p99 latency | <= 75 ms | signature/registry verification through durable checkpoint |
| Maintenance tick success | >= 99.9% over 30 days | complete tick with a published receipt |
| Planned restart readiness | <= 60 s | process start to admission-ready, at supported backlog |

A fail-closed denial caused by invalid issuer, stale trusted time, rollback or
corrupt state is a correct security outcome and is excluded from availability.
An infrastructure failure that prevents validation is unavailable, not a deny.

## Freshness and backlog objectives

| Signal | Warning | Critical |
|---|---:|---:|
| trusted-time sample age | 50% of configured validity | 80% of validity or any expiry |
| checkpoint dirty duration | 5 s | 30 s |
| expired held reservations | > 0 for 2 ticks | growing for 3 ticks or oldest > 5 min |
| indeterminate reservations | oldest > 5 min | oldest > 30 min |
| maintenance tick age | 2 x cadence | 5 x cadence |
| outbox oldest ready item | 2 min | 10 min |
| owner-lock collision | n/a | any unexpected collision |
| SQLite busy wait p99 | 250 ms | 2 s |
| database size | 70% operating budget | 90% operating budget |

## Correctness objectives

The target for every item below is 100 percent. Error budgets do not apply.

- no caller-constructible trusted issuer handle in production features;
- no settlement against a key/purpose/epoch outside the durable registry;
- no simultaneous active owner for one authority database;
- no successful public mutation that bypasses checkpoint synchronization;
- no quota release from an ambiguous post-dispatch outcome;
- no trusted-time or checkpoint generation rollback;
- no skipped/cancelled required qualification receipt represented as success;
- no production dependency enabling AuthBus `test-support`.

Any violation is a severity-1 incident and blocks further activation or rollout.

## Error budget policy

- Availability error budget: 0.01% per calendar month.
- Consuming 25% of the monthly budget in 24 hours freezes non-remediation
  releases.
- Consuming 50% freezes activation expansion and requires an incident review.
- Exhaustion disables new activation and requires security/operations approval
  to resume.
- Correctness/security objectives have zero budget; a single violation invokes
  the recovery and activation-revocation procedures.

## Required labels

All metrics and receipts must include bounded labels:

```text
module="auth.authbus"
environment
owner_id_hash
authority_instance_id
source_sha
schema_digest
result
reason (enumerated only)
```

Never label metrics with raw principal, message, reservation, operation or issuer
IDs. Use counters for reason classes and dedicated audited lookup tools for exact
records.

## Release gate

An activation candidate must show at least seven continuous days in staging with:

- all correctness objectives satisfied;
- no unexplained owner collision, rollback or integrity failure;
- maintenance and backlog objectives within threshold;
- successful key rotation and revoked-epoch drill;
- successful crash/restart and checkpoint-loss drill;
- exact-head and synthetic-merge receipts bound to the candidate SHA.
