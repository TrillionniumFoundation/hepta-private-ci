use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::EvidenceAcceptedFrontierV1;
use crate::EvidenceError;
use crate::EvidenceFrontierDurableAckV1;
use crate::EvidenceRecoverySnapshotV1;
use crate::HeptaEvidenceStore;
use crate::canonical::canonical_json;
use crate::frontier_acceptance::accept_in_transaction;
use crate::recovery_frontier::authenticated_snapshot_in_transaction;
use crate::schema_validation::classify_sqlx_error;

const MAX_PUBLICATION_LEASE_MS: u64 = 24 * 60 * 60 * 1000;
const MAX_PUBLICATION_BATCH_INTENTS: usize = 512;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EvidencePublicationOwnerLeaseV1 {
    pub store_id: String,
    pub owner_id: String,
    pub owner_generation: u64,
    pub lease_expires_at_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidencePublicationBatchStateV1 {
    Prepared,
    Dispatching,
    Indeterminate,
    Acknowledged,
}

impl EvidencePublicationBatchStateV1 {
    fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::Dispatching => "dispatching",
            Self::Indeterminate => "indeterminate",
            Self::Acknowledged => "acknowledged",
        }
    }

    fn parse(value: &str) -> Result<Self, EvidenceError> {
        match value {
            "prepared" => Ok(Self::Prepared),
            "dispatching" => Ok(Self::Dispatching),
            "indeterminate" => Ok(Self::Indeterminate),
            "acknowledged" => Ok(Self::Acknowledged),
            _ => Err(EvidenceError::Corrupt(
                "unknown evidence publication batch state".to_string(),
            )),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EvidencePublicationBatchV1 {
    pub batch_id: String,
    pub store_id: String,
    pub prepared_owner_id: String,
    pub prepared_owner_generation: u64,
    pub state: EvidencePublicationBatchStateV1,
    pub first_intent_seq: u64,
    pub last_intent_seq: u64,
    pub intent_count: usize,
    pub snapshot: EvidenceRecoverySnapshotV1,
    pub snapshot_sha256: Sha256Digest,
    pub expected_frontier_generation: Option<u64>,
    pub expected_frontier_sha256: Option<Sha256Digest>,
    pub expected_backend_identity_sha256: Option<Sha256Digest>,
    pub proposed_frontier_generation: u64,
    pub proposed_frontier_sha256: Option<Sha256Digest>,
    pub backend_identity_sha256: Option<Sha256Digest>,
    pub durable_audit_sequence: Option<u64>,
    pub created_at_unix_ms: u64,
    pub updated_at_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvidencePublicationLatestV1 {
    pub frontier_generation: u64,
    pub frontier_sha256: Sha256Digest,
    pub backend_identity_sha256: Sha256Digest,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EvidencePublicationLatestDisposition {
    RetrySameBatch,
    RecoverDurableAcknowledgement,
    AlreadyAcknowledged,
    Conflict,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EvidencePublicationAckDisposition {
    Acknowledged,
    AlreadyAcknowledged,
}

impl HeptaEvidenceStore {
    /// Acquire the single durable publication owner. A live owner cannot be
    /// replaced. An expired owner is replaced by exactly the next generation;
    /// in-flight batches keep their identity and are reconciled by the successor.
    pub async fn claim_publication_owner(
        &self,
        owner_id: &str,
        now_unix_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<EvidencePublicationOwnerLeaseV1, EvidenceError> {
        validate_stable_id(owner_id, "publication owner")?;
        if now_unix_ms == 0
            || lease_duration_ms == 0
            || lease_duration_ms > MAX_PUBLICATION_LEASE_MS
        {
            return Err(invalid(
                "publication owner lease duration must be between one millisecond and 24 hours",
            ));
        }
        let expires = now_unix_ms
            .checked_add(lease_duration_ms)
            .ok_or_else(|| invalid("publication owner lease timestamp overflow"))?;
        let now = to_i64(now_unix_ms, "publication owner timestamp")?;
        let expires_i64 = to_i64(expires, "publication owner lease expiry")?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let store_id = enrolled_store_id(&mut transaction).await?;
        let row = sqlx::query(
            "SELECT owner_id, owner_generation, lease_expires_at_ms
             FROM evidence_publication_owner WHERE store_id = ?",
        )
        .bind(&store_id)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let generation = match row {
            None => {
                sqlx::query(
                    "INSERT INTO evidence_publication_owner
                     (store_id, owner_id, owner_generation, lease_expires_at_ms, updated_at_ms)
                     VALUES (?, ?, 1, ?, ?)",
                )
                .bind(&store_id)
                .bind(owner_id)
                .bind(expires_i64)
                .bind(now)
                .execute(&mut *transaction)
                .await
                .map_err(classify_sqlx_error)?;
                1
            }
            Some(row) => {
                let current_owner: String = row.try_get("owner_id").map_err(classify_sqlx_error)?;
                let current_generation = positive_u64_from_i64(
                    row.try_get("owner_generation")
                        .map_err(classify_sqlx_error)?,
                    "publication owner generation",
                )?;
                let current_expiry = positive_u64_from_i64(
                    row.try_get("lease_expires_at_ms")
                        .map_err(classify_sqlx_error)?,
                    "publication owner lease expiry",
                )?;
                if current_owner == owner_id && current_expiry > now_unix_ms {
                    let extended = current_expiry.max(expires);
                    sqlx::query(
                        "UPDATE evidence_publication_owner
                         SET lease_expires_at_ms = ?, updated_at_ms = ?
                         WHERE store_id = ? AND owner_id = ? AND owner_generation = ?",
                    )
                    .bind(to_i64(extended, "publication owner lease expiry")?)
                    .bind(now)
                    .bind(&store_id)
                    .bind(owner_id)
                    .bind(to_i64(current_generation, "publication owner generation")?)
                    .execute(&mut *transaction)
                    .await
                    .map_err(classify_sqlx_error)?;
                    transaction.commit().await.map_err(classify_sqlx_error)?;
                    return Ok(EvidencePublicationOwnerLeaseV1 {
                        store_id,
                        owner_id: owner_id.to_string(),
                        owner_generation: current_generation,
                        lease_expires_at_unix_ms: extended,
                    });
                }
                if current_expiry > now_unix_ms {
                    return Err(EvidenceError::Unavailable(
                        "another evidence publication owner still holds the durable lease"
                            .to_string(),
                    ));
                }
                let next = current_generation
                    .checked_add(1)
                    .ok_or_else(|| invalid("publication owner generation exhausted"))?;
                sqlx::query(
                    "UPDATE evidence_publication_owner
                     SET owner_id = ?, owner_generation = ?, lease_expires_at_ms = ?, updated_at_ms = ?
                     WHERE store_id = ? AND owner_generation = ? AND lease_expires_at_ms <= ?",
                )
                .bind(owner_id)
                .bind(to_i64(next, "publication owner generation")?)
                .bind(expires_i64)
                .bind(now)
                .bind(&store_id)
                .bind(to_i64(current_generation, "publication owner generation")?)
                .bind(now)
                .execute(&mut *transaction)
                .await
                .map_err(classify_sqlx_error)?;
                next
            }
        };
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(EvidencePublicationOwnerLeaseV1 {
            store_id,
            owner_id: owner_id.to_string(),
            owner_generation: generation,
            lease_expires_at_unix_ms: expires,
        })
    }

    /// Prepare one deterministic batch and bind it to a single authenticated
    /// SQLite snapshot before any external effect. An unresolved predecessor
    /// batch is returned verbatim, so a restart never changes operation identity.
    pub async fn prepare_publication_batch(
        &self,
        lease: &EvidencePublicationOwnerLeaseV1,
        now_unix_ms: u64,
        maximum_intents: usize,
    ) -> Result<Option<EvidencePublicationBatchV1>, EvidenceError> {
        if maximum_intents == 0 || maximum_intents > MAX_PUBLICATION_BATCH_INTENTS {
            return Err(invalid(
                "publication batch must contain between one and 512 intents",
            ));
        }
        let now = to_i64(now_unix_ms, "publication preparation timestamp")?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        require_publication_owner(&mut transaction, lease, now_unix_ms).await?;
        if let Some(row) = sqlx::query(
            "SELECT * FROM evidence_publication_batches
             WHERE store_id = ? AND state IN ('prepared', 'dispatching', 'indeterminate')
             ORDER BY first_intent_seq ASC LIMIT 1",
        )
        .bind(&lease.store_id)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?
        {
            let batch = decode_batch(&row)?;
            transaction.commit().await.map_err(classify_sqlx_error)?;
            return Ok(Some(batch));
        }
        let rows = sqlx::query(
            "SELECT seq, operation_id, qualification_seq
             FROM evidence_publication_intents
             WHERE store_id = ? AND state = 'pending'
             ORDER BY qualification_seq ASC LIMIT ?",
        )
        .bind(&lease.store_id)
        .bind(i64::try_from(maximum_intents).map_err(|_| invalid("batch bound overflow"))?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        if rows.is_empty() {
            transaction.commit().await.map_err(classify_sqlx_error)?;
            return Ok(None);
        }
        let first_intent_seq = positive_u64_from_i64(
            rows.first()
                .expect("non-empty publication intent rows")
                .try_get("seq")
                .map_err(classify_sqlx_error)?,
            "publication intent sequence",
        )?;
        let last_intent_seq = positive_u64_from_i64(
            rows.last()
                .expect("non-empty publication intent rows")
                .try_get("seq")
                .map_err(classify_sqlx_error)?,
            "publication intent sequence",
        )?;
        let last_qualification_seq: i64 = rows
            .last()
            .expect("non-empty publication intent rows")
            .try_get("qualification_seq")
            .map_err(classify_sqlx_error)?;
        let first_operation: String = rows
            .first()
            .expect("non-empty publication intent rows")
            .try_get("operation_id")
            .map_err(classify_sqlx_error)?;
        let last_operation: String = rows
            .last()
            .expect("non-empty publication intent rows")
            .try_get("operation_id")
            .map_err(classify_sqlx_error)?;
        let snapshot = authenticated_snapshot_in_transaction(&mut transaction).await?;
        let snapshot_json = String::from_utf8(canonical_json(&snapshot)?)
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        let snapshot_sha256 = Sha256Digest::for_bytes(snapshot_json.as_bytes());
        let accepted = latest_accepted_in_transaction(&mut transaction, &lease.store_id).await?;
        let expected_frontier_generation = accepted.as_ref().map(|value| value.frontier_generation);
        let expected_frontier_sha256 = accepted.as_ref().map(|value| value.frontier_sha256.clone());
        let expected_backend_identity_sha256 = accepted
            .as_ref()
            .map(|value| value.backend_identity_sha256.clone());
        let proposed_frontier_generation = expected_frontier_generation
            .unwrap_or(0)
            .checked_add(1)
            .ok_or_else(|| invalid("publication frontier generation exhausted"))?;
        let batch_id = publication_batch_id(
            &lease.store_id,
            lease.owner_generation,
            &first_operation,
            &last_operation,
            &snapshot_sha256,
            proposed_frontier_generation,
        );
        sqlx::query(
            "INSERT INTO evidence_publication_batches (
                batch_id, store_id, prepared_owner_id, prepared_owner_generation,
                state, first_intent_seq, last_intent_seq, intent_count,
                snapshot_json, snapshot_sha256,
                expected_frontier_generation, expected_frontier_sha256,
                expected_backend_identity_sha256, proposed_frontier_generation,
                proposed_frontier_sha256, backend_identity_sha256,
                durable_audit_sequence, created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, 'prepared', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)",
        )
        .bind(&batch_id)
        .bind(&lease.store_id)
        .bind(&lease.owner_id)
        .bind(to_i64(
            lease.owner_generation,
            "publication owner generation",
        )?)
        .bind(to_i64(first_intent_seq, "publication intent sequence")?)
        .bind(to_i64(last_intent_seq, "publication intent sequence")?)
        .bind(i64::try_from(rows.len()).map_err(|_| invalid("batch size overflow"))?)
        .bind(&snapshot_json)
        .bind(snapshot_sha256.as_str())
        .bind(
            expected_frontier_generation
                .map(|value| to_i64(value, "expected frontier generation"))
                .transpose()?,
        )
        .bind(expected_frontier_sha256.as_ref().map(Sha256Digest::as_str))
        .bind(
            expected_backend_identity_sha256
                .as_ref()
                .map(Sha256Digest::as_str),
        )
        .bind(to_i64(
            proposed_frontier_generation,
            "proposed frontier generation",
        )?)
        .bind(now)
        .bind(now)
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let updated = sqlx::query(
            "UPDATE evidence_publication_intents
             SET state = 'batched', batch_id = ?, updated_at_ms = ?
             WHERE store_id = ? AND state = 'pending' AND qualification_seq <= ?",
        )
        .bind(&batch_id)
        .bind(now)
        .bind(&lease.store_id)
        .bind(last_qualification_seq)
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        if updated.rows_affected() != u64::try_from(rows.len()).unwrap_or(u64::MAX) {
            return Err(EvidenceError::Corrupt(
                "publication intent batch membership changed inside the write transaction"
                    .to_string(),
            ));
        }
        let row = sqlx::query("SELECT * FROM evidence_publication_batches WHERE batch_id = ?")
            .bind(&batch_id)
            .fetch_one(&mut *transaction)
            .await
            .map_err(classify_sqlx_error)?;
        let batch = decode_batch(&row)?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(Some(batch))
    }

    /// Persist the exact external CAS identity before dispatch. Retrying this
    /// method with identical semantics is idempotent; semantic drift conflicts.
    pub async fn mark_publication_dispatched(
        &self,
        lease: &EvidencePublicationOwnerLeaseV1,
        batch_id: &str,
        proposed_frontier_sha256: &Sha256Digest,
        backend_identity_sha256: &Sha256Digest,
        now_unix_ms: u64,
    ) -> Result<EvidencePublicationBatchV1, EvidenceError> {
        validate_stable_id(batch_id, "publication batch")?;
        let now = to_i64(now_unix_ms, "publication dispatch timestamp")?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        require_publication_owner(&mut transaction, lease, now_unix_ms).await?;
        let row = load_batch(&mut transaction, batch_id).await?;
        let batch = decode_batch(&row)?;
        if batch.store_id != lease.store_id {
            return Err(invalid("publication batch belongs to another store"));
        }
        if batch
            .expected_backend_identity_sha256
            .as_ref()
            .is_some_and(|expected| expected != backend_identity_sha256)
        {
            return Err(invalid(
                "publication backend identity differs from the previously accepted backend",
            ));
        }
        match batch.state {
            EvidencePublicationBatchStateV1::Prepared => {
                sqlx::query(
                    "UPDATE evidence_publication_batches
                     SET state = 'dispatching', proposed_frontier_sha256 = ?,
                         backend_identity_sha256 = ?, updated_at_ms = ?
                     WHERE batch_id = ? AND state = 'prepared'",
                )
                .bind(proposed_frontier_sha256.as_str())
                .bind(backend_identity_sha256.as_str())
                .bind(now)
                .bind(batch_id)
                .execute(&mut *transaction)
                .await
                .map_err(classify_sqlx_error)?;
            }
            EvidencePublicationBatchStateV1::Dispatching
            | EvidencePublicationBatchStateV1::Indeterminate
                if batch.proposed_frontier_sha256.as_ref() == Some(proposed_frontier_sha256)
                    && batch.backend_identity_sha256.as_ref() == Some(backend_identity_sha256) => {}
            EvidencePublicationBatchStateV1::Acknowledged
                if batch.proposed_frontier_sha256.as_ref() == Some(proposed_frontier_sha256)
                    && batch.backend_identity_sha256.as_ref() == Some(backend_identity_sha256) => {}
            _ => {
                return Err(EvidenceError::IdempotencyConflict {
                    record_id: batch_id.to_string(),
                });
            }
        }
        let row = load_batch(&mut transaction, batch_id).await?;
        let batch = decode_batch(&row)?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(batch)
    }

    /// Record an ambiguous CAS result without minting a replacement batch.
    pub async fn mark_publication_indeterminate(
        &self,
        lease: &EvidencePublicationOwnerLeaseV1,
        batch_id: &str,
        now_unix_ms: u64,
    ) -> Result<EvidencePublicationBatchV1, EvidenceError> {
        let now = to_i64(now_unix_ms, "publication indeterminate timestamp")?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        require_publication_owner(&mut transaction, lease, now_unix_ms).await?;
        let batch = decode_batch(&load_batch(&mut transaction, batch_id).await?)?;
        match batch.state {
            EvidencePublicationBatchStateV1::Dispatching => {
                sqlx::query(
                    "UPDATE evidence_publication_batches
                     SET state = 'indeterminate', updated_at_ms = ?
                     WHERE batch_id = ? AND state = 'dispatching'",
                )
                .bind(now)
                .bind(batch_id)
                .execute(&mut *transaction)
                .await
                .map_err(classify_sqlx_error)?;
            }
            EvidencePublicationBatchStateV1::Indeterminate
            | EvidencePublicationBatchStateV1::Acknowledged => {}
            EvidencePublicationBatchStateV1::Prepared => {
                return Err(invalid(
                    "publication cannot become indeterminate before durable dispatch fencing",
                ));
            }
        }
        let batch = decode_batch(&load_batch(&mut transaction, batch_id).await?)?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(batch)
    }

    /// Compare an authenticated latest read with the durable batch. A predecessor
    /// observation retries the SAME batch; the proposed value requires recovery
    /// of a durable acknowledgement; any third value is a conflict.
    pub async fn classify_publication_latest(
        &self,
        batch_id: &str,
        latest: Option<&EvidencePublicationLatestV1>,
    ) -> Result<EvidencePublicationLatestDisposition, EvidenceError> {
        let batch = self
            .publication_batch(batch_id)
            .await?
            .ok_or_else(|| invalid("publication batch does not exist"))?;
        if batch.state == EvidencePublicationBatchStateV1::Acknowledged {
            return Ok(EvidencePublicationLatestDisposition::AlreadyAcknowledged);
        }
        let proposed = match (
            batch.proposed_frontier_sha256.as_ref(),
            batch.backend_identity_sha256.as_ref(),
        ) {
            (Some(digest), Some(backend)) => Some((digest, backend)),
            _ => None,
        };
        if let (Some(latest), Some((digest, backend))) = (latest, proposed)
            && latest.frontier_generation == batch.proposed_frontier_generation
            && &latest.frontier_sha256 == digest
            && &latest.backend_identity_sha256 == backend
        {
            return Ok(EvidencePublicationLatestDisposition::RecoverDurableAcknowledgement);
        }
        let predecessor_matches = match (
            latest,
            batch.expected_frontier_generation,
            batch.expected_frontier_sha256.as_ref(),
            batch.expected_backend_identity_sha256.as_ref(),
        ) {
            (None, None, None, None) => true,
            (Some(latest), Some(generation), Some(digest), Some(backend)) => {
                latest.frontier_generation == generation
                    && &latest.frontier_sha256 == digest
                    && &latest.backend_identity_sha256 == backend
            }
            _ => false,
        };
        Ok(if predecessor_matches {
            EvidencePublicationLatestDisposition::RetrySameBatch
        } else {
            EvidencePublicationLatestDisposition::Conflict
        })
    }

    /// Admit one durable backend acknowledgement, advance local monotonic
    /// acceptance and acknowledge every intent in the exact batch atomically.
    pub async fn acknowledge_publication(
        &self,
        lease: &EvidencePublicationOwnerLeaseV1,
        batch_id: &str,
        acknowledgement: &EvidenceFrontierDurableAckV1,
        now_unix_ms: u64,
    ) -> Result<EvidencePublicationAckDisposition, EvidenceError> {
        let now = to_i64(now_unix_ms, "publication acknowledgement timestamp")?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        require_publication_owner(&mut transaction, lease, now_unix_ms).await?;
        let batch = decode_batch(&load_batch(&mut transaction, batch_id).await?)?;
        if acknowledgement.store_id != batch.store_id
            || acknowledgement.frontier_generation != batch.proposed_frontier_generation
            || batch.proposed_frontier_sha256.as_ref() != Some(&acknowledgement.frontier_sha256)
            || batch.backend_identity_sha256.as_ref()
                != Some(&acknowledgement.backend_identity_sha256)
            || acknowledgement.audit_sequence == 0
        {
            return Err(EvidenceError::IdempotencyConflict {
                record_id: batch_id.to_string(),
            });
        }
        if batch.state == EvidencePublicationBatchStateV1::Acknowledged {
            if batch.durable_audit_sequence == Some(acknowledgement.audit_sequence) {
                transaction.commit().await.map_err(classify_sqlx_error)?;
                return Ok(EvidencePublicationAckDisposition::AlreadyAcknowledged);
            }
            return Err(EvidenceError::IdempotencyConflict {
                record_id: batch_id.to_string(),
            });
        }
        if !matches!(
            batch.state,
            EvidencePublicationBatchStateV1::Dispatching
                | EvidencePublicationBatchStateV1::Indeterminate
        ) {
            return Err(invalid(
                "publication acknowledgement requires a durably dispatched batch",
            ));
        }
        accept_in_transaction(
            &mut transaction,
            &EvidenceAcceptedFrontierV1 {
                store_id: batch.store_id.clone(),
                frontier_generation: batch.proposed_frontier_generation,
                frontier_sha256: acknowledgement.frontier_sha256.clone(),
                backend_identity_sha256: acknowledgement.backend_identity_sha256.clone(),
                accepted_at_unix_ms: now_unix_ms,
            },
            false,
        )
        .await?;
        sqlx::query(
            "UPDATE evidence_publication_batches
             SET state = 'acknowledged', durable_audit_sequence = ?, updated_at_ms = ?
             WHERE batch_id = ? AND state IN ('dispatching', 'indeterminate')",
        )
        .bind(to_i64(
            acknowledgement.audit_sequence,
            "publication audit sequence",
        )?)
        .bind(now)
        .bind(batch_id)
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        sqlx::query(
            "UPDATE evidence_publication_intents
             SET state = 'acknowledged', updated_at_ms = ?
             WHERE batch_id = ? AND state = 'batched'",
        )
        .bind(now)
        .bind(batch_id)
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(EvidencePublicationAckDisposition::Acknowledged)
    }

    pub async fn publication_batch(
        &self,
        batch_id: &str,
    ) -> Result<Option<EvidencePublicationBatchV1>, EvidenceError> {
        validate_stable_id(batch_id, "publication batch")?;
        let row = sqlx::query("SELECT * FROM evidence_publication_batches WHERE batch_id = ?")
            .bind(batch_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(classify_sqlx_error)?;
        row.as_ref().map(decode_batch).transpose()
    }

    pub async fn pending_publication_count(&self) -> Result<u64, EvidenceError> {
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM evidence_publication_intents
             WHERE state != 'acknowledged'",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        u64::try_from(count)
            .map_err(|_| EvidenceError::Corrupt("negative publication intent count".to_string()))
    }
}

fn publication_batch_id(
    store_id: &str,
    owner_generation: u64,
    first_operation: &str,
    last_operation: &str,
    snapshot_sha256: &Sha256Digest,
    proposed_generation: u64,
) -> String {
    let mut bytes = b"hepta.kernel.evidence.publication-batch.v1\0".to_vec();
    push_part(&mut bytes, store_id.as_bytes());
    bytes.extend_from_slice(&owner_generation.to_be_bytes());
    push_part(&mut bytes, first_operation.as_bytes());
    push_part(&mut bytes, last_operation.as_bytes());
    push_part(&mut bytes, snapshot_sha256.as_str().as_bytes());
    bytes.extend_from_slice(&proposed_generation.to_be_bytes());
    format!(
        "kernel.evidence.publication:{}",
        Sha256Digest::for_bytes(&bytes).as_str()
    )
}

async fn enrolled_store_id(
    transaction: &mut Transaction<'_, Sqlite>,
) -> Result<String, EvidenceError> {
    sqlx::query_scalar("SELECT store_id FROM evidence_recovery_identity WHERE singleton = 1")
        .fetch_optional(&mut **transaction)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or_else(|| invalid("evidence publication requires an enrolled recovery store"))
}

async fn require_publication_owner(
    transaction: &mut Transaction<'_, Sqlite>,
    lease: &EvidencePublicationOwnerLeaseV1,
    now_unix_ms: u64,
) -> Result<(), EvidenceError> {
    validate_stable_id(&lease.store_id, "publication store")?;
    validate_stable_id(&lease.owner_id, "publication owner")?;
    if lease.owner_generation == 0 || lease.lease_expires_at_unix_ms <= now_unix_ms {
        return Err(EvidenceError::Unavailable(
            "evidence publication owner lease is expired".to_string(),
        ));
    }
    let row = sqlx::query(
        "SELECT owner_id, owner_generation, lease_expires_at_ms
         FROM evidence_publication_owner WHERE store_id = ?",
    )
    .bind(&lease.store_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?
    .ok_or_else(|| EvidenceError::Unavailable("no evidence publication owner".to_string()))?;
    let owner_id: String = row.try_get("owner_id").map_err(classify_sqlx_error)?;
    let generation = positive_u64_from_i64(
        row.try_get("owner_generation")
            .map_err(classify_sqlx_error)?,
        "publication owner generation",
    )?;
    let expiry = positive_u64_from_i64(
        row.try_get("lease_expires_at_ms")
            .map_err(classify_sqlx_error)?,
        "publication owner lease expiry",
    )?;
    if owner_id != lease.owner_id
        || generation != lease.owner_generation
        || expiry != lease.lease_expires_at_unix_ms
        || expiry <= now_unix_ms
    {
        return Err(EvidenceError::Unavailable(
            "evidence publication owner was fenced by a newer generation".to_string(),
        ));
    }
    Ok(())
}

async fn latest_accepted_in_transaction(
    transaction: &mut Transaction<'_, Sqlite>,
    store_id: &str,
) -> Result<Option<EvidenceAcceptedFrontierV1>, EvidenceError> {
    let row = sqlx::query(
        "SELECT store_id, frontier_generation, frontier_sha256,
                backend_identity_sha256, accepted_at_ms
         FROM evidence_frontier_acceptance
         WHERE store_id = ? ORDER BY seq DESC LIMIT 1",
    )
    .bind(store_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    row.as_ref().map(decode_accepted_frontier).transpose()
}

fn decode_accepted_frontier(row: &SqliteRow) -> Result<EvidenceAcceptedFrontierV1, EvidenceError> {
    Ok(EvidenceAcceptedFrontierV1 {
        store_id: row.try_get("store_id").map_err(classify_sqlx_error)?,
        frontier_generation: read_u64_blob(row, "frontier_generation")?,
        frontier_sha256: parse_digest(row, "frontier_sha256")?,
        backend_identity_sha256: parse_digest(row, "backend_identity_sha256")?,
        accepted_at_unix_ms: read_u64_blob(row, "accepted_at_ms")?,
    })
}

async fn load_batch(
    transaction: &mut Transaction<'_, Sqlite>,
    batch_id: &str,
) -> Result<SqliteRow, EvidenceError> {
    validate_stable_id(batch_id, "publication batch")?;
    sqlx::query("SELECT * FROM evidence_publication_batches WHERE batch_id = ?")
        .bind(batch_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or_else(|| invalid("publication batch does not exist"))
}

fn decode_batch(row: &SqliteRow) -> Result<EvidencePublicationBatchV1, EvidenceError> {
    let snapshot_json: String = row.try_get("snapshot_json").map_err(classify_sqlx_error)?;
    let snapshot: EvidenceRecoverySnapshotV1 =
        serde_json::from_str(&snapshot_json).map_err(|error| {
            EvidenceError::Corrupt(format!("publication snapshot cannot be decoded: {error}"))
        })?;
    let canonical = canonical_json(&snapshot)?;
    if canonical.as_slice() != snapshot_json.as_bytes() {
        return Err(EvidenceError::Corrupt(
            "publication snapshot is not canonical JSON".to_string(),
        ));
    }
    let snapshot_sha256 = parse_digest(row, "snapshot_sha256")?;
    if snapshot_sha256 != Sha256Digest::for_bytes(&canonical) {
        return Err(EvidenceError::Corrupt(
            "publication snapshot digest does not match the stored snapshot".to_string(),
        ));
    }
    let count = positive_u64_from_i64(
        row.try_get("intent_count").map_err(classify_sqlx_error)?,
        "publication intent count",
    )?;
    Ok(EvidencePublicationBatchV1 {
        batch_id: row.try_get("batch_id").map_err(classify_sqlx_error)?,
        store_id: row.try_get("store_id").map_err(classify_sqlx_error)?,
        prepared_owner_id: row
            .try_get("prepared_owner_id")
            .map_err(classify_sqlx_error)?,
        prepared_owner_generation: positive_u64_from_i64(
            row.try_get("prepared_owner_generation")
                .map_err(classify_sqlx_error)?,
            "publication prepared owner generation",
        )?,
        state: EvidencePublicationBatchStateV1::parse(
            &row.try_get::<String, _>("state")
                .map_err(classify_sqlx_error)?,
        )?,
        first_intent_seq: positive_u64_from_i64(
            row.try_get("first_intent_seq")
                .map_err(classify_sqlx_error)?,
            "publication first intent sequence",
        )?,
        last_intent_seq: positive_u64_from_i64(
            row.try_get("last_intent_seq")
                .map_err(classify_sqlx_error)?,
            "publication last intent sequence",
        )?,
        intent_count: usize::try_from(count)
            .map_err(|_| EvidenceError::Corrupt("publication intent count overflow".to_string()))?,
        snapshot,
        snapshot_sha256,
        expected_frontier_generation: optional_positive_u64_i64(
            row.try_get("expected_frontier_generation")
                .map_err(classify_sqlx_error)?,
            "expected frontier generation",
        )?,
        expected_frontier_sha256: optional_digest(row, "expected_frontier_sha256")?,
        expected_backend_identity_sha256: optional_digest(row, "expected_backend_identity_sha256")?,
        proposed_frontier_generation: positive_u64_from_i64(
            row.try_get("proposed_frontier_generation")
                .map_err(classify_sqlx_error)?,
            "proposed frontier generation",
        )?,
        proposed_frontier_sha256: optional_digest(row, "proposed_frontier_sha256")?,
        backend_identity_sha256: optional_digest(row, "backend_identity_sha256")?,
        durable_audit_sequence: optional_positive_u64_i64(
            row.try_get("durable_audit_sequence")
                .map_err(classify_sqlx_error)?,
            "publication durable audit sequence",
        )?,
        created_at_unix_ms: positive_u64_from_i64(
            row.try_get("created_at_ms").map_err(classify_sqlx_error)?,
            "publication created timestamp",
        )?,
        updated_at_unix_ms: positive_u64_from_i64(
            row.try_get("updated_at_ms").map_err(classify_sqlx_error)?,
            "publication updated timestamp",
        )?,
    })
}

fn parse_digest(row: &SqliteRow, column: &str) -> Result<Sha256Digest, EvidenceError> {
    Sha256Digest::parse(
        row.try_get::<String, _>(column)
            .map_err(classify_sqlx_error)?,
    )
    .map_err(EvidenceError::Corrupt)
}

fn optional_digest(row: &SqliteRow, column: &str) -> Result<Option<Sha256Digest>, EvidenceError> {
    row.try_get::<Option<String>, _>(column)
        .map_err(classify_sqlx_error)?
        .map(Sha256Digest::parse)
        .transpose()
        .map_err(EvidenceError::Corrupt)
}

fn read_u64_blob(row: &SqliteRow, column: &str) -> Result<u64, EvidenceError> {
    let bytes: Vec<u8> = row.try_get(column).map_err(classify_sqlx_error)?;
    let bytes: [u8; 8] = bytes.try_into().map_err(|_| {
        EvidenceError::Corrupt(format!("{column} is not an eight-byte unsigned integer"))
    })?;
    Ok(u64::from_be_bytes(bytes))
}

fn optional_positive_u64_i64(
    value: Option<i64>,
    label: &str,
) -> Result<Option<u64>, EvidenceError> {
    value
        .map(|value| positive_u64_from_i64(value, label))
        .transpose()
}

fn positive_u64_from_i64(value: i64, label: &str) -> Result<u64, EvidenceError> {
    let value =
        u64::try_from(value).map_err(|_| EvidenceError::Corrupt(format!("{label} is negative")))?;
    if value == 0 {
        return Err(EvidenceError::Corrupt(format!("{label} is zero")));
    }
    Ok(value)
}

fn to_i64(value: u64, label: &str) -> Result<i64, EvidenceError> {
    i64::try_from(value).map_err(|_| invalid(&format!("{label} exceeds the SQLite integer domain")))
}

fn validate_stable_id(value: &str, label: &str) -> Result<(), EvidenceError> {
    StableId::new(value.to_string())
        .map(|_| ())
        .map_err(|error| invalid(&format!("invalid {label}: {error}")))
}

fn push_part(target: &mut Vec<u8>, part: &[u8]) {
    target.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    target.extend_from_slice(part);
}

fn invalid(message: &str) -> EvidenceError {
    EvidenceError::InvalidRecord(message.to_string())
}

#[cfg(test)]
#[path = "publication_tests.rs"]
mod tests;
