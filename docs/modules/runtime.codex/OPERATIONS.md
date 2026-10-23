# runtime.codex deployment and operations runbook

This runbook describes the target operational contract. Values such as timeouts, capacity and alert thresholds must be measured for the selected host and provider.

## 1. Deployment topology

A production deployment has distinct principals for:

1. Agentd/App Server owner;
2. native inference worker;
3. final-use issuer and signer-key custody;
4. resolution/quarantine authority;
5. operator and auditor roles.

The final-use issuer should use a dedicated service UID and protected Unix socket. The worker receives only the public verification key and cannot read the issuer private key. The owner journal, worker journal and authority state each use owner-private directories and must not share a writable parent with an untrusted process.

## 2. Filesystem and socket requirements

- absolute paths only;
- no symlink traversal for protected configuration;
- configuration files owned by root or the service owner, one hard link, not group/world writable;
- socket parent chain not writable by unsafe principals;
- socket peer credentials checked after connection;
- target-host profile pins expected service UID, executable digest, boot/process generation and cgroup or service-unit identity where supported;
- journal directories mode `0700`; files mode `0600`;
- backups encrypted and access-controlled separately from live services.

UID equality alone is not sufficient process identity for production acceptance.

## 3. Time and revocation

The runtime uses a monotonic execution budget anchored to a trusted wall-clock observation. Wall-clock rollback, an authority frontier rollback, an epoch rollback or an untrusted restore fails closed.

Production must provide:

- authenticated time synchronization and alerting;
- maximum tolerated clock uncertainty;
- monotonic authority epoch and revocation revision;
- an external anti-rollback anchor;
- a documented recovery procedure for host restore or relocation.

A local state directory or backup is not an independent freshness oracle.

## 4. Startup order

1. Restore and verify external anti-rollback frontiers.
2. Start the final-use issuer and verify key identity, socket ownership, process identity and trusted time.
3. Start Agentd for one workspace generation.
4. Start the existing App Server under Agentd and verify the registered home, session ingress and generation.
5. Open the native journal and reconcile every `AbortPending`, `Dispatching`, `Running`, `Cancelling` and `Indeterminate` record before accepting new work.
6. Start the worker with explicit bounded capacity.
7. Run a no-effect health probe.
8. Enable admission only after all required identities and frontiers match.

Startup never deletes unresolved records to become ready.

## 5. Shutdown and drain

1. Close new admission.
2. Request cancellation for admitted but unsent work.
3. Complete exact pre-effect abort sagas.
4. Interrupt entered turns and continue terminal reconciliation for the bounded grace period.
5. Persist remaining unresolved work as indeterminate/quarantined.
6. Flush journals and evidence receipts.
7. Stop App Server, Agentd and issuer in dependency order.

A shutdown timeout changes an unresolved operation to quarantine; it does not make the operation safe to replay.

## 6. Health signals

### Ready

Ready requires all of:

- exact Agentd generation and ingress;
- App Server initialized version and Codex home match;
- final-use issuer reachable and identity-pinned;
- authority/revocation frontier current;
- durable journals writable and below capacity thresholds;
- no anti-rollback conflict;
- admission enabled.

### Degraded

Degraded but serving may be allowed only for explicitly registered conditions such as elevated latency below the deadline budget. Provider event loss, journal write failure, owner identity loss, clock rollback, revocation rollback or unresolved capacity exhaustion are not degraded states; they close admission or fence success.

## 7. Alerts

Page immediately on:

- any duplicate-effect conflict;
- owner generation or socket identity drift during a run;
- journal append/fsync failure;
- authority signature, epoch, nonce or revocation failure;
- trusted-time rollback or uncertainty beyond policy;
- first unresolved `AbortPending` beyond its short reconciliation objective;
- first provider event-stream loss in production;
- quarantine capacity above 50%;
- orphan thread cleanup growth;
- any success receipt missing exact terminal correlation.

Ticket-level alerts include latency budget erosion, repeated pre-admission overload and low remaining journal capacity.

## 8. Troubleshooting

### `AbortPending` does not close

- query Agentd run status using the original run identity;
- compare dispatch binding and nonce commitment;
- if Agentd is still exact `Dispatched`, replay the stored proof;
- if Agentd is exact `AbortedBeforeEffect`, confirm locally;
- any different binding, revision or proof is a conflict and requires quarantine.

Do not issue `turn/start` while `AbortPending` exists.

### `turn/start` timed out

- retain the slot;
- inspect same-connection `turn/started` observations;
- after restart use exact `thread/read(includeTurns=true)`;
- require one matching stable client-message ID and original input;
- duplicate, mismatched or missing history remains quarantined.

### completed provider event but boundary is quarantined

Check owner readiness/generation and terminal correlation. Provider completion remains a useful fact but cannot restore authority lost earlier in the attempt.

### final-use issuer unavailable

Close effect admission. Do not add a local allow fallback, cached unsigned grant or worker-held signing key.

### journal capacity exhausted

Close admission, investigate unresolved records and expand capacity only through a reviewed profile. Never truncate unresolved records.

## 9. Backup and restore

Backups include journals, schema versions, source candidate identity, authority/revocation frontiers, resolution frontiers and signer metadata. Restore into an isolated environment first. Compare restored frontiers with the external anchor and reject rollback. Reconciliation precedes admission.

## 10. Canary and rollback

A canary uses a named host cohort, bounded rate and predeclared stop conditions. Rollback restores a binary and state schema pair capable of interpreting every existing durable record. Rollback never rewrites or drops an unknown operation. See `PRODUCTION_QUALIFICATION.md` for the evidence gate.
