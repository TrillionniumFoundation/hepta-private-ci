use std::path::Path;

use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::DurableFleetError;
use crate::DurableFleetStore;
use crate::FleetSnapshot;
use crate::WorkspaceReservationV1;
use crate::durable_rows::content_digest;
use crate::durable_rows::operation_id;
use crate::durable_rows::to_i64;
use crate::durable_rows::validate_identity;
use crate::durable_schema::sqlx_error;

impl DurableFleetStore {
    pub async fn synchronize_workspace_reservations(
        &self,
        snapshot: &FleetSnapshot,
    ) -> Result<(), DurableFleetError> {
        let now_ms = self.owner_now_ms()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        for record in snapshot.agents.values() {
            reserve_workspace_tx(
                &mut tx,
                record.manifest.agent_id.as_str(),
                record.manifest.workspace.as_path(),
                now_ms,
            )
            .await?;
        }
        tx.commit().await.map_err(sqlx_error)
    }

    pub async fn reserve_workspace(
        &self,
        agent_id: &str,
        workspace: &Path,
    ) -> Result<WorkspaceReservationV1, DurableFleetError> {
        let now_ms = self.owner_now_ms()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        let reservation = reserve_workspace_tx(&mut tx, agent_id, workspace, now_ms).await?;
        match tx.commit().await {
            Ok(()) => Ok(reservation),
            Err(_) => Err(self.indeterminate(
                operation_id("workspace", agent_id, now_ms),
                agent_id.to_string(),
            )),
        }
    }

    pub async fn release_workspace(&self, agent_id: &str) -> Result<(), DurableFleetError> {
        validate_identity(agent_id, "agent")?;
        sqlx::query("DELETE FROM workspace_reservations WHERE agent_id = ?")
            .bind(agent_id)
            .execute(&self.pool)
            .await
            .map_err(sqlx_error)?;
        Ok(())
    }
}

async fn reserve_workspace_tx(
    tx: &mut Transaction<'_, Sqlite>,
    agent_id: &str,
    workspace: &Path,
    now_ms: u64,
) -> Result<WorkspaceReservationV1, DurableFleetError> {
    validate_identity(agent_id, "agent")?;
    if !workspace.is_absolute() {
        return Err(DurableFleetError::Invalid(
            "workspace reservation must be absolute".to_string(),
        ));
    }
    let workspace_text = workspace.to_string_lossy().into_owned();
    let rows = sqlx::query("SELECT agent_id, workspace FROM workspace_reservations")
        .fetch_all(&mut **tx)
        .await
        .map_err(sqlx_error)?;
    for row in rows {
        let existing_agent: String = row.try_get("agent_id").map_err(sqlx_error)?;
        let existing_workspace: String = row.try_get("workspace").map_err(sqlx_error)?;
        if existing_agent == agent_id && existing_workspace == workspace_text {
            continue;
        }
        let existing = Path::new(&existing_workspace);
        if workspace.starts_with(existing) || existing.starts_with(workspace) {
            return Err(DurableFleetError::Conflict(format!(
                "workspace overlaps agent {existing_agent}"
            )));
        }
    }
    let digest = content_digest(&workspace_text)?;
    sqlx::query(
        "INSERT INTO workspace_reservations(
            agent_id, workspace, workspace_digest, created_at_ms, updated_at_ms
         ) VALUES(?, ?, ?, ?, ?)
         ON CONFLICT(agent_id) DO UPDATE SET
            workspace = excluded.workspace,
            workspace_digest = excluded.workspace_digest,
            updated_at_ms = excluded.updated_at_ms",
    )
    .bind(agent_id)
    .bind(&workspace_text)
    .bind(&digest)
    .bind(to_i64(now_ms)?)
    .bind(to_i64(now_ms)?)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    Ok(WorkspaceReservationV1 {
        agent_id: agent_id.to_string(),
        workspace: workspace_text,
        workspace_digest: digest,
        created_at_ms: now_ms,
        updated_at_ms: now_ms,
    })
}
