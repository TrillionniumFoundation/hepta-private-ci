# runtime.codex target-host fault harness contract

This document defines the external harness consumed by the protected
`runtime.codex target-host qualification` workflow. The harness is outside the
repository trust domain: repository source cannot self-certify the selected
host, issuer key custody, provider audit stream, process replacement, rollback
or independent acceptance.

## Prerequisite source qualification

The target-host workflow accepts an exact `source_sha` and a direct
`runtime.codex qualification` workflow run id. It downloads both source-head
and deterministic synthetic-merge artifacts, recomputes their closed-world
contents and verifies their GitHub attestation bundles. Both receipts must be
`passed`, identify the same source SHA and preserve all deployment, acceptance,
activation, promotion and release claims as false.

A branch name, historical green run, unsigned receipt or only one lane is not a
valid prerequisite.

## Harness invocation

The workflow invokes the configured absolute executable once per scenario:

```text
HEPTA_RUNTIME_CODEX_FAULT_RUNNER \
  --scenario <scenario> \
  --source-sha <40-hex> \
  --binary <absolute-built-worker> \
  --agentd-socket <absolute-socket> \
  --agent-id <stable-id> \
  --generation <positive-u64> \
  --model <model-id> \
  --authority-config <absolute-protected-file> \
  --journal-root <absolute-private-directory> \
  --operation-id <stable-unique-id> \
  --output <absolute-json-file>
```

The executable must be independently provisioned, root/owner controlled,
non-writable by the worker identity and digest-bound in host identity evidence.
It must not patch the candidate, replace its journal, forge App Server events or
manufacture provider audit records.

## Mandatory scenarios

The inventory is closed world:

| Scenario | Required invariant |
| --- | --- |
| `provider-ack-loss` | Exactly one physical request and one fresh effect-entry winner; lost provider ACK is same-operation reconciliation only. |
| `event-lag` | Exactly one physical request; event loss/disconnect is quarantined with capacity retained. |
| `worker-kill-after-fence` | Killing the worker after the Agentd fence cannot enable abort or a second send. |
| `worker-restart` | Reopen uses the original durable identity and emits no new `turn/start`. |
| `agentd-restart` | Owner recovery preserves dispatch digest, monotonic revision and unresolved capacity. |
| `revocation-advance-before-entry` | A newer frontier rejects before the fence/send and releases definitely-unsent capacity. |
| `duplicate-owner` | Exactly one caller receives a fresh non-idempotent fence ACK and exactly one physical request occurs. |
| `stale-revision` | Stale revision/digest drift is rejected before fence/send without mutation. |

## Fault evidence v2

Each output is a bounded JSON object with no unknown critical fields and at
least:

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
  "harnessSha256": "<64-hex>",
  "providerAckLossObserved": true
}
```

The scenario-specific required flags are:

- `providerAckLossObserved`
- `eventLagObserved`
- `workerKilledAfterFenceObserved`
- `workerRestartObserved`
- `agentdRestartObserved`
- `revocationAdvanceObserved`
- `duplicateOwnerObserved`
- `staleRevisionRejected`

The verifier rejects a missing/unknown scenario, source mismatch, malformed
identity, duplicate/replayed request, more than one physical request, more than
one fresh fence ACK, accepted post-fence abort, non-monotonic owner revision,
incorrect capacity disposition, unsupported durable outcome or malformed
journal/provider/harness digest.

## Real-provider canary sample

The sample is 30–200 operations, default 50. Every canary must have:

- a successful boundary status;
- exact terminal observation and a unique terminal-correlation digest;
- one unique authenticated provider audit identity;
- no duplicate or replayed provider request;
- a retained GNU-time resource record.

The target manifest records p50, p95, p99 and maximum wall latency plus p50,
p95, p99 and maximum RSS. These are bounded host measurements, not universal
service-level objectives.

## Independent evidence inputs

The protected runner receives source-bound JSON records for:

- target-host process/socket/generation identity;
- issuer key custody and exact process instance;
- durable anti-rollback recovery;
- canary and rollback rehearsal;
- independent acceptance review.

Each record uses its registered v1 schema, identifies the exact source SHA,
contains a nonzero subject digest, issuer identity and issue time, and has
`verified: true`. Test keys or repository-generated assertions cannot replace
these records.

## Canonical target-host manifest v3

`scripts/runtime_codex_target_host_evidence.py` validates the full inventory and
emits canonical JSON using schema
`hepta.runtime-codex-target-host-qualification.v3`. The manifest binds:

- source commit/tree and built binary digest;
- both verified source qualification receipts and attestation bundles;
- all canary output/log/resource digests and unique terminal correlations;
- provider audit digest;
- all five independent evidence records;
- all eight fault outputs and their operation/journal/provider/harness digests;
- performance and resource percentiles;
- an explicit claim ceiling keeping independent acceptance, activation,
  promotion and release false.

GitHub provenance attests the retained manifest bytes and workflow identity. It
does not substitute for the external authorities or grant operational approval.
Partial failure evidence is retained for diagnosis, but only a complete
canonical manifest is attested as a passing target-host result.
