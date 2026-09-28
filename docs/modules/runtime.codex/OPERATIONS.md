# runtime.codex operations runbook

This runbook covers repository qualification, protected target-host execution,
canary, incident response and rollback for the named `runtime.codex` caller. It
does not grant deployment authority. Source qualification, target-host
qualification, independent acceptance, activation, promotion and release remain
separate decisions.

## 1. Components and owners

- Codex App Server owns the canonical thread/turn/model execution spine.
- `hepta-codex-adapter` validates request/terminal correlation and retry posture;
  it grants no model/provider authority.
- `hepta-infer-worker-host` is the named caller and consumes final-use authority
  at the server-owned effect-entry boundary.
- `hepta-infer-core` owns the durable local operation/dispatch/observation
  journal.
- Agentd owns generation, App Server ingress and the exact effect-entry/terminal
  lifecycle.
- Final-use issuer, provider audit exporter and quarantine authority are
  independently operated. Their private keys and approval authority are absent
  from worker, Agentd and repository jobs.

## 2. Repository qualification

Follow [`QUICKSTART.md`](QUICKSTART.md). The authoritative path is
`.github/workflows/runtime-codex-qualification.yml`, which runs exact-head and
deterministic synthetic-merge lanes from a clean checkout. The closed-world
inventory is `scripts/runtime_codex_receipt_v2.py` and includes the 22-cut crash
and quarantine protocol targets.

Inspect a retained bundle with:

```bash
python3 scripts/runtime_codex_receipt_v2.py verify-bundle \
  receipt.json \
  --records records \
  --bundle attestation.jsonl \
  --repository TrillionniumFoundation/hepta-private-ci \
  --signer-workflow .github/workflows/runtime-codex-qualification.yml
```

Both lanes must be `passed` for the same source SHA. A valid signature on a
failed receipt remains a failure.

## 3. Protected host prerequisites

Before starting services, independently verify:

- accepted source/tree, binary, lockfile, toolchain and configuration digests;
- host boot, kernel, service-unit, cgroup, namespace and mount identities;
- Agentd/App Server/worker identities and generation;
- final-use issuer signer/key custody and exact process instance;
- protected socket ancestry and peer UID/PID/start/executable/cgroup/boot
  identity;
- trusted time, monotonic revocation distribution and anti-rollback checkpoint;
- durable journal and quarantine-frontier integrity;
- real provider account/endpoint/model and authenticated audit exporter;
- rollback binary/configuration/frontier identity.

Keep admissions closed on any mismatch. There is no fallback issuer, socket,
state directory, provider or model.

## 4. Startup order

1. Verify source receipts, attestations and accepted release record.
2. Restore/check external anti-rollback checkpoints.
3. Establish trusted time and revocation distribution.
4. Start final-use issuer and record its exact process instance.
5. Start quarantine authority, where applicable.
6. Start Agentd fenced; verify workspace/home/run roots and generation.
7. Let Agentd create/own App Server ingress.
8. Start worker with admissions closed.
9. Verify journal schema/integrity/capacity and all authority frontiers.
10. Verify issuer socket and process identity before/after a bounded probe.
11. Verify model-only tool topology.
12. Execute protected target-host qualification.
13. Rehearse canary and rollback.
14. Open admissions only after independent acceptance of the exact release.

## 5. Target-host qualification

Use `.github/workflows/runtime-codex-target-host.yml` with:

- exact `source_sha`;
- direct signed source-qualification run id;
- exact Agentd socket/id/generation/model;
- protected final-use configuration and journal root;
- 30–200 canaries (default 50).

The runner must expose independently provisioned environment paths for host
identity, issuer custody, anti-rollback, canary/rollback and independent-review
evidence, plus authenticated provider-audit and fault-runner executables.

The workflow verifies source receipts/attestations, executes all canaries and
eight faults, retains partial failure evidence, emits canonical target-host V3
JSON and attests only a complete passing manifest.

## 6. Canary policy

Bind the canary to source/binary/configuration/host/issuer/provider/generation
and rollback identities. Explicitly cap operation count, concurrency and time.

Required observations:

- one fresh effect-entry winner and at most one physical request per operation;
- unique provider audit and terminal-correlation identities;
- exact terminal/usage correlation;
- no post-fence abort or original-operation replay;
- cancellation/deadline/owner-loss remain non-success;
- unknown ACK/process loss retains operation ownership;
- no model-visible or registered tools;
- bounded p95/p99 latency/RSS and no unexpected orphan/quarantine growth.

Stop immediately on duplicate/replay, more than one fresh winner, owner revision
rollback, authority/process/frontier mismatch, journal corruption, false success,
unbounded resource growth or capability expansion. Traffic widening requires a
new independent decision.

## 7. Observability

Emit bounded structured events/metrics for:

- admission and local/Agentd revision transitions;
- dispatch/request/payload/authority/correlation digests;
- signer id, epoch and revocation-head digest;
- effect-entry ACK class and physical-send attempt count;
- overload, rejection, timeout, cancellation, owner loss and quarantine;
- same-connection/restart reconciliation attempts/results;
- terminal settlement and owner/local convergence;
- thread cleanup attempts, failures/orphans and retained unknown history;
- unresolved count/oldest age and quarantine count/oldest age;
- p50/p95/p99/max latency, CPU/RSS/files/socket/event/journal profile.

Do not log private keys, bearer credentials, full prompts, unrestricted output,
raw memory/context or unredacted provider responses.

## 8. Immediate alert classes

Page on:

- duplicate or replayed provider request;
- more than one fresh fence winner;
- accepted post-fence abort;
- local/Agentd digest or revision divergence;
- signature, issuer process, time or revocation failure;
- anti-rollback mismatch;
- terminal success without current owner authority;
- release/replacement without verified quarantine envelope;
- durable-store corruption or failed settlement;
- unresolved/quarantine age or capacity beyond policy;
- sustained orphan-thread growth.

## 9. Incident playbooks

### Fence acknowledgement unknown

Do not send. Preserve local/owner state and exact dispatch digest. Query Agentd:
`ContextAttached` may still permit the original live abort proof; exact
`Dispatched` is reconciliation only. An idempotent receipt cannot mint a send
permit.

### `turn/start` acknowledgement unknown

Stop retries. On the original connection consume only an exact
`turn/started`. After restart authenticate the original generation and use
`thread/read(includeTurns=true)` matching both stable client-message id and
original user input. Mismatch/multiplicity/missing history is conflict or
quarantine, not “not sent”.

### Typed pre-admission rejection

Verify registered rejection class and response digest. Commit exact Agentd
terminal rejection first; release local capacity only after matching owner ACK.
Unknown owner ACK retains the slot for reconciliation.

### App Server history unavailable

Quarantine under [`QUARANTINE_AND_RELEASE.md`](QUARANTINE_AND_RELEASE.md).
Retain ownership/capacity/evidence. Only a verified independent envelope may
record exact terminal evidence, abandon without replay, or authorize a distinct
one-shot replacement.

### Issuer unavailable or identity drift

Reject before effect and close admissions. Never use a local signer, cached
unsigned proposal or permissive mode. Validate release/unit/socket/process/key
custody/epoch/frontier/anti-rollback before recovery.

### Durable store failure

Close admissions and preserve the last checkpoint/evidence. Repair/restore only
through the qualified procedure. Never delete unknown operations to regain
capacity.

## 10. Rollback

1. Close admissions.
2. Finish exact pre-effect compensation only for definitely-unsent work.
3. Interrupt/reconcile started work without replay.
4. Quarantine unresolved effects.
5. Verify predecessor schema compatibility or restore a compatible snapshot and
   independently checkpointed frontiers.
6. Start predecessor generation fenced with new exact process/socket identity.
7. Re-establish issuer, Agentd/App Server and provider identities.
8. Run rollback canaries.
9. Reopen only after independent approval.

Rollback never deletes journals, resets epochs/revisions/sequences, reuses stale
socket identity or relabels unknown effects.

## 11. Acceptance handoff

The handoff package contains:

- both source receipts and attestation bundles;
- target-host V3 manifest/provenance and raw evidence;
- host/process/socket and issuer custody records;
- trusted time/revocation and anti-rollback evidence;
- provider audit/fault results and resource baseline;
- quarantine inventory/frontier;
- canary/rollback receipts;
- security/runtime/operations reviews;
- independent acceptance record.

Absent, stale or failed elements remain false. No maintainer, workflow or
generated document can self-grant activation, promotion or release.
