# runtime.codex production qualification and acceptance

Repository CI can establish source correctness for an exact candidate. Production qualification requires independently operated target-host evidence. This document defines the gate; it does not mark it passed.

## 1. Candidate identity

Every run binds:

- exact Git commit and tree;
- deterministic merge-candidate commit and tree;
- lockfile and toolchain digests;
- source-object digests for the App Server, adapter, worker, journal, authority port and Agentd owner;
- build artifact digests;
- host image/kernel/service profile;
- configuration and schema revisions.

A changed field creates a new candidate.

## 2. Required environments

1. repository exact-head source lane;
2. deterministic merge candidate against the current protected base;
3. isolated target-host qualification environment;
4. limited canary cohort;
5. production cohort after independent acceptance.

Mock-provider evidence is retained but cannot substitute for environment 3.

## 3. Issuer and key custody

Independently verify:

- signer identity and public key;
- private key held outside the worker and App Server principals;
- HSM/KMS or equivalent custody and access audit;
- dedicated issuer service UID;
- socket path, full parent chain, peer PID, executable digest, service unit/cgroup, boot identity and process start identity where supported;
- nonce replay rejection;
- authority epoch and revocation rollback rejection;
- trusted time and maximum uncertainty;
- backup/restore anti-rollback procedure.

Exercise wrong UID, same-UID wrong process, socket replacement, stale process, wrong executable, wrong boot, forged signature, expired grant, revoked grant, nonce reuse and frontier rollback.

## 4. Real provider fault matrix

Using the selected provider/account/model and the named product caller, inject or reproduce:

- normal completion, terminal failure and interruption;
- overload before admission;
- invalid request and policy rejection;
- connection loss before write, during write and after write;
- ACK loss after provider admission;
- delayed first token and delayed terminal event;
- duplicate or reordered events;
- event-stream lag and disconnect;
- worker kill, App Server kill, Agentd kill and host reboot at every durable boundary;
- owner generation replacement;
- cancellation/deadline before and after admission;
- provider completion after boundary cancellation;
- lost App Server history;
- provider-side idempotency lookup where available.

For every case retain packet/process timing, journal records, owner records, provider IDs, terminal evidence and the final disposition. Exactly-once effect claims require provider evidence, not request-count inference alone.

## 5. Crash-injection boundaries

At minimum inject immediately before and after:

1. native reservation append/fsync;
2. native dispatch append/fsync;
3. Agentd bound-dispatch request write and response read;
4. local `AbortPending` append/fsync;
5. Agentd abort request write and response read;
6. local abort confirmation append/fsync;
7. final-use token entry;
8. App Server socket request write;
9. `turn/started` observation;
10. local `native_started` append/fsync;
11. cancellation intent append/fsync;
12. terminal observation append/fsync;
13. Agentd terminal reconciliation request/ack;
14. thread unsubscribe and process shutdown.

The oracle is the state-machine invariant, not a boolean test return.

## 6. Concurrency and ownership stress

Run sustained tests for:

- two workers attempting one operation;
- stale expected revision;
- duplicate owner response and lost response;
- owner generation replacement;
- capacity exhaustion with active quarantine;
- restart loops while abort or terminal reconciliation is pending;
- simultaneous cancellation and completion;
- deadline and revocation frontier advance at final-use entry;
- thread/session replacement;
- high event volume causing channel lag;
- repeated same-semantics idempotent calls and changed-semantics conflicts.

No test may recover by clearing state.

## 7. Performance and resource baseline

Measure warm and cold distributions for:

- authority claim;
- durable reservation and dispatch fsync;
- owner dispatch and abort RPC;
- payload assembly and context revalidation;
- App Server thread start and turn start;
- provider queue, first token and terminal event;
- same-connection and post-restart reconciliation;
- cleanup and quarantine operations.

Report p50, p95, p99, maximum, sample count and confidence interval where applicable. Also report CPU, RSS, file descriptors, journal growth, fsync rate, socket backlog, event-channel occupancy and cache behavior. Bounds become enforced only after the selected profile is accepted.

## 8. Canary

The canary plan declares:

- exact candidate and host cohort;
- maximum request rate and concurrency;
- permitted models/providers;
- no external tools for the native inference identity;
- observation duration;
- stop conditions;
- rollback binary/state pair;
- on-call ownership;
- quarantine capacity.

Immediate stop conditions include duplicate effects, identity drift, journal failure, signer/frontier failure, clock rollback, unresolved cleanup growth or a success without exact correlation.

## 9. Rollback rehearsal

Rehearse rollback with active records in every nonterminal state. The predecessor must parse all durable records or a deterministic forward-compatible migration must complete before rollback. Verify that rollback preserves abort/quarantine proofs and cannot resurrect a released, revoked or superseded operation.

## 10. Independent acceptance

Acceptance evidence is produced by an actor independent of the source implementer and runtime generator. It reviews:

- source and dependency candidate identity;
- all required receipts and skips;
- real-provider/target-host fault evidence;
- security and key-custody evidence;
- performance profile;
- canary and rollback results;
- unresolved risks and exceptions.

Acceptance, activation, promotion and release are separate signed decisions. A CI pass cannot set them true.

## 11. Current gate status template

```json
{
  "sourceExactHead": false,
  "syntheticMerge": false,
  "targetHostIdentity": false,
  "productionIssuerAndKeyCustody": false,
  "trustedTimeAndRevocation": false,
  "realProviderFaultMatrix": false,
  "performanceBaseline": false,
  "canary": false,
  "rollbackRehearsal": false,
  "independentAcceptance": false,
  "activation": false,
  "promotion": false,
  "release": false
}
```

Automation may change a field only from retained evidence for the exact candidate and authorized signer class.
