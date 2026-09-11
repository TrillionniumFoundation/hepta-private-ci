//! Current-cut admission for an isolated, explicitly read-only cold image.

use super::*;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::DurableCognitiveSnapshot;

/// An admitted historical image, not a writable owner or a live authorization.
///
/// Only the canonical bounded Lane C projection is exposed. There is no pool,
/// mutable store, dereference, migration, repair, or writer conversion API.
/// The host must authenticate the CURRENT witness and revocation disposition
/// independently at admission. Subsequent live revocation requires discarding
/// this historical handle and its projections; this is not a writer lease.
pub struct RecoveredCognitiveReadOnly {
    store: CognitiveStore,
    anchor: CognitiveRecoveryAnchor,
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
    ///
    /// This does NOT complete `open_with_recovery`: writer restoration still
    /// requires a descriptor-backed VFS and an independently current writer fence.
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
        let pool = config
            .open_cold_image_read_only_pool(&guard)
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
        })
    }
}
