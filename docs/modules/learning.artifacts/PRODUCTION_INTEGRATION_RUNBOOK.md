# learning.artifacts production integration runbook

## Scope and authority boundary

The supported production composition is:

```text
authenticated host transport
  -> action-level authorization
  -> LearningArtifactOwnerService
  -> LearningArtifactOwnerHost
  -> one trusted artifact root
```

Only `LearningArtifactOwnerService` is a supported mutable product entrypoint. A product must not expose the raw owner host, storage helpers, registry mutation, lifecycle journal, or filesystem root over a transport. This runbook grants no artifact selection, promotion, release, model execution, network, secret, or external-effect authority.

The crate's curated downstream API is `codex_hepta_learning_artifacts::stable`. Integrations should avoid importing low-level encoding and repair helpers from the crate root.

## Deployment layout

Use separate, private roots for:

- artifact data: payloads, registry snapshots, witnesses, head records, transaction checkpoints and writer lease state;
- host control state: transport identity, action authorization policy, audit receipts, readiness state and backup metadata;
- externally managed signing keys: never store private key material in either artifact root.

The artifact data root must be owned by the service account, not writable by readers, and protected against concurrent hostile replacement of any ancestor. On qualified Unix hosts, the service must require `DirectoryDurabilityProfileV1::UnixDirectorySync`. Other platforms remain fail-closed until their create, replace, delete and power-loss behavior is separately qualified.

## Startup sequence

1. Authenticate the configured artifact root and reject symlink roots, group/world-writable ancestors and unexpected ownership.
2. Acquire the unique process-lifetime writer fence before opening mutable state.
3. Load the trust bundle and verify the configured writer lease, signer identity, scope digest, epoch, validity window and revocation state.
4. Supply the independently retained required CURRENT head when a prior generation exists. Never derive that requirement from the candidate root being opened.
5. Open `LearningArtifactOwnerService`; replay transaction checkpoints, registry state, signed head chain, withdrawal state, lifecycle state and reservation state.
6. If recovery is required, expose liveness but keep readiness false. Permit only authenticated recovery/status operations.
7. Reconcile create-only zero-length orphans only through an explicitly authorized operation while the writer fence is held.
8. Verify that the recovered CURRENT head is not below the independent restart anchor and that no nonterminal publication is silently promoted.
9. Sync all publication directories and the root on a qualified target.
10. Mark readiness true only after recovery, trust, root, writer-fence and current-head checks have all succeeded.

A missing or corrupt current-head anchor, invalid signature, unsupported directory durability profile, unresolved publication, failed root ownership check or indeterminate I/O keeps the service unready.

## Authenticated transport and action authorization

Transport authentication and request framing are host responsibilities. Every command envelope must bind:

- protocol and schema version;
- request identity and idempotency identity;
- authenticated principal and credential/key digest;
- authority epoch and expiry;
- tenant/scope digest;
- action name;
- payload digest and bounded byte count;
- expected registry generation/head;
- request time and replay window.

Authorize actions independently. Suggested actions are:

```text
status.read
current.read
publication.submit
publication.recover
key.rotate
backup.checkpoint
orphan.reconcile
shutdown.drain
```

A publication principal does not automatically receive key rotation, backup, orphan cleanup or shutdown authority. Reader principals receive no filesystem handle and only opaque verified CURRENT views. Unknown fields, unknown actions, expired credentials, scope drift, epoch rollback, request replay with payload drift and oversize input are rejected before touching owner state.

## Publication and durability

The only valid publication order is:

```text
Prepared
  -> PayloadDurable
  -> RegistryDurable
  -> WitnessDurable
  -> Acknowledged
```

Persist each transaction checkpoint under the writer fence before treating that phase as durable. After `LearningArtifactOwnerService::publish` succeeds, call the qualified publication-directory synchronization boundary before returning host-level success. File creation alone is not acknowledgement.

For an I/O error after target creation, report an indeterminate result. Never overwrite, truncate, adopt or retry through the same final path. Reopen the service, recover the checkpoint and retry the same semantic operation identity. A different payload under the same identity is a conflict.

## Process-kill recovery drill

Run the following against the selected filesystem and mount options, not only a temporary directory:

1. Start the writer and record its exact trust/root/configuration digest.
2. Submit one publication with a fixed operation identity.
3. At each side-effect boundary—before/after payload write, registry write, witness write, CURRENT publication, transaction checkpoint and acknowledgement—terminate the process with `SIGKILL`.
4. Restart with the same independent required CURRENT anchor.
5. Verify recovery reports the exact last durable phase.
6. Retry the identical operation.
7. Verify exactly one payload, one accepted registry extension, one signed head-chain extension and one terminal receipt.
8. Verify registry/head/refcount/reservation state is mutually consistent.
9. Restore an older root copy and verify the independent CURRENT anchor rejects rollback.
10. Repeat under disk-full, quota, permission, lock contention and interrupted directory-sync faults.

Target-host qualification records filesystem type, mount options, kernel/runtime version, storage stack, power-loss method and resulting receipt digests.

## Health endpoints

Liveness means the process can answer a bounded status request. It does not imply the writer is usable.

Readiness requires all of:

- unique writer fence held;
- trust and writer lease current;
- root and durability profile accepted;
- no unresolved recovery or indeterminate write;
- current-head restart anchor verified;
- audit sink available;
- resource ceilings below configured stop thresholds.

Return explicit reason codes rather than one Boolean. A failed readiness check closes mutable routes.

## Graceful shutdown

1. Stop accepting new mutable requests.
2. Allow the current serialized publication either to reach a durable checkpoint or to return indeterminate.
3. Persist final audit and health records.
4. Sync transaction/head/audit directories.
5. Release the writer fence only after all handles are closed.
6. Never write a synthetic success receipt during shutdown.

## Key rotation

Rotation is a separately authorized action. Introduce a higher authority epoch, verify overlap rules, publish and retain the new public trust material, rotate the writer lease, and restart or atomically activate the new configuration. Old keys remain available only for historical signature verification until retention policy permits destruction. Epoch rollback and a different key at the same epoch are rejected.

## Backup and restore

Back up immutable payloads, registry/head/witness chains, transaction checkpoints, withdrawal/lifecycle state, receipts and the independent CURRENT anchor. Do not back up signing private keys with artifact data.

A restore is admitted only after:

- full digest verification;
- restoration of the independent CURRENT anchor from a separate trust domain;
- withdrawal/tombstone freshness verification;
- target-host directory synchronization;
- read-only recovery first;
- explicit operator acceptance before mutable readiness.

An old internally consistent backup is not current and must fail against a newer independent anchor.

## Deployment gate

Production activation requires all of:

- green `learning.artifacts exact-head required` for the exact commit;
- green Lane E exact-source and ordered-parent merge qualification;
- candidate-bound receipts whose checks are all `success`—never skipped;
- target-host directory and power-loss qualification;
- authenticated transport and action-authorization review;
- backup/restore and key-rotation rehearsal;
- independent security review;
- canary and operator acceptance.

Source implementation or a green repository workflow alone does not grant activation, promotion or release.
