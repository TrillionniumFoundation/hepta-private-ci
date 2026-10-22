# Windows retained SQLite recovery

## Purpose and ownership

The original cognitive owner needs to inspect and recover an independently authenticated current database cut on Windows. Recovery authority, the exact-current-cut comparison, the writer fence, the full checkpoint and activation remain in `hepta-memory/src/cognitive_store_recovery.rs`. A retained file identity is an integrity condition; it does not issue a grant or authenticate a backup.

The prior Windows implementation returned `Indeterminate` from identity binding and revalidation. This implementation adds the platform operations while retaining the original owner protocol. Its Windows and Linux execution gates are in `.github/workflows/hepta-windows-private-state-native.yml`. A source proposal or a successful compile alone does not qualify recovery.

## Modules and boundaries

| Module | Responsibility |
| --- | --- |
| `utils/path-utils/src/private_state_windows_directory.rs` | Existing-only no-reparse directory acquisition and relative leaf acquisition with explicit access, sharing and creation disposition. |
| `utils/path-utils/src/private_state_windows_recovery.rs` | Retained handles, immutable identity snapshots, same-name revalidation and exclusive private output creation. |
| `state/src/sqlite_recovery_windows.rs` | Bounded database and sidecar bundle, immutable byte acquisition, private copy and cold-image input. |
| `state/src/sqlite_recovery_image.rs` | Existing readonly in-memory SQLite deserialize/reconnect implementation. |
| `hepta-memory/src/cognitive_store_windows.rs` | Private directory, lock, database and pointer objects for the original cognitive owner. |

Input acquisition uses `FILE_OPEN`, never creation. Read-only input handles exclude write and delete sharing. Snapshots bind the full file ID and volume, type, single-link requirement, length, timestamps and actual owner/security descriptor. Redirected or unsafe existing objects fail without ACL repair. The complete bundle is revalidated after reading and before creating output.

Copying preserves database, WAL and rollback journal bytes but does not copy SHM. Each file is bounded to 128 MiB and the copy bundle to 256 MiB. The cold-image path requires a sidecar-free database between 100 bytes and 128 MiB. New outputs use `FILE_CREATE` with a private descriptor. Failed writes are cleaned through their owned handles, never by deleting an unverified replacement pathname.

## Development and regression gates

The path utility tests exercise existing-only acquisition, stream-name rejection, real writer and delete exclusion, hardlinks, junctions, actual DACL and timestamp drift, exclusive output creation and cleanup. State tests exercise full bundle copying, output collisions, absent-sidecar drift, wrong-home rejection, bounded allocation and actual readonly SQLite reconnect after source replacement.

The original cognitive recovery tests must also pass, including:

- `exact_current_cut_recovers_writable_generation_and_persists_activation`
- `graceful_close_retains_store_fence_until_sqlite_connections_finish`
- `predecessor_witness_is_rejected_and_current_witness_recovers`
- `revoked_owner_profile_and_witness_checks_precede_recovery_admission`

Run the repository's pinned Rust toolchain and original `just test --locked -p codex-utils-path -p codex-state -p codex-hepta-memory --lib` on Windows and Linux. Native Windows execution is necessary for sharing, ACL, reparse and retained identity semantics. Update Cargo and Bazel locks using their original generators when dependencies change. The dedicated source-proposal workflow can export the actual generated patch; it has read-only repository permissions and does not publish or merge source.

## Remaining qualification limits

The original directory flush and post-publication error handling remain mandatory. Unsupported or failed durability operations remain unavailable or indeterminate. A token/filesystem combination whose SQLite-created sidecars lack the required private descriptor is rejected. This change does not repair such sidecars, loosen authority validation, synthesize a current witness, or certify production provider composition.

