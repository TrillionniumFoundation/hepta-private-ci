# AuthBus target-host qualification contract

Repository CI proves source behavior on GitHub-hosted Linux runners. Production
activation additionally requires an unchanged candidate to execute on a
registered self-hosted target with the real filesystem, volume, kernel, service
manager and independently retained witness backend.

The manually dispatched workflow
`.github/workflows/authbus-target-host-qualification.yml` is intentionally
fail-closed. A runner must provide four root-owned harnesses:

- `/opt/hepta/authbus-qualification/enospc`
- `/opt/hepta/authbus-qualification/power-loss`
- `/opt/hepta/authbus-qualification/permission-loss`
- `/opt/hepta/authbus-qualification/restore-old-snapshot`

Each harness receives the exact candidate SHA, target profile and output
directory. It must emit one JSON receipt with the declared scenario, exact
candidate SHA, immutable target identity, start/end boot identity, fault
injection identity, observed result and `passed: true`. The repository validator
rejects missing fields, scenario substitution, candidate drift, target identity
mismatch and non-passing results, then hashes the raw receipts into one
qualification manifest.

The power-loss harness must use a real qualified power-cut or storage fault
facility. `SIGKILL`, process restart and an in-memory mock do not satisfy that
scenario. ENOSPC must be produced by the selected filesystem/volume layer.
Permission loss must exercise the deployed UID/GID and path ownership model.
Old-snapshot restore must restore an actual prior database image while retaining
the newer independent witness and observe fail-closed rollback detection.

The workflow uploads raw receipts and the aggregate manifest. Uploading an
artifact does not grant acceptance. A separate security identity must review and
sign the manifest, and the activation decision must name that signature.
