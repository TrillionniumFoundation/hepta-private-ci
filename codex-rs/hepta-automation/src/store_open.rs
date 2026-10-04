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
use super::reconcile_legacy_migration_ids_connection;
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
        if let Err(error) = migrate_owner(&pool, &owner_agent_id).await {
            pool.close().await;
            return Err(error);
        }
        protect_database_file(&path)?;
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

/// Fence logical owner qualification and schema changes on one connection.
/// The existing pool has already opened/configured SQLite. This is not a
/// side-effect-free filesystem preflight or a descriptor-bound writer admission.
async fn migrate_owner(
    pool: &sqlx::SqlitePool,
    owner_agent_id: &AgentId,
) -> Result<(), AutomationError> {
    let mut transaction = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(unavailable)?;
    let has_meta: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'automation_meta'",
    )
    .fetch_one(&mut *transaction)
    .await
    .map_err(unavailable)?;
    if has_meta == 0 {
        let objects: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM main.sqlite_schema")
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
        if objects != 0 {
            return Err(AutomationError::Corrupt);
        }
    } else {
        let rows = sqlx::query(
            "SELECT singleton, schema_version, owner_agent_id FROM automation_meta LIMIT 2",
        )
        .fetch_all(&mut *transaction)
        .await
        .map_err(|_| AutomationError::Corrupt)?;
        if rows.len() != 1 {
            return Err(AutomationError::Corrupt);
        }
        let row = &rows[0];
        let singleton: i64 = row
            .try_get("singleton")
            .map_err(|_| AutomationError::Corrupt)?;
        let schema: i64 = row
            .try_get("schema_version")
            .map_err(|_| AutomationError::Corrupt)?;
        let owner: String = row
            .try_get("owner_agent_id")
            .map_err(|_| AutomationError::Corrupt)?;
        // Relocated migrations 17/18 emitted legacy metadata versions 4/5.
        // They never defined owner schema versions 17/18.
        if singleton != 1 || !matches!(schema, 1..=16 | 19 | 20) || AgentId::parse(&owner).is_err()
        {
            return Err(AutomationError::Corrupt);
        }
        if owner != owner_agent_id.as_str() {
            return Err(AutomationError::AccessDenied);
        }
    }
    reconcile_legacy_migration_ids_connection(&mut transaction).await?;
    MIGRATOR.run(&mut *transaction).await.map_err(unavailable)?;
    sqlx::query(
        "INSERT INTO automation_meta (singleton, schema_version, owner_agent_id)
         VALUES (1, ?, ?) ON CONFLICT(singleton) DO NOTHING",
    )
    .bind(i64::from(AUTOMATION_SCHEMA_VERSION))
    .bind(owner_agent_id.as_str())
    .execute(&mut *transaction)
    .await
    .map_err(unavailable)?;
    transaction.commit().await.map_err(unavailable)
}
