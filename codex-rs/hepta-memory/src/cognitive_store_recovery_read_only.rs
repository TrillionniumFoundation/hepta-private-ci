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

    pub(super) async fn verify_writer_fence(
        &self,
        expected: &CognitiveRecoveryWriterFence,
    ) -> Result<(), CognitiveRecoveryError> {
        expected.validate(self.store.owner_agent_id())?;
        let row = sqlx::query(
            "SELECT lease_sequence, generation, state, authority_epoch, owner_epoch,
                    lease_expires_at_unix_seconds, lease_sha256
             FROM cognitive_local_leases
             WHERE lease_id = ? AND owner_agent_id = ?
             ORDER BY lease_sequence DESC LIMIT 1",
        )
        .bind(&expected.lease_id)
        .bind(self.store.owner_agent_id().as_str())
        .fetch_optional(&self.store.pool)
        .await
        .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?
        .ok_or_else(|| {
            CognitiveRecoveryError::AccessDenied(
                "current cognitive writer fence is missing from the verified cut".to_string(),
            )
        })?;
        let lease_sequence = row
            .try_get::<i64, _>("lease_sequence")
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        let generation = row
            .try_get::<i64, _>("generation")
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        let state = row
            .try_get::<String, _>("state")
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        let authority_epoch = row
            .try_get::<Option<i64>, _>("authority_epoch")
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        let owner_epoch = row
            .try_get::<Option<i64>, _>("owner_epoch")
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        let expires = row
            .try_get::<Option<i64>, _>("lease_expires_at_unix_seconds")
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        let lease_sha256 = row
            .try_get::<String, _>("lease_sha256")
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?;
        let observed = (
            u64::try_from(lease_sequence).ok(),
            u64::try_from(generation).ok(),
            state.as_str(),
            authority_epoch.and_then(|value| u64::try_from(value).ok()),
            owner_epoch.and_then(|value| u64::try_from(value).ok()),
            expires.and_then(|value| u64::try_from(value).ok()),
            Sha256Digest::parse(lease_sha256).ok(),
        );
        if observed
            != (
                Some(expected.lease_sequence),
                Some(expected.generation),
                "active",
                Some(expected.authority_epoch),
                Some(expected.owner_epoch),
                Some(expected.lease_expires_at_unix_seconds),
                Some(expected.lease_sha256.clone()),
            )
        {
            return Err(CognitiveRecoveryError::AccessDenied(
                "verified cognitive cut does not contain the independently retained current writer fence"
                    .to_string(),
            ));
        }
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| CognitiveRecoveryError::Indeterminate(error.to_string()))?
            .as_secs();
        if now >= expected.lease_expires_at_unix_seconds {
            return Err(CognitiveRecoveryError::AccessDenied(
                "cognitive recovery writer fence expired before recovery admission".to_string(),
            ));
        }
        Ok(())
    }

    pub(super) async fn close(self) {
        self.store.pool.close().await;
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
        let validated = validate_requirement(layout, requirement)?;
        let expected = validated.anchor;
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
