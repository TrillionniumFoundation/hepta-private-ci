//! Destination-owned idempotency/apply boundary for cross-owner operations.
//!
//! `kernel.operations` owns source intent/retry/reconciliation state. This
//! module owns only the destination-side durable application receipt inside the
//! existing CognitiveStore database. The same operation identity and semantic
//! digest is idempotent; identity reuse with changed semantics or payload is a
//! conflict. A successful return means the exact payload is durably committed
//! in the destination owner store, not merely accepted by a transport queue.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::Sha256Digest;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::cognitive_store::unavailable;
use crate::cognitive_store::validate_key;
use crate::framing::frame_part;

pub const MAX_CROSS_OWNER_OPERATION_ROWS: i64 = 100_000;
pub const MAX_CROSS_OWNER_OPERATION_PAYLOAD_BYTES: usize = 1_048_576;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CrossOwnerOperationApply {
    pub operation_id: String,
    pub source_owner_id: String,
    pub semantic_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
    pub payload: Vec<u8>,
}

impl CrossOwnerOperationApply {
    fn validate(&self) -> Result<(), CognitiveStoreError> {
        validate_key(&self.operation_id, "cross-owner operation id")?;
        validate_key(&self.source_owner_id, "cross-owner source owner")?;
        if self.semantic_digest.as_str().bytes().all(|byte| byte == b'0') {
            return Err(CognitiveStoreError::Invalid(
                "cross-owner semantic digest must be nonzero".to_string(),
            ));
        }
        if self.payload.is_empty() || self.payload.len() > MAX_CROSS_OWNER_OPERATION_PAYLOAD_BYTES {
            return Err(CognitiveStoreError::Invalid(format!(
                "cross-owner payload must contain 1..={MAX_CROSS_OWNER_OPERATION_PAYLOAD_BYTES} bytes"
            )));
        }
        if Sha256Digest::for_bytes(&self.payload) != self.payload_digest {
            return Err(CognitiveStoreError::Invalid(
                "cross-owner payload digest mismatch".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CrossOwnerOperationReceipt {
    pub operation_id: String,
    pub source_owner_id: String,
    pub destination_owner_agent_id: String,
    pub semantic_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
    pub receipt_digest: Sha256Digest,
    pub applied_at_unix_seconds: i64,
    pub replayed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct StoredCrossOwnerOperation {
    operation_id: String,
    source_owner_id: String,
    destination_owner_agent_id: String,
    semantic_digest: Sha256Digest,
    payload_digest: Sha256Digest,
    payload: Vec<u8>,
    receipt_digest: Sha256Digest,
    applied_at_unix_seconds: i64,
}

impl CognitiveStore {
    /// Atomically deduplicate and durably apply one cross-owner operation to
    /// the destination-owned CognitiveStore inbox.
    ///
    /// This is the terminal destination effect for this narrow contract. It
    /// neither dispatches another queue nor writes `kernel.operations` state.
    pub async fn apply_cross_owner_operation(
        &self,
        apply: &CrossOwnerOperationApply,
    ) -> Result<CrossOwnerOperationReceipt, CognitiveStoreError> {
        apply.validate()?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;

        if let Some(existing) =
            load_cross_owner_operation_tx(&mut transaction, &apply.operation_id).await?
        {
            ensure_exact_replay(self, &existing, apply)?;
            transaction.commit().await.map_err(unavailable)?;
            return Ok(existing.receipt(/*replayed*/ true));
        }

        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_cross_owner_operations")
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
        if count >= MAX_CROSS_OWNER_OPERATION_ROWS {
            return Err(CognitiveStoreError::Invalid(format!(
                "cross-owner operation capacity exceeded; maximum is {MAX_CROSS_OWNER_OPERATION_ROWS}"
            )));
        }

        let applied_at_unix_seconds = now_unix_seconds()?;
        let receipt_digest = cross_owner_receipt_digest(
            self.owner_agent_id().as_str(),
            &apply.operation_id,
            &apply.source_owner_id,
            &apply.semantic_digest,
            &apply.payload_digest,
            applied_at_unix_seconds,
        );
        sqlx::query(
            "INSERT INTO cognitive_cross_owner_operations (
                operation_id, source_owner_id, semantic_sha256, payload_sha256,
                payload, destination_owner_agent_id, receipt_sha256,
                applied_at_unix_seconds
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(&apply.operation_id)
        .bind(&apply.source_owner_id)
        .bind(apply.semantic_digest.as_str())
        .bind(apply.payload_digest.as_str())
        .bind(&apply.payload)
        .bind(self.owner_agent_id().as_str())
        .bind(receipt_digest.as_str())
        .bind(applied_at_unix_seconds)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;

        let stored = load_cross_owner_operation_tx(&mut transaction, &apply.operation_id)
            .await?
            .ok_or_else(|| {
                CognitiveStoreError::Corrupt(
                    "cross-owner operation disappeared before commit".to_string(),
                )
            })?;
        ensure_exact_replay(self, &stored, apply)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(stored.receipt(/*replayed*/ false))
    }

    /// Observe whether this destination durably applied the exact semantic
    /// operation. Missing is authoritative `not applied` for this local
    /// database; semantic drift is a conflict rather than a false success.
    pub async fn observe_cross_owner_operation(
        &self,
        operation_id: &str,
        semantic_digest: &Sha256Digest,
        payload_digest: &Sha256Digest,
    ) -> Result<Option<CrossOwnerOperationReceipt>, CognitiveStoreError> {
        validate_key(operation_id, "cross-owner operation id")?;
        let row = sqlx::query(
            "SELECT * FROM cognitive_cross_owner_operations WHERE operation_id = ?",
        )
        .bind(operation_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(unavailable)?;
        let Some(row) = row else {
            return Ok(None);
        };
        let stored = decode_cross_owner_operation(row)?;
        if &stored.semantic_digest != semantic_digest || &stored.payload_digest != payload_digest {
            return Err(CognitiveStoreError::Conflict(format!(
                "cross-owner operation {operation_id} was reused with changed semantics"
            )));
        }
        ensure_stored_receipt(self, &stored)?;
        Ok(Some(stored.receipt(/*replayed*/ true)))
    }
}

impl StoredCrossOwnerOperation {
    fn receipt(&self, replayed: bool) -> CrossOwnerOperationReceipt {
        CrossOwnerOperationReceipt {
            operation_id: self.operation_id.clone(),
            source_owner_id: self.source_owner_id.clone(),
            destination_owner_agent_id: self.destination_owner_agent_id.clone(),
            semantic_digest: self.semantic_digest.clone(),
            payload_digest: self.payload_digest.clone(),
            receipt_digest: self.receipt_digest.clone(),
            applied_at_unix_seconds: self.applied_at_unix_seconds,
            replayed,
        }
    }
}

fn ensure_exact_replay(
    store: &CognitiveStore,
    stored: &StoredCrossOwnerOperation,
    apply: &CrossOwnerOperationApply,
) -> Result<(), CognitiveStoreError> {
    ensure_stored_receipt(store, stored)?;
    if stored.operation_id != apply.operation_id
        || stored.source_owner_id != apply.source_owner_id
        || stored.semantic_digest != apply.semantic_digest
        || stored.payload_digest != apply.payload_digest
        || stored.payload != apply.payload
    {
        return Err(CognitiveStoreError::Conflict(format!(
            "cross-owner operation {} was reused with changed semantics",
            apply.operation_id
        )));
    }
    Ok(())
}

fn ensure_stored_receipt(
    store: &CognitiveStore,
    stored: &StoredCrossOwnerOperation,
) -> Result<(), CognitiveStoreError> {
    if stored.destination_owner_agent_id != store.owner_agent_id().as_str() {
        return Err(CognitiveStoreError::Corrupt(
            "cross-owner operation belongs to another destination owner".to_string(),
        ));
    }
    if stored.payload.is_empty() || stored.payload.len() > MAX_CROSS_OWNER_OPERATION_PAYLOAD_BYTES {
        return Err(CognitiveStoreError::Corrupt(
            "stored cross-owner payload size is invalid".to_string(),
        ));
    }
    if Sha256Digest::for_bytes(&stored.payload) != stored.payload_digest {
        return Err(CognitiveStoreError::Corrupt(
            "stored cross-owner payload digest mismatch".to_string(),
        ));
    }
    let expected = cross_owner_receipt_digest(
        &stored.destination_owner_agent_id,
        &stored.operation_id,
        &stored.source_owner_id,
        &stored.semantic_digest,
        &stored.payload_digest,
        stored.applied_at_unix_seconds,
    );
    if expected != stored.receipt_digest {
        return Err(CognitiveStoreError::Corrupt(
            "stored cross-owner operation receipt digest mismatch".to_string(),
        ));
    }
    Ok(())
}

async fn load_cross_owner_operation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Option<StoredCrossOwnerOperation>, CognitiveStoreError> {
    sqlx::query("SELECT * FROM cognitive_cross_owner_operations WHERE operation_id = ?")
        .bind(operation_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(unavailable)?
        .map(decode_cross_owner_operation)
        .transpose()
}

fn decode_cross_owner_operation(
    row: SqliteRow,
) -> Result<StoredCrossOwnerOperation, CognitiveStoreError> {
    let operation_id: String = row.try_get("operation_id").map_err(unavailable)?;
    let source_owner_id: String = row.try_get("source_owner_id").map_err(unavailable)?;
    let destination_owner_agent_id: String =
        row.try_get("destination_owner_agent_id").map_err(unavailable)?;
    validate_key(&operation_id, "stored cross-owner operation id")?;
    validate_key(&source_owner_id, "stored cross-owner source owner")?;
    validate_key(
        &destination_owner_agent_id,
        "stored cross-owner destination owner",
    )?;
    let semantic_digest = parse_digest(&row, "semantic_sha256")?;
    let payload_digest = parse_digest(&row, "payload_sha256")?;
    let receipt_digest = parse_digest(&row, "receipt_sha256")?;
    let payload: Vec<u8> = row.try_get("payload").map_err(unavailable)?;
    let applied_at_unix_seconds: i64 =
        row.try_get("applied_at_unix_seconds").map_err(unavailable)?;
    if applied_at_unix_seconds < 0 {
        return Err(CognitiveStoreError::Corrupt(
            "stored cross-owner timestamp is negative".to_string(),
        ));
    }
    Ok(StoredCrossOwnerOperation {
        operation_id,
        source_owner_id,
        destination_owner_agent_id,
        semantic_digest,
        payload_digest,
        payload,
        receipt_digest,
        applied_at_unix_seconds,
    })
}

fn parse_digest(row: &SqliteRow, column: &str) -> Result<Sha256Digest, CognitiveStoreError> {
    Sha256Digest::parse(row.try_get::<String, _>(column).map_err(unavailable)?)
        .map_err(CognitiveStoreError::Corrupt)
}

fn cross_owner_receipt_digest(
    destination_owner_agent_id: &str,
    operation_id: &str,
    source_owner_id: &str,
    semantic_digest: &Sha256Digest,
    payload_digest: &Sha256Digest,
    applied_at_unix_seconds: i64,
) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(
        &mut hasher,
        b"hepta:cognitive:cross-owner-operation-receipt:v1",
    );
    frame_part(&mut hasher, destination_owner_agent_id.as_bytes());
    frame_part(&mut hasher, operation_id.as_bytes());
    frame_part(&mut hasher, source_owner_id.as_bytes());
    frame_part(&mut hasher, semantic_digest.as_str().as_bytes());
    frame_part(&mut hasher, payload_digest.as_str().as_bytes());
    frame_part(&mut hasher, &applied_at_unix_seconds.to_be_bytes());
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn now_unix_seconds() -> Result<i64, CognitiveStoreError> {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
        .as_secs();
    i64::try_from(seconds)
        .map_err(|_| CognitiveStoreError::Unavailable("system time exceeds SQLite INTEGER".into()))
}

/// Reopen verifier for the destination-owned dedupe/apply ledger.
pub(crate) async fn verify_cross_owner_operations(
    pool: &SqlitePool,
    owner: &codex_hepta_contracts::AgentId,
) -> Result<(), CognitiveStoreError> {
    let rows = sqlx::query(
        "SELECT * FROM cognitive_cross_owner_operations ORDER BY operation_id LIMIT ?",
    )
    .bind(MAX_CROSS_OWNER_OPERATION_ROWS + 1)
    .fetch_all(pool)
    .await
    .map_err(|error| {
        CognitiveStoreError::Corrupt(format!(
            "cross-owner operation inbox is unavailable during reopen verification: {error}"
        ))
    })?;
    if i64::try_from(rows.len()).unwrap_or(i64::MAX) > MAX_CROSS_OWNER_OPERATION_ROWS {
        return Err(CognitiveStoreError::Corrupt(format!(
            "cross-owner operation inbox exceeds {MAX_CROSS_OWNER_OPERATION_ROWS} rows"
        )));
    }
    for row in rows {
        let stored = decode_cross_owner_operation(row)?;
        if stored.destination_owner_agent_id != owner.as_str() {
            return Err(CognitiveStoreError::Corrupt(
                "cross-owner operation destination owner drift".to_string(),
            ));
        }
        let expected = cross_owner_receipt_digest(
            &stored.destination_owner_agent_id,
            &stored.operation_id,
            &stored.source_owner_id,
            &stored.semantic_digest,
            &stored.payload_digest,
            stored.applied_at_unix_seconds,
        );
        if stored.payload.is_empty()
            || stored.payload.len() > MAX_CROSS_OWNER_OPERATION_PAYLOAD_BYTES
            || Sha256Digest::for_bytes(&stored.payload) != stored.payload_digest
            || expected != stored.receipt_digest
        {
            return Err(CognitiveStoreError::Corrupt(
                "cross-owner operation inbox failed semantic integrity verification".to_string(),
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn apply() -> CrossOwnerOperationApply {
        CrossOwnerOperationApply {
            operation_id: "operation:cross-owner:test:1".to_string(),
            source_owner_id: "durability-kernel".to_string(),
            semantic_digest: Sha256Digest::for_bytes(b"semantic"),
            payload_digest: Sha256Digest::for_bytes(b"payload"),
            payload: b"payload".to_vec(),
        }
    }

    async fn store(temp: &TempDir) -> CognitiveStore {
        let owner = crate::cognitive_test_support::agent_id(211);
        CognitiveStore::open(&crate::cognitive_test_support::layout(temp, &owner))
            .await
            .unwrap()
    }

    #[tokio::test]
    async fn exact_replay_is_destination_deduplicated() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let first = store.apply_cross_owner_operation(&apply()).await.unwrap();
        assert!(!first.replayed);
        let replay = store.apply_cross_owner_operation(&apply()).await.unwrap();
        assert!(replay.replayed);
        assert_eq!(first.receipt_digest, replay.receipt_digest);
        let count: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_cross_owner_operations")
                .fetch_one(&store.pool)
                .await
                .unwrap();
        assert_eq!(count, 1);
    }

    #[tokio::test]
    async fn identity_reuse_with_payload_drift_conflicts() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        store.apply_cross_owner_operation(&apply()).await.unwrap();
        let mut drift = apply();
        drift.payload = b"changed".to_vec();
        drift.payload_digest = Sha256Digest::for_bytes(&drift.payload);
        assert!(matches!(
            store.apply_cross_owner_operation(&drift).await,
            Err(CognitiveStoreError::Conflict(_))
        ));
    }

    #[tokio::test]
    async fn payload_digest_mismatch_fails_before_mutation() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let mut invalid = apply();
        invalid.payload = b"changed".to_vec();
        assert!(matches!(
            store.apply_cross_owner_operation(&invalid).await,
            Err(CognitiveStoreError::Invalid(_))
        ));
        let count: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_cross_owner_operations")
                .fetch_one(&store.pool)
                .await
                .unwrap();
        assert_eq!(count, 0);
    }

    #[tokio::test]
    async fn reopen_preserves_authoritative_terminal_observation() {
        let temp = TempDir::new().unwrap();
        let owner = crate::cognitive_test_support::agent_id(212);
        let layout = crate::cognitive_test_support::layout(&temp, &owner);
        let store = CognitiveStore::open(&layout).await.unwrap();
        let first = store.apply_cross_owner_operation(&apply()).await.unwrap();
        store.pool.close().await;

        let reopened = CognitiveStore::open(&layout).await.unwrap();
        let observed = reopened
            .observe_cross_owner_operation(
                &apply().operation_id,
                &apply().semantic_digest,
                &apply().payload_digest,
            )
            .await
            .unwrap()
            .unwrap();
        assert!(observed.replayed);
        assert_eq!(observed.receipt_digest, first.receipt_digest);
    }
}
