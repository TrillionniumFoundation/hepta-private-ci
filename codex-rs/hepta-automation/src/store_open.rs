//! Open and qualify the existing automation owner before exposing its handle.
//! Kept beside the store and retirement fence; no second owner is introduced.

use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::Row;

use crate::AUTOMATION_SCHEMA_VERSION;
use crate::AutomationError;

use super::AUTOMATION_DB_FILENAME;
use super::AutomationStore;
use super::MIGRATOR;
use super::create_private_directory;
use super::protect_database_file;
use super::reconcile_legacy_migration_ids;
use super::unavailable;
use super::verify_store;

impl AutomationStore {
    pub(crate) async fn open_root(
        root: PathBuf,
        owner_agent_id: AgentId,
    ) -> Result<Self, AutomationError> {
        create_private_directory(&root)?;
        let path = root.join(AUTOMATION_DB_FILENAME);
        let retirement_fence = crate::timer_retirement::read(&path, &owner_agent_id)?;
        if retirement_fence.is_some() && !path.is_file() {
            return Err(AutomationError::Corrupt);
        }
        let sqlite_home = AbsolutePathBuf::try_from(root).map_err(|_| AutomationError::Invalid)?;
        let pool = SqliteConfig::from_sqlite_home(sqlite_home)
            .open_durable_evidence_pool(&path)
            .await
            .map_err(unavailable)?;
        if let Some(epoch) = retirement_fence
            && let Err(error) = crate::timer_retirement::verify_open(&pool, epoch).await
        {
            pool.close().await;
            return Err(error);
        }
        if let Err(error) = reconcile_legacy_migration_ids(&pool).await {
            pool.close().await;
            return Err(error);
        }
        if MIGRATOR.run(&pool).await.is_err() {
            pool.close().await;
            return Err(AutomationError::Unavailable);
        }
        protect_database_file(&path)?;
        sqlx::query(
            "INSERT INTO automation_meta (singleton, schema_version, owner_agent_id)
             VALUES (1, ?, ?) ON CONFLICT(singleton) DO NOTHING",
        )
        .bind(i64::from(AUTOMATION_SCHEMA_VERSION))
        .bind(owner_agent_id.as_str())
        .execute(&pool)
        .await
        .map_err(unavailable)?;
        verify_store(&pool, &owner_agent_id).await?;
        let timer = sqlx::query(
            "SELECT writer_epoch, phase FROM automation_timer_lifecycle WHERE singleton = 1",
        )
        .fetch_one(&pool)
        .await
        .map_err(unavailable)?;
        let timer_epoch: i64 = timer.try_get("writer_epoch").map_err(unavailable)?;
        let timer_phase: String = timer.try_get("phase").map_err(unavailable)?;
        if timer_phase == "retired"
            && retirement_fence.is_none()
            && let Err(error) =
                crate::timer_retirement::persist(&path, &owner_agent_id, timer_epoch)
        {
            pool.close().await;
            return Err(error);
        }
        if timer_epoch <= 0 {
            pool.close().await;
            return Err(AutomationError::Corrupt);
        }
        Ok(Self {
            pool,
            owner_agent_id,
            path,
            timer_epoch,
        })
    }
}
