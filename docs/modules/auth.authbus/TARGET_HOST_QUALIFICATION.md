# AuthBus target-host qualification contract

Repository CI proves source behavior on GitHub-hosted Linux runners. Production
activation additionally requires the unchanged candidate to execute on a
registered self-hosted target with the deployed kernel, filesystem, volume,
service identity and independently retained witness backend.

The manually dispatched workflow
`.github/workflows/authbus-target-host-qualification.yml` can run only from
`refs/heads/main`. It checks out the trusted main control SHA, never the supplied
candidate SHA. The candidate must already be an ancestor of that control SHA,
and the target workflow, crash/performance contracts and validator blobs must be
identical at candidate and control revisions.

Candidate execution belongs inside root-owned isolated harnesses. The workflow
runner executes only trusted controller scripts. Every raw receipt carries both
`candidateSha` and `controlSha`; validators reject either identity drifting.
The workflow has read-only repository permissions, no persisted Git credentials,
and cannot format, commit or push source.

## Root-owned harnesses

The runner must provide these executable, root-owned, non-group-writable and
non-world-writable harnesses:

- `/opt/hepta/authbus-qualification/enospc`
- `/opt/hepta/authbus-qualification/power-loss`
- `/opt/hepta/authbus-qualification/permission-loss`
- `/opt/hepta/authbus-qualification/restore-old-snapshot`
- `/opt/hepta/authbus-qualification/owner-collision`
- `/opt/hepta/authbus-qualification/wal-corruption`
- `/opt/hepta/authbus-qualification/backup-race`
- `/opt/hepta/authbus-qualification/trust-generation-mismatch`
- `/opt/hepta/authbus-qualification/fsync-failure`
- `/opt/hepta/authbus-qualification/rename-failure`
- `/opt/hepta/authbus-qualification/checkpoint-corruption`
- `/opt/hepta/authbus-qualification/performance`
- `/opt/hepta/authbus-qualification/kms-hsm`
- `/opt/hepta/authbus-qualification/key-rotation-revocation`
- `/opt/hepta/authbus-qualification/backup-restore`
- `/opt/hepta/authbus-qualification/owner-mount`
- `/opt/hepta/authbus-qualification/activation-plan`
- `/opt/hepta/authbus-qualification/rollback-plan`

A fault harness is invoked as:

```text
<harness> --candidate-sha <candidate> --control-sha <trusted-main> \
  --target-profile <profile> --output-dir <dir>
```

Single-output performance, production-drill and plan harnesses use `--output`
instead of `--output-dir`.

Fault harnesses write `<dir>/<scenario>.json` with schema
`hepta.authbus.target-host-scenario.v2`. A receipt includes the exact candidate,
trusted controller, immutable target and mount identities, start/end boot
identity, unique fault-injection identity, observed result and `passed: true`.

It must also report the observed commit state, retry rule, startup detection,
recovery action and read-service disposition. The trusted repository validator
compares those values exactly with
`docs/modules/auth.authbus/CRASH_CONSISTENCY_MATRIX.json`; a harness cannot
silently redefine the safety contract.

## Isolation requirements

A harness may build or execute the candidate only in the registered disposable
qualification target, VM, namespace or device. It must not source candidate
shell, Python or workflow code in the privileged controller process. Candidate
network access, credentials and host mounts are denied unless the individual
fault contract explicitly requires them. The raw receipt identifies the actual
target rather than merely the controller runner.

## Reality requirements

- Power-loss evidence must cross a real target boot identity. SIGKILL, process
  restart and an in-memory mock are insufficient.
- ENOSPC must be produced by the selected filesystem or volume layer.
- Permission loss must exercise the deployed UID/GID and path ownership model.
- Old-snapshot restore must restore a real prior database image while retaining
  the newer independent witness.
- Owner collision must use two real processes against the deployed lock inode.
- WAL corruption must be introduced against a disposable qualification copy and
  demonstrate fail-closed integrity checks.
- Backup race must overlap a real mutation/checkpoint publication and prove that
  no mismatched database/witness pair is accepted.
- Trust-generation mismatch must combine different database/checkpoint and
  issuer/trusted-time generations and demonstrate fail-closed startup.
- fsync, rename and checkpoint-corruption harnesses must exercise the deployed
  filesystem path, not only an in-process failpoint.

The workflow uploads raw receipts, the target fingerprint and one aggregate
manifest. Uploading an artifact does not grant acceptance. A separate security
identity must review and sign the exact manifest; the activation decision must
name that signature, candidate SHA and trusted control SHA.

## End-to-end performance

The performance harness executes the matrix in
`PERFORMANCE_QUALIFICATION.json`, retains raw samples and emits p50, p95, p99
and maximum latency for signature verification, authority validation, mutation
gate wait, SQLite transaction, frontier update, checkpoint publication,
reconciliation, product acknowledgement and the full caller-visible operation.
`authbus-performance-evidence.py` binds that receipt to the same candidate,
control SHA and target identity as the fault matrix. Production thresholds
remain an activation-owner decision.

## Production security and operations evidence

The protected target additionally supplies root-owned harnesses for KMS/HSM,
key rotation/revocation/recovery, backup/restore, dual-owner/wrong-mount,
activation planning and tested rollback. Their outputs are retained in the same
candidate-, control- and target-bound artifact as the fault and performance
receipts. They do not grant activation by themselves; the separately protected
production acceptance workflow requires independent security and operator
Ed25519 signatures over their exact digests.
