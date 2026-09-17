//! Exact-cut writable recovery through an isolated WAL replay candidate.
//!
//! The suspect source path is never opened by SQLite. codex-state binds the
//! source main/WAL/SHM identities read-only, copies retained descriptors into a
//! fresh private sibling, and SQLite replays/checkpoints only that copy. This
//! module authenticates the complete logical cut against an independently held
//! CURRENT anchor before the candidate can replace the canonical pathname.

use super::super::CognitiveRecoveryError;
use super::super::CognitiveRecoveryRequirement;
use super::super::capture;
use super::super::recovery_error;
use super::super::validate_requirement;
use crate::COGNITIVE_DB_FILENAME;
use crate::CognitiveStore;
use codex_hepta_paths::HeptaAgentLayout;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

const AUTHORITY_LOCK_FILENAME: &str = ".hepta-cognitive-production-authority.lock";
const MAX_QUARANTINE_COMPONENTS: usize = 4;

impl CognitiveStore {
    /// Recover the exact independently authenticated current cut as the live
    /// writable owner on Unix.
    ///
    /// Admission is deliberately stronger than ordinary `open`: a process-wide
    /// authority lock is held, the source identities are retained without
    /// following symlinks, WAL replay occurs only on an isolated copy, the full
    /// canonical logical cut must equal `ExactCurrentCut`, and the source is
    /// quarantined before the validated candidate is atomically renamed into
    /// the canonical database pathname. No mismatch falls back to ordinary open.
    ///
    /// The caller is still responsible for establishing that the supplied cut
    /// is CURRENT and authenticated outside the suspect database. The lock here
    /// prevents another canonical production writer in this repository from
    /// racing promotion; a host must call recovery before serving cognitive
    /// tools or exposing any alternate write path.
    pub async fn open_replayed_recovery(
        layout: &HeptaAgentLayout,
        requirement: CognitiveRecoveryRequirement<'_>,
    ) -> Result<Self, CognitiveRecoveryError> {
        let expected = validate_requirement(layout, requirement)?;
        let root = layout.cognitive_root();
        let path = root.join(COGNITIVE_DB_FILENAME);
        let _authority_lock = acquire_authority_lock(root)?;
        let home = AbsolutePathBuf::try_from(root.to_path_buf())
            .map_err(|error| CognitiveRecoveryError::Invalid(error.to_string()))?;
        let config = SqliteConfig::from_sqlite_home(home);
        let guard = config
            .bind_existing_recovery_database(&path)
            .map_err(recovery_error)?;
        let nonce = recovery_nonce()?;
        let staged = root.join(format!(
            ".cognitive-recovery-stage-{}-{nonce}.sqlite3",
            std::process::id()
        ));
        let pool = config
            .open_replayed_recovery_copy(&guard, &staged)
            .await
            .map_err(recovery_error)?;
        let observed = async {
            let mut transaction = pool
                .begin_with("BEGIN IMMEDIATE")
                .await
                .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
            let observed = capture(&mut transaction, layout.agent_id())
                .await
                .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
            transaction
                .commit()
                .await
                .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
            Ok::<_, CognitiveRecoveryError>(observed)
        }
        .await;
        let observed = match observed {
            Ok(observed) => observed,
            Err(error) => {
                pool.close().await;
                cleanup_stage(&staged);
                return Err(error);
            }
        };
        if observed != *expected {
            pool.close().await;
            cleanup_stage(&staged);
            return Err(CognitiveRecoveryError::AccessDenied(
                "replayed recovery candidate differs from independently supplied current cut"
                    .to_string(),
            ));
        }
        pool.close().await;
        require_checkpointed_stage(&staged)?;
        guard
            .verify_inspection_unchanged()
            .map_err(recovery_error)?;

        let quarantine = root.join(format!(
            ".cognitive-recovery-quarantine-{}-{nonce}",
            std::process::id()
        ));
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(&quarantine)
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        let moved = match quarantine_source(&path, &quarantine) {
            Ok(moved) => moved,
            Err(error) => {
                cleanup_stage(&staged);
                let _ = std::fs::remove_dir(&quarantine);
                return Err(error);
            }
        };
        if let Err(error) = std::fs::rename(&staged, &path) {
            let restored = restore_quarantine(&moved);
            cleanup_stage(&staged);
            let _ = std::fs::remove_dir(&quarantine);
            return Err(CognitiveRecoveryError::Indeterminate(format!(
                "failed to promote replayed cognitive database: {error}; source restored={restored}"
            )));
        }
        sync_file(&path)?;
        sync_directory(root)?;

        let store = CognitiveStore::open(layout)
            .await
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        let reopened = store
            .recovery_anchor()
            .await
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        if reopened != *expected {
            return Err(CognitiveRecoveryError::Indeterminate(
                "promoted cognitive database changed across canonical reopen".to_string(),
            ));
        }
        Ok(store)
    }
}

fn acquire_authority_lock(root: &Path) -> Result<File, CognitiveRecoveryError> {
    let canonical = root
        .canonicalize()
        .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
    if canonical != root {
        return Err(CognitiveRecoveryError::Indeterminate(
            "cognitive recovery root must be canonical".to_string(),
        ));
    }
    let path = root.join(AUTHORITY_LOCK_FILENAME);
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(&path)
        .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
    match file.try_lock() {
        Ok(()) => Ok(file),
        Err(std::fs::TryLockError::WouldBlock) => Err(CognitiveRecoveryError::Unavailable(
            "another cognitive production writer or recovery attempt is live".to_string(),
        )),
        Err(std::fs::TryLockError::Error(error)) => {
            Err(CognitiveRecoveryError::Indeterminate(error.to_string()))
        }
    }
}

fn recovery_nonce() -> Result<u128, CognitiveRecoveryError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))
}

fn sidecar(database: &Path, suffix: &str) -> PathBuf {
    let mut value = database.as_os_str().to_os_string();
    value.push(suffix);
    PathBuf::from(value)
}

fn cleanup_stage(database: &Path) {
    for path in [
        database.to_path_buf(),
        sidecar(database, "-wal"),
        sidecar(database, "-shm"),
        sidecar(database, "-journal"),
    ] {
        let _ = std::fs::remove_file(path);
    }
}

fn require_checkpointed_stage(database: &Path) -> Result<(), CognitiveRecoveryError> {
    let wal = sidecar(database, "-wal");
    match std::fs::symlink_metadata(&wal) {
        Ok(metadata)
            if metadata.is_file() && !metadata.file_type().is_symlink() && metadata.len() == 0 =>
        {
            std::fs::remove_file(&wal)
                .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Ok(_) | Err(_) => {
            cleanup_stage(database);
            return Err(CognitiveRecoveryError::Indeterminate(
                "recovery staging WAL was not fully checkpointed".to_string(),
            ));
        }
    }
    let shm = sidecar(database, "-shm");
    match std::fs::symlink_metadata(&shm) {
        Ok(metadata) if metadata.is_file() && !metadata.file_type().is_symlink() => {
            std::fs::remove_file(&shm)
                .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Ok(_) | Err(_) => {
            cleanup_stage(database);
            return Err(CognitiveRecoveryError::Indeterminate(
                "recovery staging SHM identity is invalid".to_string(),
            ));
        }
    }
    let journal = sidecar(database, "-journal");
    match std::fs::symlink_metadata(&journal) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Ok(_) | Err(_) => {
            cleanup_stage(database);
            return Err(CognitiveRecoveryError::Indeterminate(
                "recovery staging rollback journal is unexpected".to_string(),
            ));
        }
    }
    sync_file(database)
}

fn quarantine_source(
    database: &Path,
    quarantine: &Path,
) -> Result<Vec<(PathBuf, PathBuf)>, CognitiveRecoveryError> {
    let name = database.file_name().ok_or_else(|| {
        CognitiveRecoveryError::Indeterminate("cognitive database filename missing".to_string())
    })?;
    let components = [
        (database.to_path_buf(), ""),
        (sidecar(database, "-wal"), "-wal"),
        (sidecar(database, "-shm"), "-shm"),
        (sidecar(database, "-journal"), "-journal"),
    ];
    let mut moved = Vec::with_capacity(MAX_QUARANTINE_COMPONENTS);
    for (source, suffix) in components {
        match std::fs::symlink_metadata(&source) {
            Ok(metadata) if metadata.is_file() && !metadata.file_type().is_symlink() => {
                let mut destination_name = name.to_os_string();
                destination_name.push(suffix);
                let destination = quarantine.join(destination_name);
                if let Err(error) = std::fs::rename(&source, &destination) {
                    let restored = restore_quarantine(&moved);
                    return Err(CognitiveRecoveryError::Indeterminate(format!(
                        "failed to quarantine cognitive source {}: {error}; restored={restored}",
                        source.display()
                    )));
                }
                moved.push((source, destination));
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Ok(_) | Err(_) => {
                let restored = restore_quarantine(&moved);
                return Err(CognitiveRecoveryError::Indeterminate(format!(
                    "invalid cognitive source component during quarantine; restored={restored}"
                )));
            }
        }
    }
    if moved.is_empty() || moved[0].0 != database {
        let restored = restore_quarantine(&moved);
        return Err(CognitiveRecoveryError::Indeterminate(format!(
            "canonical cognitive database disappeared during promotion; restored={restored}"
        )));
    }
    Ok(moved)
}

fn restore_quarantine(moved: &[(PathBuf, PathBuf)]) -> bool {
    let mut restored = true;
    for (source, destination) in moved.iter().rev() {
        if std::fs::rename(destination, source).is_err() {
            restored = false;
        }
    }
    restored
}

fn sync_file(path: &Path) -> Result<(), CognitiveRecoveryError> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))
}

fn sync_directory(path: &Path) -> Result<(), CognitiveRecoveryError> {
    File::open(path)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))
}
