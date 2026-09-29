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

    /// Verify a detached cold archive image through the SAME physical owner's
    /// schema, full-history cut and SQLite-integrity oracle. This never opens
    /// a writer, publishes an active pointer, repairs, migrates or mints a cut.
    /// The trusted host must authenticate the current witness independently;
    /// a digest obtained from the supplied image is not such a witness.
    pub async fn open_archive_image(
        path: &std::path::Path,
        requirement: CognitiveRecoveryRequirement<'_>,
    ) -> Result<Self, CognitiveRecoveryError> {
        let expected = match requirement {
            CognitiveRecoveryRequirement::Revoked => {
                return Err(CognitiveRecoveryError::AccessDenied(
                    "cold archive admission is revoked".to_string(),
                ));
            }
            CognitiveRecoveryRequirement::ExactCurrentCut(anchor) => anchor,
        };
        if expected.profile != PROFILE
            || expected.schema_digest.as_str() != REQUIRED_SCHEMA_ORACLE_SHA256
        {
            return Err(CognitiveRecoveryError::Invalid(
                "unsupported cold archive recovery profile or schema".to_string(),
            ));
        }
        open_verified_cold_image(path, expected).await
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
    /// This is not writable recovery. The separate `open_with_recovery` entry
    /// requires a current external authority and retains the exclusive fence.
    pub async fn open_read_only_recovery(
        layout: &HeptaAgentLayout,
        requirement: CognitiveRecoveryRequirement<'_>,
    ) -> Result<RecoveredCognitiveReadOnly, CognitiveRecoveryError> {
        let expected = validate_requirement(layout, requirement)?;
        let path = layout
            .cognitive_root()
            .join(super::super::COGNITIVE_DB_FILENAME);
        open_verified_cold_image(&path, expected).await
    }
}

async fn open_verified_cold_image(
    path: &std::path::Path,
    expected: &CognitiveRecoveryAnchor,
) -> Result<RecoveredCognitiveReadOnly, CognitiveRecoveryError> {
    let parent = path.parent().ok_or_else(|| {
        CognitiveRecoveryError::Invalid("cold image has no parent directory".to_string())
    })?;
    let home = AbsolutePathBuf::try_from(parent.to_path_buf())
        .map_err(|error| CognitiveRecoveryError::Invalid(error.to_string()))?;
    let config = SqliteConfig::from_sqlite_home(home);
    let guard = config
        .bind_existing_recovery_database(path)
        .map_err(recovery_error)?;
    let pool = config
        .open_cold_image_read_only_pool(&guard)
        .await
        .map_err(recovery_error)?;
    let result = async {
        let mut transaction = pool.begin().await.map_err(unavailable)?;
        let observed = capture(&mut transaction, &expected.owner_agent_id).await?;
        // Authenticate schema and every logical fact before evaluating CHECK
        // expressions in integrity_check. Physical equality is checked by the
        // archive envelope; this oracle additionally protects owner semantics.
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
        store: CognitiveStore::from_read_only_pool(
            pool,
            expected.owner_agent_id.clone(),
            path.to_path_buf(),
        ),
        anchor: observed,
    })
}

#[cfg(test)]
mod archive_tests {
    use std::error::Error;

    use codex_hepta_paths::HeptaFleetRoot;
    use tempfile::TempDir;

    use super::*;

    #[tokio::test]
    async fn detached_archive_uses_existing_full_cut_oracle() -> Result<(), Box<dyn Error>> {
        let temp = TempDir::new()?;
        let root = temp.path().canonicalize()?.join("fleet");
        std::fs::create_dir_all(&root)?;
        let owner = AgentId::parse("00000000-0000-4000-8000-00000000ca83")?;
        let layout = HeptaFleetRoot::parse(root)?.layout().agent(&owner);
        let store = CognitiveStore::open(&layout).await?;
        let anchor = store.recovery_anchor().await?;
        let path = store.path().to_path_buf();
        store.pool.close().await;
        let image = RecoveredCognitiveReadOnly::open_archive_image(
            &path,
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        )
        .await?;
        assert_eq!(image.anchor(), &anchor);
        let mut stale = anchor.clone();
        stale.state_digest = Sha256Digest::for_bytes(b"not-the-current-owner-cut");
        let rejected = RecoveredCognitiveReadOnly::open_archive_image(
            &path,
            CognitiveRecoveryRequirement::ExactCurrentCut(&stale),
        )
        .await;
        assert!(matches!(
            rejected,
            Err(CognitiveRecoveryError::AccessDenied(_))
        ));
        Ok(())
    }

    #[tokio::test]
    async fn revoked_archive_denies_before_missing_path_access() {
        let result = RecoveredCognitiveReadOnly::open_archive_image(
            std::path::Path::new("/missing/cognitive-archive-image.sqlite3"),
            CognitiveRecoveryRequirement::Revoked,
        )
        .await;
        assert!(matches!(
            result,
            Err(CognitiveRecoveryError::AccessDenied(_))
        ));
    }
}
