//! Current-cut admission for an isolated cold image plus fenced fresh-owner promotion.

use super::*;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::DurableCognitiveSnapshot;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityVerifier;
use codex_state::ColdSqliteRecoveryImage;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

/// An admitted historical image, not by itself a writable owner or a live
/// authorization.
///
/// Only the canonical bounded Lane C projection is exposed before promotion.
/// The exact immutable bytes used for admission are retained so a trusted host
/// can later promote *those same bytes* into a fresh inode after supplying an
/// independently verified current production authority fence. Promotion never
/// makes the suspect source file writable and never rereads it by pathname.
pub struct RecoveredCognitiveReadOnly {
    store: CognitiveStore,
    anchor: CognitiveRecoveryAnchor,
    image: ColdSqliteRecoveryImage,
}

impl RecoveredCognitiveReadOnly {
    /// The independently supplied complete cut which was actually verified.
    pub fn anchor(&self) -> &CognitiveRecoveryAnchor {
        &self.anchor
    }

    /// Read the existing canonical scope projection, with its normal access
    /// checks, row bounds, tombstones and source-revocation handling.
    pub async fn lane_c_snapshot(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        now_unix_seconds: i64,
    ) -> Result<DurableCognitiveSnapshot, CognitiveStoreError> {
        self.store
            .lane_c_snapshot(access, scope, now_unix_seconds)
            .await
    }

    /// Promote this already-admitted immutable image into a *fresh* canonical
    /// owner under an externally verified current production authority lease.
    ///
    /// Safety properties:
    /// - the exact bytes admitted read-only are the bytes materialized;
    /// - the suspect source is never opened writable or repaired in place;
    /// - a separate Agent run-root recovery lock serializes promotions without
    ///   invalidating the retained cognitive-directory identity;
    /// - external authority is verified before materialization, immediately
    ///   before route publication, and after reopen before a writable handle is
    ///   returned;
    /// - the previous source inode is quarantined and never used as fallback
    ///   without a fresh independently authenticated recovery attempt;
    /// - the newly opened owner must reproduce the exact logical recovery cut.
    ///
    /// The verifier contract is stronger here than ordinary writer admission:
    /// returning `Ok(())` means the supervisor has established that this lease
    /// is CURRENT and that the previous Agent generation/writer has been fenced.
    pub async fn promote_to_fresh_owner<V>(
        self,
        layout: &HeptaAgentLayout,
        authority: &ProductionAuthorityLease,
        verifier: &V,
    ) -> Result<CognitiveStore, CognitiveRecoveryError>
    where
        V: ProductionAuthorityVerifier + ?Sized,
    {
        #[cfg(not(unix))]
        {
            let _ = (layout, authority, verifier);
            return Err(CognitiveRecoveryError::Unavailable(
                "writable cold-image recovery currently requires Unix descriptor semantics"
                    .to_string(),
            ));
        }

        #[cfg(unix)]
        {
            if self.anchor.owner_agent_id != *layout.agent_id()
                || self.store.owner_agent_id() != layout.agent_id()
                || self.store.path()
                    != layout.cognitive_root().join(COGNITIVE_DB_FILENAME).as_path()
            {
                return Err(CognitiveRecoveryError::AccessDenied(
                    "recovery promotion layout does not match the admitted owner".to_string(),
                ));
            }
            verify_recovery_authority(authority, verifier, layout.agent_id())?;
            let _lock = RecoveryPromotionLock::acquire(layout)?;

            let root = layout.cognitive_root();
            let path = root.join(COGNITIVE_DB_FILENAME);
            let sqlite_home = AbsolutePathBuf::try_from(root.to_path_buf())
                .map_err(|error| CognitiveRecoveryError::Invalid(error.to_string()))?;
            let config = SqliteConfig::from_sqlite_home(sqlite_home);
            let key = self
                .anchor
                .state_digest
                .as_str()
                .chars()
                .take(16)
                .collect::<String>();
            let fresh = root.join(format!(".{COGNITIVE_DB_FILENAME}.recovery-{key}.new"));
            let quarantine =
                root.join(format!(".{COGNITIVE_DB_FILENAME}.recovery-{key}.quarantine"));
            let failed = root.join(format!(".{COGNITIVE_DB_FILENAME}.recovery-{key}.failed"));
            for reserved in [&fresh, &quarantine, &failed] {
                if reserved.exists() {
                    return Err(CognitiveRecoveryError::Indeterminate(format!(
                        "recovery promotion reserved path already exists: {}",
                        reserved.display()
                    )));
                }
            }

            // The in-memory read pool is no longer needed. Closing it cannot
            // touch the suspect path because it was created with deserialize.
            self.store.pool.close().await;
            self.image
                .write_fresh_copy(&config, &fresh)
                .map_err(recovery_error)?;
            sync_directory(root)?;

            // The fresh sibling changed only the cognitive-directory metadata;
            // image.write_fresh_copy revalidated the bound database and all
            // sidecar identities after that change. Reverify the external fence
            // at the last point before replacing the route.
            if let Err(error) = verify_recovery_authority(authority, verifier, layout.agent_id()) {
                let _ = std::fs::remove_file(&fresh);
                return Err(error);
            }

            if let Err(error) = std::fs::rename(&path, &quarantine) {
                let _ = std::fs::remove_file(&fresh);
                return Err(CognitiveRecoveryError::Indeterminate(format!(
                    "cannot quarantine admitted cognitive source: {error}"
                )));
            }
            if let Err(error) = std::fs::rename(&fresh, &path) {
                let rollback = std::fs::rename(&quarantine, &path);
                let _ = std::fs::remove_file(&fresh);
                return match rollback {
                    Ok(()) => Err(CognitiveRecoveryError::Indeterminate(format!(
                        "cannot publish fresh cognitive owner: {error}"
                    ))),
                    Err(rollback_error) => Err(CognitiveRecoveryError::Indeterminate(format!(
                        "cannot publish fresh cognitive owner ({error}); cannot restore quarantined source ({rollback_error})"
                    ))),
                };
            }
            sync_directory(root)?;

            let reopened = match CognitiveStore::open(layout).await {
                Ok(store) => store,
                Err(error) => {
                    rollback_promotion(root, &path, &quarantine, &failed)?;
                    return Err(CognitiveRecoveryError::Indeterminate(format!(
                        "fresh cognitive owner failed verified open: {error}"
                    )));
                }
            };
            let observed = match reopened.recovery_anchor().await {
                Ok(anchor) => anchor,
                Err(error) => {
                    reopened.pool.close().await;
                    rollback_promotion(root, &path, &quarantine, &failed)?;
                    return Err(CognitiveRecoveryError::Indeterminate(format!(
                        "fresh cognitive owner failed recovery-anchor verification: {error}"
                    )));
                }
            };
            if observed != self.anchor {
                reopened.pool.close().await;
                rollback_promotion(root, &path, &quarantine, &failed)?;
                return Err(CognitiveRecoveryError::AccessDenied(
                    "fresh cognitive owner differs from the independently authenticated current cut"
                        .to_string(),
                ));
            }
            if let Err(error) =
                verify_recovery_authority(authority, verifier, layout.agent_id())
            {
                reopened.pool.close().await;
                rollback_promotion(root, &path, &quarantine, &failed)?;
                return Err(error);
            }
            Ok(reopened)
        }
    }
}

impl CognitiveStore {
    /// Admit a Unix cold database as a read-only historical image, without
    /// opening the source path in SQLite or modifying source files.
    ///
    /// The host MUST supply its independently retained/authenticated CURRENT
    /// full-cut anchor. Deriving that anchor from the suspect image itself
    /// defeats rollback protection. Revocation denies before filesystem access.
    /// Every WAL/SHM/journal, even empty, is rejected; no replay is attempted.
    /// The retained descriptor copy is bounded to 128 MiB. Metadata checks are
    /// drift detection, not an atomic snapshot guarantee: the fixed copy must
    /// also pass schema/integrity checks and match ALL canonical logical facts
    /// (including deletion/revocation state) under the full current-cut hash.
    /// Unused physical bytes are not authority and are not covered by that hash.
    /// A mismatch never falls back to an older cut or ordinary store opening.
    pub async fn open_read_only_recovery(
        layout: &HeptaAgentLayout,
        requirement: CognitiveRecoveryRequirement<'_>,
    ) -> Result<RecoveredCognitiveReadOnly, CognitiveRecoveryError> {
        let expected = validate_requirement(layout, requirement)?;
        let path = layout.cognitive_root().join(COGNITIVE_DB_FILENAME);
        let home = AbsolutePathBuf::try_from(layout.cognitive_root().to_path_buf())
            .map_err(|error| CognitiveRecoveryError::Invalid(error.to_string()))?;
        let config = SqliteConfig::from_sqlite_home(home);
        let guard = config
            .bind_existing_recovery_database(&path)
            .map_err(recovery_error)?;
        let image = config
            .capture_cold_recovery_image(&guard)
            .map_err(recovery_error)?;
        let pool = image
            .open_read_only_pool(&config)
            .await
            .map_err(recovery_error)?;
        let result = async {
            let mut transaction = pool.begin().await.map_err(unavailable)?;
            let observed = capture(&mut transaction, layout.agent_id()).await?;
            // Unlike quick_check, this also verifies ordinary index content
            // against table rows. The source copy may have raced an in-place
            // writer: metadata stability is never treated as page consistency.
            // First authenticate the entire schema/cut: integrity_check may
            // evaluate CHECK expressions embedded in untrusted schema SQL.
            if observed == *expected {
                let integrity: Vec<String> = sqlx::query_scalar("PRAGMA integrity_check(1)")
                    .fetch_all(&mut *transaction)
                    .await
                    .map_err(unavailable)?;
                if integrity != ["ok"] {
                    return Err(CognitiveStoreError::Corrupt(
                        "cold image integrity check failed".into(),
                    ));
                }
            }
            transaction.commit().await.map_err(unavailable)?;
            Ok::<_, CognitiveStoreError>(observed)
        }
        .await;
        let observed = match result {
            Ok(observed) => observed,
            Err(error) => {
                pool.close().await;
                return Err(CognitiveRecoveryError::Indeterminate(error.to_string()));
            }
        };
        if observed != *expected {
            pool.close().await;
            return Err(CognitiveRecoveryError::AccessDenied(
                "cold image differs from the independently supplied current cut".to_string(),
            ));
        }
        Ok(RecoveredCognitiveReadOnly {
            store: CognitiveStore::from_read_only_pool(pool, layout.agent_id().clone(), path),
            anchor: observed,
            image,
        })
    }
}

#[cfg(unix)]
struct RecoveryPromotionLock {
    _file: std::fs::File,
    _path: PathBuf,
}

#[cfg(unix)]
impl RecoveryPromotionLock {
    fn acquire(layout: &HeptaAgentLayout) -> Result<Self, CognitiveRecoveryError> {
        use std::os::unix::fs::OpenOptionsExt;
        use std::os::unix::fs::PermissionsExt;

        std::fs::create_dir_all(layout.run_root()).map_err(|error| {
            CognitiveRecoveryError::Indeterminate(format!(
                "cannot create Agent recovery lock root: {error}"
            ))
        })?;
        std::fs::set_permissions(layout.run_root(), std::fs::Permissions::from_mode(0o700))
            .map_err(|error| {
                CognitiveRecoveryError::Indeterminate(format!(
                    "cannot protect Agent recovery lock root: {error}"
                ))
            })?;
        let path = layout.run_root().join("cognitive-recovery.lock");
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .open(&path)
            .map_err(|error| {
                CognitiveRecoveryError::Indeterminate(format!(
                    "cannot open cognitive recovery lock {}: {error}",
                    path.display()
                ))
            })?;
        match file.try_lock() {
            Ok(()) => Ok(Self {
                _file: file,
                _path: path,
            }),
            Err(std::fs::TryLockError::WouldBlock) => Err(CognitiveRecoveryError::AccessDenied(
                "another cognitive recovery promotion is active".to_string(),
            )),
            Err(std::fs::TryLockError::Error(error)) => {
                Err(CognitiveRecoveryError::Indeterminate(format!(
                    "cannot acquire cognitive recovery lock: {error}"
                )))
            }
        }
    }
}

fn verify_recovery_authority<V>(
    authority: &ProductionAuthorityLease,
    verifier: &V,
    expected_agent: &AgentId,
) -> Result<(), CognitiveRecoveryError>
where
    V: ProductionAuthorityVerifier + ?Sized,
{
    verifier
        .verify(authority, expected_agent)
        .map_err(CognitiveRecoveryError::AccessDenied)?;
    if &authority.agent_id != expected_agent {
        return Err(CognitiveRecoveryError::AccessDenied(
            "recovery writer authority owner mismatch".to_string(),
        ));
    }
    if authority.authority_epoch == 0 || authority.owner_epoch == 0 {
        return Err(CognitiveRecoveryError::Invalid(
            "recovery writer authority epochs must be non-zero".to_string(),
        ));
    }
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?
        .as_secs();
    if authority.is_expired_at(now) {
        return Err(CognitiveRecoveryError::AccessDenied(
            "recovery writer authority is expired".to_string(),
        ));
    }
    authority
        .fencing_token_digest()
        .map_err(|error| CognitiveRecoveryError::AccessDenied(error.to_string()))?;
    Ok(())
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), CognitiveRecoveryError> {
    let directory = std::fs::File::open(path).map_err(|error| {
        CognitiveRecoveryError::Indeterminate(format!(
            "cannot open cognitive directory for sync: {error}"
        ))
    })?;
    directory.sync_all().map_err(|error| {
        CognitiveRecoveryError::Indeterminate(format!(
            "cannot sync cognitive directory: {error}"
        ))
    })
}

#[cfg(unix)]
fn rollback_promotion(
    root: &Path,
    canonical: &Path,
    quarantine: &Path,
    failed: &Path,
) -> Result<(), CognitiveRecoveryError> {
    if canonical.exists() {
        std::fs::rename(canonical, failed).map_err(|error| {
            CognitiveRecoveryError::Indeterminate(format!(
                "cannot quarantine failed fresh cognitive owner: {error}"
            ))
        })?;
    }
    for suffix in ["-wal", "-shm", "-journal"] {
        let mut value = canonical.as_os_str().to_os_string();
        value.push(suffix);
        let sidecar = PathBuf::from(value);
        match std::fs::remove_file(&sidecar) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => {
                return Err(CognitiveRecoveryError::Indeterminate(format!(
                    "cannot remove failed fresh cognitive sidecar {}: {error}",
                    sidecar.display()
                )));
            }
        }
    }
    std::fs::rename(quarantine, canonical).map_err(|error| {
        CognitiveRecoveryError::Indeterminate(format!(
            "cannot restore quarantined cognitive source: {error}"
        ))
    })?;
    sync_directory(root)
}
