//! Durable identified creation binding in the original state.sqlite owner.
use super::*;
use sqlx::Row;
use std::path::PathBuf;

const MAX_PENDING_CREATIONS: i64 = 1024;
const MAX_CREATION_RECEIPT_BYTES: usize = 1024 * 1024;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ThreadCreationReservation {
    pub idempotency_key: String,
    pub parameters_sha256: String,
    pub thread_id: ThreadId,
    pub project_id: Option<String>,
    pub cwd: PathBuf,
    pub thread_source: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ThreadCreationPhase {
    Pending,
    Created,
    Deleted,
    Abandoned,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ThreadCreationRecord {
    pub reservation: ThreadCreationReservation,
    pub rollout_path: Option<PathBuf>,
    pub receipt_json: Option<String>,
    pub phase: ThreadCreationPhase,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ThreadCreationReserveOutcome {
    Reserved,
    Existing(ThreadCreationRecord),
}

impl StateRuntime {
    /// Bind the complete request and fixed thread ID before any creation effect.
    /// Matching existing keys never confer permission to run creation again.
    pub async fn reserve_thread_creation(
        &self,
        requested: &ThreadCreationReservation,
    ) -> anyhow::Result<ThreadCreationReserveOutcome> {
        anyhow::ensure!(
            !requested.idempotency_key.is_empty()
                && requested.idempotency_key.len() <= 256
                && !requested.idempotency_key.chars().any(char::is_control)
                && requested.parameters_sha256.len() == 64
                && requested
                    .parameters_sha256
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                && requested.cwd.is_absolute(),
            "invalid identified creation binding"
        );
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        if let Some(row) =
            sqlx::query("SELECT * FROM thread_creation_operations WHERE idempotency_key = ?")
                .bind(&requested.idempotency_key)
                .fetch_optional(&mut *tx)
                .await?
        {
            let record = creation_from_row(row)?;
            anyhow::ensure!(
                record.reservation.parameters_sha256 == requested.parameters_sha256
                    && record.reservation.project_id == requested.project_id
                    && record.reservation.cwd == requested.cwd
                    && record.reservation.thread_source == requested.thread_source,
                "identified creation key conflicts with its original parameters or scope"
            );
            tx.commit().await?;
            return Ok(ThreadCreationReserveOutcome::Existing(record));
        }
        if let Some(project_id) = &requested.project_id {
            anyhow::ensure!(
                sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM projects WHERE id = ?")
                    .bind(project_id)
                    .fetch_one(&mut *tx)
                    .await?
                    == 1,
                "identified creation project is unavailable"
            );
        }
        let pending: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM thread_creation_operations WHERE phase = 'pending'",
        )
        .fetch_one(&mut *tx)
        .await?;
        anyhow::ensure!(
            pending < MAX_PENDING_CREATIONS,
            "unsettled identified creation capacity reached"
        );
        sqlx::query("INSERT INTO thread_creation_operations (idempotency_key, parameters_sha256, thread_id, project_id, cwd, thread_source, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?)")
            .bind(&requested.idempotency_key).bind(&requested.parameters_sha256)
            .bind(requested.thread_id.to_string()).bind(&requested.project_id)
            .bind(requested.cwd.to_string_lossy().as_ref()).bind(&requested.thread_source)
            .bind(Utc::now().timestamp_millis()).execute(&mut *tx).await?;
        tx.commit().await?;
        Ok(ThreadCreationReserveOutcome::Reserved)
    }

    /// SELECT only: absence never authorizes another creation or implies success.
    pub async fn read_thread_creation(
        &self,
        key: &str,
    ) -> anyhow::Result<Option<ThreadCreationRecord>> {
        sqlx::query("SELECT * FROM thread_creation_operations WHERE idempotency_key = ?")
            .bind(key)
            .fetch_optional(self.pool.as_ref())
            .await?
            .map(creation_from_row)
            .transpose()
    }

    /// An explicit owner action may retire only the pre-effect reservation.
    /// The lazy recorder binds its path under this same writer before it can
    /// materialize. If abandonment wins, that binding and late index writes
    /// fail; a bound path, even a missing file, never permits cancellation.
    pub async fn abandon_reserved_thread_creation(
        &self,
        reservation: &ThreadCreationReservation,
    ) -> anyhow::Result<bool> {
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let row = sqlx::query("SELECT * FROM thread_creation_operations WHERE idempotency_key = ?")
            .bind(&reservation.idempotency_key)
            .fetch_optional(&mut *tx)
            .await?
            .ok_or_else(|| anyhow::anyhow!("original creation reservation is unavailable"))?;
        let record = creation_from_row(row)?;
        anyhow::ensure!(
            record.reservation == *reservation,
            "creation abandonment changed its original binding or scope"
        );
        if record.phase == ThreadCreationPhase::Abandoned
            && record.rollout_path.is_none()
            && record.receipt_json.is_none()
        {
            tx.commit().await?;
            return Ok(true);
        }
        let result = sqlx::query("UPDATE thread_creation_operations SET phase = 'abandoned' WHERE idempotency_key = ? AND thread_id = ? AND phase = 'pending' AND rollout_path IS NULL AND receipt_json IS NULL AND NOT EXISTS (SELECT 1 FROM threads WHERE id = ?)")
            .bind(&reservation.idempotency_key)
            .bind(reservation.thread_id.to_string())
            .bind(reservation.thread_id.to_string())
            .execute(&mut *tx).await?;
        tx.commit().await?;
        Ok(result.rows_affected() == 1)
    }

    /// The original lazy recorder binds its exact path before materialization.
    pub async fn bind_thread_creation_rollout(
        &self,
        thread_id: ThreadId,
        cwd: &std::path::Path,
        thread_source: &str,
        path: &std::path::Path,
    ) -> anyhow::Result<()> {
        // Ordinary unkeyed creation is a cheap indexed read, never an extra
        // global writer transaction. The keyed path rechecks under the writer.
        if sqlx::query_scalar::<_, i64>(
            "SELECT 1 FROM thread_creation_operations WHERE thread_id = ?",
        )
        .bind(thread_id.to_string())
        .fetch_optional(self.pool.as_ref())
        .await?
        .is_none()
        {
            return Ok(());
        }
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let row = sqlx::query("SELECT * FROM thread_creation_operations WHERE thread_id = ?")
            .bind(thread_id.to_string())
            .fetch_optional(&mut *tx)
            .await?;
        if let Some(row) = row {
            let record = creation_from_row(row)?;
            anyhow::ensure!(
                record.phase == ThreadCreationPhase::Pending
                    && record.reservation.cwd == cwd
                    && record.reservation.thread_source == thread_source
                    && record
                        .rollout_path
                        .as_deref()
                        .is_none_or(|original| original == path),
                "original identified creation rollout or scope changed"
            );
            sqlx::query("UPDATE thread_creation_operations SET rollout_path = ? WHERE thread_id = ? AND phase = 'pending'")
                .bind(path.to_string_lossy().as_ref()).bind(thread_id.to_string())
                .execute(&mut *tx).await?;
        }
        tx.commit().await?;
        Ok(())
    }

    /// Save the precise original response before the persist/commit crash gap.
    pub async fn prepare_thread_creation_receipt(
        &self,
        reservation: &ThreadCreationReservation,
        receipt_json: &str,
    ) -> anyhow::Result<()> {
        anyhow::ensure!(
            receipt_json.len() <= MAX_CREATION_RECEIPT_BYTES,
            "oversized creation receipt"
        );
        let result = sqlx::query("UPDATE thread_creation_operations SET receipt_json = ? WHERE idempotency_key = ? AND thread_id = ? AND parameters_sha256 = ? AND phase = 'pending' AND rollout_path IS NOT NULL AND (receipt_json IS NULL OR receipt_json = ?)")
            .bind(receipt_json).bind(&reservation.idempotency_key).bind(reservation.thread_id.to_string())
            .bind(&reservation.parameters_sha256).bind(receipt_json).execute(self.pool.as_ref()).await?;
        anyhow::ensure!(
            result.rows_affected() == 1,
            "creation receipt lost its original binding"
        );
        Ok(())
    }

    /// Only the original owner calls this after verifying durable exact rollout identity.
    pub async fn commit_thread_creation_receipt(
        &self,
        reservation: &ThreadCreationReservation,
    ) -> anyhow::Result<()> {
        anyhow::ensure!(
            !self
                .thread_queue
                .thread_queue_is_sealed_for_deletion(reservation.thread_id)
                .await?,
            "creation is sealed for deletion"
        );
        let result = sqlx::query("UPDATE thread_creation_operations SET phase = 'created' WHERE idempotency_key = ? AND thread_id = ? AND parameters_sha256 = ? AND phase = 'pending' AND rollout_path IS NOT NULL AND receipt_json IS NOT NULL")
            .bind(&reservation.idempotency_key).bind(reservation.thread_id.to_string())
            .bind(&reservation.parameters_sha256).execute(self.pool.as_ref()).await?;
        anyhow::ensure!(
            result.rows_affected() == 1,
            "creation commit lost its original binding"
        );
        Ok(())
    }

    /// Keep permanent key tombstones before any external hard-delete effect.
    pub async fn tombstone_thread_creations(&self, thread_ids: &[ThreadId]) -> anyhow::Result<()> {
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        for id in thread_ids {
            sqlx::query(
                "UPDATE thread_creation_operations SET phase = 'deleted' WHERE thread_id = ?",
            )
            .bind(id.to_string())
            .execute(&mut *tx)
            .await?;
        }
        tx.commit().await?;
        Ok(())
    }
}

fn creation_from_row(row: sqlx::sqlite::SqliteRow) -> anyhow::Result<ThreadCreationRecord> {
    let phase: String = row.try_get("phase")?;
    Ok(ThreadCreationRecord {
        reservation: ThreadCreationReservation {
            idempotency_key: row.try_get("idempotency_key")?,
            parameters_sha256: row.try_get("parameters_sha256")?,
            thread_id: ThreadId::from_string(&row.try_get::<String, _>("thread_id")?)?,
            project_id: row.try_get("project_id")?,
            cwd: PathBuf::from(row.try_get::<String, _>("cwd")?),
            thread_source: row.try_get("thread_source")?,
        },
        rollout_path: row
            .try_get::<Option<String>, _>("rollout_path")?
            .map(PathBuf::from),
        receipt_json: row.try_get("receipt_json")?,
        phase: match phase.as_str() {
            "pending" => ThreadCreationPhase::Pending,
            "created" => ThreadCreationPhase::Created,
            "deleted" => ThreadCreationPhase::Deleted,
            "abandoned" => ThreadCreationPhase::Abandoned,
            _ => anyhow::bail!("invalid creation phase"),
        },
    })
}

#[cfg(test)]
#[path = "thread_creation_tests.rs"]
mod tests;
