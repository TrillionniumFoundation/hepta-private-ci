# runtime.codex production qualification

This document is the closed-world production qualification contract for `runtime.codex`. Repository source can prepare and verify evidence, but it cannot self-certify the external principals, target host, provider, acceptance authority or release decision described here.

## 1. Required repository gates

Both checks are mandatory for the exact candidate proposed for integration:

- `runtime.codex exact-head`
- `runtime.codex synthetic-merge`

Each check must complete successfully, not be skipped or cancelled, and retain a canonical machine-readable receipt, SHA-256 sidecar, raw command records and logs. The synthetic merge must have ordered parents `[base, source]` and a tree independently recomputed by `git merge-tree --write-tree`. The workflow attestation is evidence of GitHub workflow execution only; it is not target-host or independent acceptance.

Required repository suites include:

- adapter terminal, correlation, deadline and recovery tests;
- durable admission/dispatch/abort/reopen tests;
- Agentd run-state and exact-dispatch tests;
- native caller, authority, cancellation, deadline and owner-loss tests;
- real Agentd/App Server product composition against a controlled provider;
- strict lint and formatting checks;
- receipt-verifier tests;
- the crash-injection obligations in `CRASH_INJECTION_MATRIX.md` as they become executable.

## 2. Final-use issuer and key custody

Production evidence must establish:

- independently operated issuer service identity;
- signer private key in approved custody, unavailable to worker/Agentd/repository jobs;
- signer rotation and emergency revocation procedures;
- protected socket ancestry and connected peer/process identity;
- issuer boot identity and failover semantics;
- trusted time source and bounded clock uncertainty;
- monotonic revocation distribution and stale-frontier detection;
- external anti-rollback checkpoints and rehearsed restore;
- forged grant, stale epoch, nonce replay, key substitution, socket replacement and same-UID impersonation tests.

A local verifying key, UID check or successful unit test alone is insufficient.

## 3. Target-host identity

The selected host profile binds:

- immutable host or measured workload identity;
- OS/kernel, architecture and sandbox features;
- Agentd binary/configuration digest and generation;
- App Server binary/configuration digest, socket identity, version and Codex home;
- worker binary/configuration digest;
- cgroup/service-unit and namespace identities;
- durable filesystem/mount identity and fsync/rename qualification;
- provider network egress identity;
- release and rollback digests.

Qualification is repeated after any identity-changing update. A different host image, socket owner, namespace, filesystem or service unit is a new profile.

## 4. Real provider qualification

Run the named caller against the selected real provider/account/endpoint and retain authenticated evidence for:

- exactly one physical request for one authorized operation;
- exact model/provider selection or explicit substitution rejection;
- streaming terminal and usage correlation;
- overload before admission;
- invalid request rejection;
- provider 5xx and unclassified errors;
- connection reset before, during and after request write;
- acknowledgement loss with a provider-side accepted request;
- delayed/duplicated/reordered terminal events;
- cancellation and deadline after admission;
- process kill and host restart;
- quota exhaustion and rate limiting;
- absence of model-visible tools for the model-only profile;
- secret and payload redaction in all retained evidence.

A mock provider proves product composition but not this gate.

## 5. Quarantine and recovery

The deployment must operate the protocol in `QUARANTINE_AND_RELEASE.md` with an independent signer and anti-rollback frontier. Demonstrate:

- App Server history loss leaves the operation quarantined;
- capacity is not silently freed;
- same-operation replay is impossible;
- unsigned/manual release is rejected;
- stale revision, stale sequence, wrong evidence digest and nonce reuse are rejected;
- late exact terminal evidence is reconciled without rewriting history;
- a separately authorized new operation has a new identity and explicit constraints.

Restore, migration and regional failover exercises must preserve every unresolved operation and frontier.

## 6. Performance and capacity

Measure representative concurrency and workload distributions on the selected host. Retain exact release identity and raw samples for:

- final-use authority latency;
- durable prepare/fsync latency;
- Agentd dispatch and terminal RPC latency;
- App Server thread/start and turn/start admission;
- provider queue, first token and terminal latency;
- same-connection and restart reconciliation;
- end-to-end p50, p95 and p99;
- CPU, RSS, open files, socket/event queue depth and journal growth;
- overload behavior and recovery time.

Set admission, timeout, queue and alert thresholds from those measurements. Repository benchmark output is only a source-candidate baseline.

## 7. Canary

The canary plan specifies traffic fraction, maximum operations, duration, stop conditions, rollback digest and independent approver. Immediate stop conditions include:

- any duplicate physical request;
- authority or revocation validation failure;
- owner/local dispatch divergence;
- terminal success without final owner readiness;
- journal corruption or lost unresolved operation;
- unbounded queue/resource growth;
- release without independent resolution;
- provider/tool capability outside the registered profile.

Canary continuation and widening require independently signed decisions. Automation may recommend; it may not self-approve.

## 8. Rollback and anti-rollback recovery

Before activation, rehearse rollback with live unresolved and terminal records. Prove:

- predecessor schema compatibility or a deterministic compatible restore;
- no deletion or reinterpretation of indeterminate operations;
- authority, revocation and quarantine frontiers do not move backward;
- old binaries cannot accept new incompatible records as success;
- restored hosts rebind issuer, Agentd, App Server, filesystem and provider identities;
- rollback canary and independent approval complete before admissions reopen.

## 9. Independent acceptance and release

The independent acceptance record binds all repository receipts, target-host profiles, external signer evidence, real-provider fault results, performance baseline, canary, rollback and unresolved quarantine inventory. It names the accepting authority, scope, expiry and release digest.

The following remain false until that record exists and verifies:

- deployment qualification complete;
- independent acceptance complete;
- activation approved;
- promotion approved;
- release approved.

No commit message, pull request text, branch administrator exception, generated receipt or repository test may set these facts to true.
