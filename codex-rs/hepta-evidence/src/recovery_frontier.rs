use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;

#[path = "recovery_snapshot.rs"]
mod snapshot;

pub const EVIDENCE_DATABASE_LINEAGE: &str = "hepta_evidence_2.sqlite";

/// Historical Rust name retained for source compatibility. The wire version is
/// explicit: 1 commits public envelopes, 2 commits full stored admission records
/// and the enrolled store identity. A V1 digest must never be relabelled as V2.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceRecoverySnapshotV1 {
    pub schema_version: u32,
    pub database_lineage: String,
    pub migration_set_sha256: Sha256Digest,
    pub qualification_max_seq: u64,
    pub qualification_frontier_sha256: Sha256Digest,
    pub authbus_replay_frontier_sha256: Sha256Digest,
}

impl HeptaEvidenceStore {
    pub async fn bind_recovery_store_id(&self, store_id: &str) -> Result<(), EvidenceError> {
        StableId::new(store_id.to_string()).map_err(|error| {
            EvidenceError::InvalidRecord(format!("invalid evidence recovery store id: {error}"))
        })?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let existing: Option<String> = sqlx::query_scalar(
            "SELECT store_id FROM evidence_recovery_identity WHERE singleton = 1",
        )
        .fetch_optional(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        match existing {
            Some(existing) if existing != store_id => {
                return Err(EvidenceError::IdempotencyConflict {
                    record_id: "evidence_recovery_identity".to_string(),
                });
            }
            Some(_) => {}
            None => {
                sqlx::query(
                    "INSERT INTO evidence_recovery_identity (singleton, store_id) VALUES (1, ?)",
                )
                .bind(store_id)
                .execute(&mut *transaction)
                .await
                .map_err(classify_sqlx_error)?;
            }
        }
        transaction.commit().await.map_err(classify_sqlx_error)
    }

    pub async fn recovery_store_id(&self) -> Result<Option<String>, EvidenceError> {
        sqlx::query_scalar("SELECT store_id FROM evidence_recovery_identity WHERE singleton = 1")
            .fetch_optional(&self.pool)
            .await
            .map_err(classify_sqlx_error)
    }

    /// Legacy V1 digest semantics, now read from one consistent transaction.
    pub async fn recovery_snapshot(&self) -> Result<EvidenceRecoverySnapshotV1, EvidenceError> {
        snapshot::collect(&self.pool, snapshot::Domain::LegacyEnvelope).await
    }

    /// Full stored admission commitment. Requires explicit store enrollment.
    /// This does not reconstruct signatures absent from historical V1 rows, nor
    /// claim that a backup or an external frontier has been durably published.
    pub async fn authenticated_recovery_snapshot(
        &self,
    ) -> Result<EvidenceRecoverySnapshotV1, EvidenceError> {
        snapshot::collect(&self.pool, snapshot::Domain::AuthenticatedAdmission).await
    }
}

/// Reuse a caller's transaction: no nested transaction or second pool checkout.
pub(crate) async fn authenticated_snapshot_in_transaction(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
) -> Result<EvidenceRecoverySnapshotV1, EvidenceError> {
    snapshot::collect_in_transaction(transaction, snapshot::Domain::AuthenticatedAdmission).await
}

#[cfg(test)]
#[path = "recovery_snapshot_tests.rs"]
mod tests;
