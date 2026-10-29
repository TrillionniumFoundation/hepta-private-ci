//! Finite destination-owned entry fence, not a worker or terminal authority.

use codex_hepta_operations::DestinationApplyStart;
use codex_hepta_operations::DestinationDedupeStore;
use codex_hepta_operations::DestinationOperationIdentity;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::SqliteConnection;
use sqlx::SqlitePool;

pub(super) const CAPACITY: usize = 16;

pub(super) struct OrdinaryCpuOwner {
    pub(super) pool: SqlitePool,
    dedupe: DestinationDedupeStore,
}

#[derive(Debug)]
pub(super) enum Entry {
    New(usize),
    Retained,
}

impl OrdinaryCpuOwner {
    /// The trusted embedding supplies its existing private, fully durable owner
    /// pool and migration lineage. This API does not open or secure a path.
    pub(super) async fn from_migrated_pool(pool: SqlitePool) -> Result<Self, String> {
        let mut connection = pool.acquire().await.map_err(|e| e.to_string())?;
        verify_durable(&mut connection).await?;
        drop(connection);
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM ordinary_cpu_entries")
            .fetch_one(&pool)
            .await
            .map_err(|e| e.to_string())?;
        if count > CAPACITY as i64 {
            return Err("ordinary CPU owner exceeds fixed capacity".to_owned());
        }
        let dedupe = DestinationDedupeStore::from_migrated_pool(pool.clone())
            .await
            .map_err(|e| e.to_string())?;
        Ok(Self { pool, dedupe })
    }

    /// Commit the irreversible, finite entry before a caller may spawn. Once
    /// committed, errors/cancellation/lost ownership never authorize a relaunch.
    pub(super) async fn enter(&self, intent: &OperationIntentV1) -> Result<Entry, String> {
        let identity = DestinationOperationIdentity {
            destination: intent.destination_id().clone(),
            scope_id: StableId::new(intent.scope_digest().to_string())
                .map_err(|e| e.to_string())?,
            operation_id: intent.operation_id().clone(),
            payload_digest: intent.semantic_digest(),
        };
        let start = self
            .dedupe
            .begin_apply(&identity)
            .await
            .map_err(|e| e.to_string())?;
        let mut apply = match start {
            DestinationApplyStart::AlreadyApplied(_) => {
                self.entry(intent)
                    .await?
                    .ok_or("dedupe entry has no owner row")?;
                return Ok(Entry::Retained);
            }
            DestinationApplyStart::Apply(apply) => apply,
        };
        let transaction = apply.transaction().map_err(|e| e.to_string())?;
        verify_durable(transaction).await?;
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM ordinary_cpu_entries")
            .fetch_one(&mut **transaction)
            .await
            .map_err(|e| e.to_string())?;
        if count >= CAPACITY as i64 {
            return Err(
                "ordinary CPU lifetime capacity exhausted; retained rows cannot be pruned"
                    .to_owned(),
            );
        }
        sqlx::query("INSERT INTO ordinary_cpu_entries(slot, operation_id, semantic_digest) VALUES (?, ?, ?)")
            .bind(count).bind(intent.operation_id().as_str()).bind(intent.semantic_digest().as_array().as_slice())
            .execute(&mut **transaction).await.map_err(|e| e.to_string())?;
        apply
            .commit_applied(intent.semantic_digest())
            .await
            .map_err(|e| e.to_string())?;
        Ok(Entry::New(count as usize))
    }

    pub(super) async fn entry(
        &self,
        intent: &OperationIntentV1,
    ) -> Result<Option<(usize, Option<String>)>, String> {
        let row = sqlx::query("SELECT slot, semantic_digest, terminal_receipt FROM ordinary_cpu_entries WHERE operation_id = ?")
            .bind(intent.operation_id().as_str()).fetch_optional(&self.pool).await.map_err(|e| e.to_string())?;
        let Some(row) = row else { return Ok(None) };
        let slot: i64 = row.try_get("slot").map_err(|e| e.to_string())?;
        let digest: Vec<u8> = row.try_get("semantic_digest").map_err(|e| e.to_string())?;
        if !(0..CAPACITY as i64).contains(&slot) || digest != intent.semantic_digest().as_array() {
            return Err("ordinary CPU owner row binding is corrupt or conflicts".to_owned());
        }
        Ok(Some((
            slot as usize,
            row.try_get("terminal_receipt").map_err(|e| e.to_string())?,
        )))
    }

    /// Only the live owned-Child observer calls this. A disk receipt alone
    /// never reconstructs a Child or qualifies post-process-loss terminality.
    pub(super) async fn record_terminal(
        &self,
        intent: &OperationIntentV1,
        receipt: &str,
    ) -> Result<(), String> {
        if receipt.is_empty() || receipt.len() > 128 {
            return Err("unbounded ordinary child terminal receipt".to_owned());
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|e| e.to_string())?;
        verify_durable(&mut transaction).await?;
        sqlx::query("UPDATE ordinary_cpu_entries SET terminal_receipt = ? WHERE operation_id = ? AND semantic_digest = ? AND terminal_receipt IS NULL")
            .bind(receipt).bind(intent.operation_id().as_str()).bind(intent.semantic_digest().as_array().as_slice())
            .execute(&mut *transaction).await.map_err(|e| e.to_string())?;
        let stored: Option<Option<String>> = sqlx::query_scalar("SELECT terminal_receipt FROM ordinary_cpu_entries WHERE operation_id = ? AND semantic_digest = ?")
            .bind(intent.operation_id().as_str()).bind(intent.semantic_digest().as_array().as_slice())
            .fetch_optional(&mut *transaction).await.map_err(|e| e.to_string())?;
        if stored.as_ref().and_then(Option::as_deref) != Some(receipt) {
            return Err("ordinary child terminal binding conflicts or is missing".to_owned());
        }
        transaction.commit().await.map_err(|e| e.to_string())
    }
}

pub(super) async fn verify_durable(connection: &mut SqliteConnection) -> Result<(), String> {
    let synchronous: i64 = sqlx::query_scalar("PRAGMA synchronous")
        .fetch_one(&mut *connection)
        .await
        .map_err(|e| e.to_string())?;
    let journal: String = sqlx::query_scalar("PRAGMA journal_mode")
        .fetch_one(connection)
        .await
        .map_err(|e| e.to_string())?;
    if synchronous != 2 || !journal.eq_ignore_ascii_case("wal") {
        return Err("ordinary CPU owner requires SQLite WAL/synchronous FULL".to_owned());
    }
    Ok(())
}

#[cfg(test)]
#[path = "ordinary_cpu_owner_tests.rs"]
pub(super) mod tests;
