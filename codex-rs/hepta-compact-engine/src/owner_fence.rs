//! Private identity check shared by every owned compaction write transaction.
use codex_hepta_types::Digest32;
use sqlx::{Row, Sqlite, SqliteConnection, SqlitePool, Transaction};

use crate::durable::DurableCompactionError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct OwnerWriteFenceV2 {
    pub(crate) root_key_digest: Digest32,
    pub(crate) lease_token_digest: Digest32,
    pub(crate) lease_epoch: u64,
    pub(crate) minimum_expiry_unix_seconds: u64,
}

impl OwnerWriteFenceV2 {
    pub(crate) async fn begin(
        &self,
        pool: &SqlitePool,
        owner_id: &str,
        expected_manifest: Digest32,
        now: u64,
    ) -> Result<Transaction<'static, Sqlite>, DurableCompactionError> {
        let mut transaction = pool.begin_with("BEGIN IMMEDIATE").await?;
        self.verify_tx(&mut transaction, owner_id, expected_manifest, now)
            .await?;
        Ok(transaction)
    }

    pub(crate) async fn verify_tx(
        &self,
        connection: &mut SqliteConnection,
        owner_id: &str,
        expected_manifest: Digest32,
        now: u64,
    ) -> Result<(), DurableCompactionError> {
        let row = sqlx::query(
            "SELECT f.root_key_digest AS fence_root_key_digest,
                    f.lease_token_digest, f.lease_epoch,
                    f.lease_expires_at_unix_seconds, a.manifest_digest,
                    m.root_key_digest AS manifest_root_key_digest
             FROM compaction_owner_fence_v2 AS f
             JOIN active_compaction_manifest_v2 AS a ON a.owner_id = f.owner_id
             JOIN compaction_manifest_log_v2 AS m
               ON m.owner_id = a.owner_id AND m.manifest_digest = a.manifest_digest
             WHERE f.owner_id = ?",
        )
        .bind(owner_id)
        .fetch_optional(&mut *connection)
        .await?
        .ok_or_else(|| conflict("durable owner fence or active manifest disappeared"))?;

        let root: String = row.try_get("fence_root_key_digest")?;
        let token: String = row.try_get("lease_token_digest")?;
        let epoch: i64 = row.try_get("lease_epoch")?;
        let expiry: i64 = row.try_get("lease_expires_at_unix_seconds")?;
        let manifest: String = row.try_get("manifest_digest")?;
        let manifest_root: String = row.try_get("manifest_root_key_digest")?;
        if root != self.root_key_digest.to_string()
            || token != self.lease_token_digest.to_string()
            || u64::try_from(epoch).ok() != Some(self.lease_epoch)
            || u64::try_from(expiry)
                .ok()
                .is_none_or(|value| value < self.minimum_expiry_unix_seconds || value <= now)
            || manifest != expected_manifest.to_string()
            || manifest_root != self.root_key_digest.to_string()
        {
            return Err(conflict(
                "write lost its exact lease, root pin or active manifest fence",
            ));
        }
        Ok(())
    }
}

fn conflict(message: &str) -> DurableCompactionError {
    DurableCompactionError::Conflict(message.to_string())
}
