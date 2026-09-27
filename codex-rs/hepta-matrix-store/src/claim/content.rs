use sqlx::Row;

use crate::MatrixDurableError;
use crate::MatrixDurableStore;

use super::sql::require_live_active_claim_tx;
use super::sql::to_i64;
use super::sql::unavailable;
use super::*;

const CONTENT_SCHEMA: &str = include_str!("../../migrations/0008_matrix_content_binding.sql");

impl MatrixDurableStore {
    /// Pin full canonical content and authenticated transaction scope before
    /// requesting authority. This operation grants no permission to send.
    ///
    /// An identical retry is idempotent. A different edit target, body, device,
    /// session or destination cannot reuse this stable transaction. Unpinned
    /// legacy attempts are not automatically reinterpreted after an upgrade.
    pub async fn pin_outbox_content(
        &self,
        claim: &MatrixFencedOutboxClaim,
        canonical_content_sha256: &str,
        scope_sha256: &str,
        recorded_at_ms: u64,
    ) -> Result<(), MatrixDurableError> {
        for digest in [canonical_content_sha256, scope_sha256] {
            if digest.len() != 64
                || digest.bytes().all(|byte| byte == b'0')
                || !digest.bytes().all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
            {
                return Err(MatrixDurableError::Invalid);
            }
        }
        let mut transaction = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        // Compare actual DDL, not merely the presence of named objects.
        // All three statements in this migration are separated by blank lines.
        for statement in CONTENT_SCHEMA.split("\n\n").filter(|sql| sql.starts_with("CREATE ")) {
            let name = statement.split_whitespace().nth(2).ok_or(MatrixDurableError::Corrupt)?;
            let actual: Option<String> = sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = ?")
                .bind(name)
                .fetch_optional(&mut *transaction)
                .await
                .map_err(unavailable)?;
            if actual.as_deref().map(normalized_sql) != Some(normalized_sql(statement)) {
                return Err(MatrixDurableError::Corrupt);
            }
        }
        let identity = claim.identity();
        require_live_active_claim_tx(&mut transaction, &identity, recorded_at_ms).await?;
        let record = claim.record();
        let raw_digest = Sha256Digest::for_bytes(&record.payload);
        let current: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM outbox_messages AS message
             JOIN matrix_dispatch_ledger AS dispatch USING (stable_txn_id)
             WHERE message.stable_txn_id = ? AND message.attempts = ?
               AND message.state = 'in_flight' AND message.room_id = ?
               AND message.binding_revision = ? AND message.generation = ?
               AND message.payload_sha256 = ? AND dispatch.payload_sha256 = message.payload_sha256
               AND dispatch.attempts = message.attempts",
        )
        .bind(identity.stable_txn_id.as_str())
        .bind(to_i64(identity.attempt)?)
        .bind(record.room_id.as_str())
        .bind(to_i64(record.binding_revision)?)
        .bind(to_i64(record.generation)?)
        .bind(raw_digest.as_str())
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if current != 1 {
            return Err(MatrixDurableError::Conflict);
        }
        let existing = sqlx::query(
            "SELECT canonicalization_version, canonical_content_sha256, scope_sha256,
                    source_payload_sha256
             FROM matrix_dispatch_content_bindings WHERE stable_txn_id = ?",
        )
        .bind(identity.stable_txn_id.as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if let Some(row) = existing {
            if row.try_get::<i64, _>("canonicalization_version").map_err(unavailable)? != 1
                || row.try_get::<String, _>("canonical_content_sha256").map_err(unavailable)? != canonical_content_sha256
                || row.try_get::<String, _>("scope_sha256").map_err(unavailable)? != scope_sha256
                || row.try_get::<String, _>("source_payload_sha256").map_err(unavailable)? != raw_digest.as_str()
            {
                return Err(MatrixDurableError::Conflict);
            }
        } else {
            // No new pin may retroactively authorize an earlier unknown send.
            // The first new sender attempt pins before grant acquisition, so
            // subsequent legitimate retries always find the retained binding.
            if record.attempts != 1 {
                return Err(MatrixDurableError::Conflict);
            }
            let prior: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM matrix_dispatch_authority_claims WHERE stable_txn_id = ?",
            )
            .bind(identity.stable_txn_id.as_str())
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
            if prior != 0 {
                return Err(MatrixDurableError::Conflict);
            }
            sqlx::query(
                "INSERT INTO matrix_dispatch_content_bindings (
                    stable_txn_id, canonicalization_version, canonical_content_sha256,
                    scope_sha256, source_payload_sha256, pinned_at_ms
                 ) VALUES (?, 1, ?, ?, ?, ?)",
            )
            .bind(identity.stable_txn_id.as_str())
            .bind(canonical_content_sha256)
            .bind(scope_sha256)
            .bind(raw_digest.as_str())
            .bind(to_i64(recorded_at_ms)?)
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
        }
        transaction.commit().await.map_err(unavailable)
    }
}

fn normalized_sql(value: &str) -> String {
    value.trim().trim_end_matches(';').split_whitespace().collect::<Vec<_>>().join(" ")
}
