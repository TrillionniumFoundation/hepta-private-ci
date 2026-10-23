use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use sqlx::SqlitePool;

use super::CognitiveRecoveryAnchor;
use super::CognitiveRecoveryError;
use super::profile;
use super::profile::SchemaProfile;
use super::profile::indeterminate;
use crate::cognitive_store::protect_database_file;
use crate::cognitive_store::recovered_database_filename;
use crate::cognitive_store::recovery::cleanup_candidate_sidecars;
use crate::cognitive_store::recovery::cleanup_recovery_candidate;
use crate::cognitive_store::recovery::recovery_error;
use crate::cognitive_store::verify_store;

pub(super) struct UpgradeImage {
    pub(super) path: PathBuf,
    pub(super) pool: SqlitePool,
}

impl UpgradeImage {
    pub(super) async fn close(self) -> PathBuf {
        self.pool.close().await;
        self.path
    }

    pub(super) async fn discard(self) {
        self.pool.close().await;
        cleanup_recovery_candidate(&self.path);
    }
}

/// SQLite opens only a new descriptor-bound copy. The suspect source and its
/// sidecars are never repaired, migrated, checkpointed, or opened by SQLite.
pub(super) async fn copy_verified(
    config: &SqliteConfig,
    root: &Path,
    source: &Path,
    expected: &CognitiveRecoveryAnchor,
    fence: &Sha256Digest,
    schema: &SchemaProfile,
) -> Result<UpgradeImage, CognitiveRecoveryError> {
    let guard = config
        .bind_existing_recovery_database(source)
        .map_err(recovery_error)?;
    let path = root.join(recovered_database_filename(expected, fence));
    config
        .materialize_identity_bound_recovery_copy(&guard, &path)
        .map_err(recovery_error)?;
    let pool = match config.open_durable_evidence_pool(&path).await {
        Ok(pool) => pool,
        Err(error) => {
            cleanup_recovery_candidate(&path);
            return Err(indeterminate(error));
        }
    };
    let result = profile::capture_verified(&pool, &expected.owner_agent_id, schema).await;
    match result {
        Ok(observed) if observed == *expected => Ok(UpgradeImage { path, pool }),
        result => {
            pool.close().await;
            cleanup_recovery_candidate(&path);
            Err(match result {
                Err(error) => error,
                Ok(_) => CognitiveRecoveryError::AccessDenied(
                    "upgrade image differs from the independently retained exact cut".into(),
                ),
            })
        }
    }
}

/// Full checkpoint and reopen must preserve the newly captured logical cut,
/// including every current table and the exact compiled migration ledger.
pub(super) async fn seal_current(
    config: &SqliteConfig,
    root: &Path,
    image: UpgradeImage,
    expected: &CognitiveRecoveryAnchor,
) -> Result<UpgradeImage, CognitiveRecoveryError> {
    let path = image.close().await;
    let result = async {
        config
            .checkpoint_private_recovery_database(&path)
            .await
            .map_err(indeterminate)?;
        cleanup_candidate_sidecars(&path)?;
        protect_database_file(&path).map_err(indeterminate)?;
        std::fs::File::open(&path)
            .and_then(|file| file.sync_all())
            .map_err(indeterminate)?;
        #[cfg(unix)]
        let directory_sync = std::fs::File::open(root)
            .and_then(|directory| directory.sync_all())
            .map_err(indeterminate);
        #[cfg(not(unix))]
        let directory_sync: Result<(), CognitiveRecoveryError> =
            Err(CognitiveRecoveryError::Unavailable(format!(
                "schema upgrade directory durability is not qualified for {}",
                root.display(),
            )));
        directory_sync?;
        let pool = config
            .open_durable_evidence_pool(&path)
            .await
            .map_err(indeterminate)?;
        let checked = async {
            verify_store(&pool, &expected.owner_agent_id)
                .await
                .map_err(indeterminate)?;
            let observed =
                profile::capture_verified(&pool, &expected.owner_agent_id, &profile::current()?)
                    .await?;
            if observed != *expected {
                return Err(CognitiveRecoveryError::Indeterminate(
                    "upgrade cut changed across checkpoint/reopen".into(),
                ));
            }
            Ok(())
        }
        .await;
        if let Err(error) = checked {
            pool.close().await;
            return Err(error);
        }
        Ok(UpgradeImage {
            path: path.clone(),
            pool,
        })
    }
    .await;
    if result.is_err() {
        cleanup_recovery_candidate(&path);
    }
    result
}
