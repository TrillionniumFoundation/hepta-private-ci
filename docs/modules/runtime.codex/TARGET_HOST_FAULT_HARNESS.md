# runtime.codex target-host fault harness contract

This document defines the external harness consumed by the protected
`runtime.codex target-host qualification` workflow. The harness is deliberately
outside the repository trust domain: repository source cannot self-certify the
selected host, issuer key custody, provider audit stream, process replacement,
or independent acceptance.

## Invocation

The workflow invokes the configured absolute executable once per scenario:

```text
FAULT_HARNESS \
  --scenario <scenario> \
  --source-sha <40-hex> \
  --binary <absolute-built-worker> \
  --agentd-socket <absolute-socket> \
  --agent-id <stable-id> \
  --generation <positive-u64> \
  --model <model-id> \
  --authority-config <absolute-protected-file> \
  --journal-root <absolute-private-directory> \
  --output <absolute-json-file>
```

The executable must be independently provisioned, root/owner controlled,
non-writable by the worker identity, and digest-bound in host identity evidence.
It must not patch the candidate, replace its journal, forge App Server events,
or manufacture provider audit records.

## Mandatory scenarios

The scenario inventory is closed world:

| Scenario | Required invariant |
| --- | --- |
| `provider-ack-loss` | One physical provider request at most; lost acknowledgement is same-operation reconciliation only. |
| `event-lag` | Event loss/disconnect is quarantined; no blind replay. |
| `worker-kill-after-fence` | Killing the worker after the Agentd effect-entry CAS cannot enable abort or a second send. |
| `worker-restart` | Reopen uses the original durable identity and emits no new `turn/start`. |
| `agentd-restart` | Owner recovery preserves dispatch digest, revision monotonicity and unresolved capacity. |
| `revocation-advance-before-entry` | A newer revocation frontier prevents physical send and leaves no false success. |
| `duplicate-owner` | Exactly one caller receives the fresh non-idempotent fence acknowledgement; all others reconcile. |
| `stale-revision` | Stale owner revision and digest drift are rejected without mutation or effect. |

## Evidence schema

Each output is a JSON object with no unknown critical fields and at least:

```json
{
  "schema": "hepta.runtime-codex-fault-evidence.v2",
  "schemaVersion": 2,
  "scenario": "provider-ack-loss",
  "sourceSha": "<40-hex>",
  "verified": true,
  "operationId": "<stable-id>",
  "physicalRequestCount": 1,
  "freshFenceAckCount": 1,
  "duplicateRequestCount": 0,
  "replayedRequestCount": 0,
  "abortAfterFenceAccepted": false,
  "ownerRevisionMonotonic": true,
  "unresolvedCapacityRetained": true,
  "durableOutcome": "indeterminate",
  "journalSha256": "<64-hex>",
  "providerAuditSha256": "<64-hex>",
  "harnessSha256": "<64-hex>"
}
```

Scenario-specific observation booleans are mandatory where applicable:
`eventLagObserved`, `workerRestartObserved`, `agentdRestartObserved`,
`revocationAdvanceObserved`, `duplicateOwnerObserved`, and
`staleRevisionRejected`.

A result with a missing scenario, an unknown scenario, a duplicate/replayed
request, more than one fresh fence acknowledgement, accepted post-fence abort,
non-monotonic owner revision, source mismatch, malformed digest, or unsupported
outcome fails the whole qualification.

## Performance sample

The real-provider canary sample is 30–200 operations, default 50. The manifest
records p50, p95, p99 and maximum wall latency and maximum resident set size.
These measurements are a bounded host profile, not a universal service-level
objective. They remain invalid if any canary lacks exact terminal correlation or
if the provider audit does not prove one unique physical request per canary.

## Independent evidence

The protected runner must also receive independently issued, source-bound JSON
records for:

- target-host process/socket/generation identity;
- issuer key custody and exact process instance;
- durable anti-rollback recovery;
- canary and rollback rehearsal;
- independent acceptance review.

GitHub provenance attests the retained manifest bytes and workflow identity. It
does not replace those external authorities and does not grant activation,
promotion, or release.
