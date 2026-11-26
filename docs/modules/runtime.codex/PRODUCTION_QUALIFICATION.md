# runtime.codex production qualification

This document is the closed-world qualification contract for `runtime.codex`.
Repository source can implement and verify evidence formats, but it cannot
self-certify the external principals, target host, real provider, acceptance
authority or release decision described here.

## 1. Repository source gates

Both lanes are mandatory for the exact candidate:

- `runtime.codex exact-head`
- `runtime.codex synthetic-merge`

The synthetic merge is the deterministic ordered-parent tree produced from the
current base and source. Each lane must finish successfully and retain a
canonical machine-readable receipt, raw command records, bounded logs, SHA-256
sidecar and workflow attestation bundle. A missing, skipped, cancelled,
timed-out, dirty, malformed, under-floor or nonzero record is a failed lane.

The closed-world receipt inventory includes:

- runtime binaries;
- adapter terminal/correlation/deadline/recovery tests;
- durable native journal, abort, rejection, reopen and no-replay tests;
- Agent protocol and lifecycle tests;
- worker-host authority, issuer identity, cancellation, deadline, owner-loss,
  typestate and thread-cleanup tests;
- the executable 22-cut `runtime_codex_crash_matrix` test binary;
- the signed quarantine-resolution protocol tests;
- real repository Agentd/App Server product composition against a controlled
  provider, proving one physical request;
- the model-only tool-topology test;
- strict Clippy and formatting.

The required `CI required` aggregate consumes the reusable runtime.codex
qualification job for inference-impacting changes. Direct qualification runs on
the canonical branch additionally produce the attestation bundles required by
target-host qualification. Branch-protection administration remains an
independent repository-control fact and must be inspected separately.

## 2. Effect-entry and recovery contract

Before production, source and evidence must establish:

- final owner/ingress, context, cancellation, deadline, revocation and
  `VerifiedUseToken::enter` checks precede the server-owned fence;
- Agentd's exact `RunMarkDispatchedExact` CAS accepts only `ContextAttached` and
  binds run, dispatch digest, revision and generation;
- only a fresh, exact, non-idempotent ACK creates one non-transferable send
  permit;
- idempotent/lost/mismatched/stale responses create no send permit;
- the local one-shot abort proof cannot survive a fence whose commit may be
  unknown, and Agentd rejects post-fence abort;
- typed non-admission settles Agentd before local capacity release;
- terminal facts become durable before thread cleanup and settle both owners
  exactly/idempotently;
- missing App Server history remains quarantined, never inferred absent;
- original-operation replay is impossible.

The repository 22-cut model proves transition invariants. Selected real process
cuts and the external eight-scenario harness prove implementation behavior.
Neither may substitute for the other.

## 3. Final-use issuer and key custody

Production evidence establishes:

- an independently operated issuer service and private-key custody unavailable
  to worker, Agentd and repository jobs;
- signer rotation and emergency revocation procedures;
- protected socket ancestry and connected peer UID;
- exact Linux issuer PID, process start time, executable digest, cgroup digest
  and host boot-id digest sampled before and after the exchange;
- trusted time with bounded uncertainty;
- monotonic revocation distribution and stale-frontier detection;
- external anti-rollback checkpoints and rehearsed restore;
- forged grant, stale epoch, nonce replay, key substitution, socket replacement,
  same-UID impersonation and process-restart tests.

A locally generated key, UID-only check or successful unit test is not this
gate.

## 4. Target-host identity

The selected profile binds:

- immutable/measured host identity, OS/kernel, architecture and sandbox;
- service units, cgroups, namespaces, mounts and socket identities;
- Agentd/App Server/worker binary and configuration digests;
- exact Agent id/generation, App Server protocol/version and Codex home;
- durable filesystem identity plus qualified rename/fsync behavior;
- final-use and quarantine authority frontiers;
- provider account, endpoint, model and audit exporter identity;
- accepted release and rollback identities.

Any identity-changing update creates a new target-host profile.

## 5. Real provider and fault matrix

The protected workflow consumes a direct signed repository-qualification run
for the same source SHA. It then executes 30–200 real-provider canaries (default
50) and all eight scenarios from
[`TARGET_HOST_FAULT_HARNESS.md`](TARGET_HOST_FAULT_HARNESS.md):

1. provider acknowledgement loss;
2. event lag/disconnect;
3. worker kill after the effect-entry fence;
4. worker restart;
5. Agentd restart;
6. revocation advance before entry;
7. duplicate owner;
8. stale revision/digest drift.

The authenticated provider audit proves one unique request per successful
canary and the scenario-specific zero/one-send contract. Every fault output
binds source, operation, owner revision, fresh fence count, capacity posture,
journal digest, provider audit digest and harness digest.

The workflow also verifies independently issued host identity, issuer custody,
anti-rollback, canary/rollback and independent-review records. It emits and
attests a canonical
`hepta.runtime-codex-target-host-qualification.v3` manifest. The manifest's
claim ceiling leaves independent acceptance, activation, promotion and release
false.

## 6. Quarantine and resolution

The deployment operates `QUARANTINE_AND_RELEASE.md` with an independent signer
and externally checkpointed monotonic frontier. Demonstrate:

- unavailable history retains operation ownership/capacity;
- unsigned/manual release is rejected;
- wrong operation/request/dispatch/evidence digest, stale revision/sequence,
  wrong authority epoch, expired validity and nonce reuse fail closed;
- exact late terminal evidence can settle without rewriting history;
- abandonment never permits original-operation replay;
- a replacement has a distinct operation id, exactly one attempt, a provider
  idempotency key and any required compensation prerequisite;
- operator UI/API cannot bypass the verifier.

Restore, migration and failover preserve all unresolved records and frontiers.

## 7. Performance and capacity

Retain exact raw samples and the release/host identity for:

- final-use issuer latency;
- local durable prepare/fsync and owner CAS latency;
- App Server thread/start and turn/start admission;
- provider queue, first-token and terminal latency;
- same-connection and restart reconciliation;
- end-to-end p50, p95, p99 and maximum;
- CPU, RSS, file/socket/event depth and journal growth;
- orphan-thread cleanup, unresolved capacity and quarantine age;
- overload behavior and recovery time.

Admission, timeout, queue and alert thresholds derive from the selected profile.
Repository benchmark output is only a source-candidate baseline.

## 8. Canary and rollback

The canary plan names operation count, concurrency, duration, stop conditions,
rollback digest and independent approver. Immediate stop conditions include:

- duplicate/replayed physical request or more than one fresh fence winner;
- post-fence abort acceptance;
- authority, process identity, time or revocation failure;
- owner/local dispatch divergence or revision rollback;
- terminal success without current owner authority;
- journal/frontier corruption or lost unresolved operation;
- unbounded resource, orphan or quarantine growth;
- model/tool capability outside the registered model-only profile.

Rollback is rehearsed with live unresolved and terminal records. It never
deletes journals, resets epochs/sequences, reuses old socket/process identity or
relabels an unknown effect. Predecessor compatibility or a deterministic
compatible snapshot is mandatory.

## 9. Independent acceptance and release

The acceptance record binds repository receipts and attestations, target-host
manifest, external identity/key/anti-rollback evidence, provider fault results,
performance profile, quarantine inventory, canary and rollback receipts and all
reviewer decisions. It names scope, expiry and the exact release digest.

These facts remain false until the independently signed record exists and
verifies:

- independent acceptance complete;
- activation approved;
- promotion approved;
- release approved.

No commit message, pull request text, branch administrator exception, generated
receipt, source test or GitHub attestation may set them true.
