# AuthBus target-host qualification contract

Repository CI proves source behavior on GitHub-hosted Linux runners. Production
activation additionally requires the unchanged candidate to execute on a
registered self-hosted target with the deployed kernel, filesystem, volume,
service identity and independently retained witness backend.

The manually dispatched workflow
`.github/workflows/authbus-target-host-qualification.yml` is read-only and
protected by the `authbus-target-host-qualification` environment. It checks out
the exact requested SHA with no persisted Git credentials and cannot format,
commit or push source.

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

Each harness is invoked as:

```text
<harness> --candidate-sha <sha> --target-profile <profile> --output-dir <dir>
```

It writes `<dir>/<scenario>.json` with schema
`hepta.authbus.target-host-scenario.v2`. The receipt includes the exact
candidate, immutable target and mount identities, start/end boot identity,
unique fault-injection identity, observed result and `passed: true`.

It must also report the observed commit state, retry rule, startup detection,
recovery action and read-service disposition. The repository validator compares
those values exactly with
`docs/modules/auth.authbus/CRASH_CONSISTENCY_MATRIX.json`; a harness cannot
silently redefine the safety contract.

## Reality requirements

- Power-loss evidence must cross a real boot identity. SIGKILL, process restart
  and an in-memory mock are insufficient.
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
name that signature and the unchanged candidate SHA.

## End-to-end performance

The performance harness executes the matrix in
`PERFORMANCE_QUALIFICATION.json`, retains raw samples and emits p50, p95, p99
and maximum latency for signature verification, authority validation, mutation
gate wait, SQLite transaction, frontier update, checkpoint publication,
reconciliation, product acknowledgement and the full caller-visible operation.
`authbus-performance-evidence.py` binds that receipt to the same target identity
as the fault matrix. Production thresholds remain an activation-owner decision.
