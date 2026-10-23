//! Durable, crash-atomic ownership for qualified compaction artifacts.
//!
//! The pure kernel remains deterministic and authority-free. This module owns
//! publication metadata, immutable artifact images, the active checkpoint CAS,
//! a local outbox, trust-enrollment history and restart verification. It never
//! rewrites source memory facts.

use std::str::FromStr;
use std::time::{SystemTime, UNIX_EPOCH};

use codex_hepta_types::{Digest32, StableId};
use sha2::{Digest, Sha256};
use sqlx::sqlite::{SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions, SqliteSynchronous};
use sqlx::{Row, SqliteConnection, SqlitePool};

use crate::{
    CompactionTrustRoleV1, QualifiedCompactionCandidateV2, TrustEnrollmentV1,
    TrustedCompactionProofV1,
};

pub const DURABLE_COMPACTION_SCHEMA_VERSION: u32 = 1;
pub const MEMORY_CHECKPOINT_COORDINATOR_CALLER: &str = "memory.checkpoint-coordinator.v1";
pub const MAX_DURABLE_COMPACTION_ARTIFACT_BYTES: usize = 64 * 1024 * 1024;
pub const MAX_DURABLE_COMPACTION_OUTBOX_PAYLOAD_BYTES: usize = 1024 * 1024;
const PUBLICATION_DOMAIN: &[u8] = b"hepta.compaction.durable-publication.v1\0";
const SOURCE_RETENTION_DOMAIN: &[u8] = b"hepta.compaction.source-retention-fence.v1\0";
const OUTBOX_DOMAIN: &[u8] = b"hepta.compaction.outbox.v1\0";
const REVOCATION_DOMAIN: &[u8] = b"hepta.compaction.checkpoint-revocation.v1\0";

#[derive(Debug, thiserror::Error)]
pub enum DurableCompactionError {
    #[error("invalid durable compaction input: {0}")]
    Invalid(String),
    #[error("durable compaction CAS conflict: {0}")]
    Conflict(String),
    #[error("durable compaction store is corrupt: {0}")]
    Corrupt(String),
    #[error("durable compaction capacity exceeded: {0}")]
    Capacity(String),
    #[error(transparent)]
    Sql(#[from] sqlx::Error),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionArtifactImagesV1 {
    pub candidate_image: Vec<u8>,
    pub evaluation_image: Vec<u8>,
    pub proof_image: Vec<u8>,
    pub checkpoint_image: Vec<u8>,
}

impl CompactionArtifactImagesV1 {
    pub fn validate(&self) -> Result<(), DurableCompactionError> {
        for (name, bytes) in [
            ("candidate", self.candidate_image.as_slice()),
            ("evaluation", self.evaluation_image.as_slice()),
            ("proof", self.proof_image.as_slice()),
            ("checkpoint", self.checkpoint_image.as_slice()),
        ] {
            if bytes.is_empty() || bytes.len() > MAX_DURABLE_COMPACTION_ARTIFACT_BYTES {
                return Err(invalid(format!(
                    "{name} image must contain 1..={MAX_DURABLE_COMPACTION_ARTIFACT_BYTES} bytes"
                )));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCompactionTrustSetV1 {
    pub selector: TrustEnrollmentV1,
    pub generator: TrustEnrollmentV1,
    pub tokenizer: TrustEnrollmentV1,
    pub evaluator: TrustEnrollmentV1,
}

impl DurableCompactionTrustSetV1 {
    pub fn validate_historical_at(&self, accepted_at: u64) -> Result<(), DurableCompactionError> {
        for (expected, enrollment) in [
            (CompactionTrustRoleV1::RetentionSelector, &self.selector),
            (CompactionTrustRoleV1::SemanticGenerator, &self.generator),
            (CompactionTrustRoleV1::Tokenizer, &self.tokenizer),
            (CompactionTrustRoleV1::Evaluator, &self.evaluator),
        ] {
            if enrollment.role != expected {
                return Err(invalid("trust set contains a role mismatch"));
            }
            enrollment
                .validate_historical_at(accepted_at)
                .map_err(|error| invalid(format!("trust enrollment rejected: {error}")))?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCompactionBundleV1 {
    owner_id: String,
    idempotency_key: String,
    scope_id: String,
    purpose_id: String,
    generation: u64,
    predecessor_checkpoint_digest: Option<Digest32>,
    source_snapshot_digest: Digest32,
    source_memory_snapshot_digest: Digest32,
    source_retention_fence_digest: Digest32,
    retain_source_until_unix_seconds: u64,
    policy_digest: Digest32,
    candidate_digest: Digest32,
    payload_digest: Digest32,
    payload: Vec<u8>,
    payload_tokens: u64,
    evaluation_digest: Digest32,
    proof_digest: Digest32,
    checkpoint_digest: Digest32,
    selection_receipt_digest: Digest32,
    generation_receipt_digest: Digest32,
    trusted_proof: TrustedCompactionProofV1,
    trust: DurableCompactionTrustSetV1,
    images: CompactionArtifactImagesV1,
    publication_digest: Digest32,
    accepted_at_unix_seconds: u64,
}

impl DurableCompactionBundleV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn from_verified(
        owner_id: impl Into<String>,
        idempotency_key: impl Into<String>,
        candidate: &QualifiedCompactionCandidateV2,
        trusted_proof: TrustedCompactionProofV1,
        selection_receipt_digest: Digest32,
        generation_receipt_digest: Digest32,
        trust: DurableCompactionTrustSetV1,
        images: CompactionArtifactImagesV1,
        retain_source_until_unix_seconds: u64,
    ) -> Result<Self, DurableCompactionError> {
        candidate
            .validate()
            .map_err(|error| invalid(format!("candidate rejected: {error}")))?;
        trusted_proof
            .proof
            .validate()
            .map_err(|error| invalid(format!("proof rejected: {error}")))?;
        trusted_proof
            .witness
            .verify_proof(&trusted_proof.proof)
            .map_err(|error| invalid(format!("proof witness rejected: {error}")))?;
        images.validate()?;

        let owner_id = owner_id.into();
        let idempotency_key = idempotency_key.into();
        validate_text_identity("owner id", &owner_id)?;
        validate_text_identity("idempotency key", &idempotency_key)?;
        ensure_digest(selection_receipt_digest, "selection receipt")?;
        ensure_digest(generation_receipt_digest, "generation receipt")?;
        if retain_source_until_unix_seconds < trusted_proof.accepted_at_unix_seconds {
            return Err(invalid(
                "source retention deadline precedes publication acceptance",
            ));
        }
        trust.validate_historical_at(trusted_proof.accepted_at_unix_seconds)?;
        if trusted_proof.evaluator_key_id != trust.evaluator.key_id
            || trusted_proof.evaluator_trust_epoch != trust.evaluator.trust_epoch
            || trusted_proof.proof.evaluator_id != trust.evaluator.key_id
            || trusted_proof.proof.tokenizer_key_digest != trust.tokenizer.key_digest()
        {
            return Err(invalid("proof trust binding does not match the trust set"));
        }

        let checkpoint = candidate.checkpoint();
        if trusted_proof.proof.candidate_digest != candidate.candidate_digest()
            || trusted_proof.proof.checkpoint_digest != checkpoint.checkpoint_digest
        {
            return Err(invalid("proof does not bind the candidate checkpoint"));
        }
        let payload = candidate.semantic_payload().payload.clone();
        if payload.is_empty()
            || payload.len() > MAX_DURABLE_COMPACTION_ARTIFACT_BYTES
            || Digest32::of_bytes(&payload) != checkpoint.payload_digest
        {
            return Err(invalid("semantic payload bytes fail digest or size validation"));
        }

        let scope_id = checkpoint.source_snapshot.vector.scope_id.to_string();
        let purpose_id = checkpoint.source_snapshot.vector.purpose_id.to_string();
        let generation = checkpoint.generation.get();
        let source_snapshot_digest = checkpoint.source_snapshot.vector_digest;
        let source_memory_snapshot_digest = checkpoint.source_memory_snapshot_digest;
        let policy_digest = candidate.policy().digest();
        let candidate_digest = candidate.candidate_digest();
        let payload_digest = checkpoint.payload_digest;
        let evaluation_digest = trusted_proof.evaluation_receipt_digest;
        let proof_digest = trusted_proof.proof.proof_digest;
        let checkpoint_digest = checkpoint.checkpoint_digest;
        let predecessor_checkpoint_digest = checkpoint.predecessor_digest;
        let accepted_at_unix_seconds = trusted_proof.accepted_at_unix_seconds;
        let source_retention_fence_digest = source_retention_fence_digest(
            &owner_id,
            &scope_id,
            &purpose_id,
            source_snapshot_digest,
            source_memory_snapshot_digest,
            generation,
            retain_source_until_unix_seconds,
        );
        let publication_digest = publication_digest(
            &owner_id,
            &idempotency_key,
            &scope_id,
            &purpose_id,
            generation,
            predecessor_checkpoint_digest,
            source_snapshot_digest,
            source_memory_snapshot_digest,
            source_retention_fence_digest,
            policy_digest,
            candidate_digest,
            payload_digest,
            evaluation_digest,
            proof_digest,
            checkpoint_digest,
            selection_receipt_digest,
            generation_receipt_digest,
            &trust,
            &images,
            accepted_at_unix_seconds,
        );

        Ok(Self {
            owner_id,
            idempotency_key,
            scope_id,
            purpose_id,
            generation,
            predecessor_checkpoint_digest,
            source_snapshot_digest,
            source_memory_snapshot_digest,
            source_retention_fence_digest,
            retain_source_until_unix_seconds,
            policy_digest,
            candidate_digest,
            payload_digest,
            payload_tokens: candidate.semantic_payload().token_count,
            payload,
            evaluation_digest,
            proof_digest,
            checkpoint_digest,
            selection_receipt_digest,
            generation_receipt_digest,
            trusted_proof,
            trust,
            images,
            publication_digest,
            accepted_at_unix_seconds,
        })
    }

    #[must_use]
    pub fn publication_digest(&self) -> Digest32 {
        self.publication_digest
    }

    #[must_use]
    pub fn checkpoint_digest(&self) -> Digest32 {
        self.checkpoint_digest
    }

    #[must_use]
    pub fn generation(&self) -> u64 {
        self.generation
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableCompactionDisposition {
    Inserted,
    Unchanged,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCompactionPublicationReceiptV1 {
    pub schema_version: u32,
    pub caller: String,
    pub owner_id: String,
    pub idempotency_key: String,
    pub scope_id: String,
    pub purpose_id: String,
    pub generation: u64,
    pub checkpoint_digest: Digest32,
    pub publication_digest: Digest32,
    pub outbox_event_id: Digest32,
    pub disposition: DurableCompactionDisposition,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCompactionSelectionV1 {
    pub owner_id: String,
    pub scope_id: String,
    pub purpose_id: String,
    pub generation: u64,
    pub checkpoint_digest: Digest32,
    pub predecessor_checkpoint_digest: Option<Digest32>,
    pub source_snapshot_digest: Digest32,
    pub source_memory_snapshot_digest: Digest32,
    pub candidate_digest: Digest32,
    pub payload_digest: Digest32,
    pub proof_digest: Digest32,
    pub publication_digest: Digest32,
    pub payload: Vec<u8>,
    pub proof_image: Vec<u8>,
    pub checkpoint_image: Vec<u8>,
    pub fell_back_from_revoked_head: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCompactionOutboxEventV1 {
    pub event_id: Digest32,
    pub publication_digest: Digest32,
    pub event_kind: String,
    pub payload: Vec<u8>,
    pub attempt_count: u32,
    pub claim_token: String,
}

#[derive(Clone)]
pub struct DurableCompactionStoreV1 {
    owner_id: String,
    pool: SqlitePool,
}

impl DurableCompactionStoreV1 {
    pub async fn open(
        database_url: &str,
        owner_id: impl Into<String>,
    ) -> Result<Self, DurableCompactionError> {
        let owner_id = owner_id.into();
        validate_text_identity("owner id", &owner_id)?;
        let options = SqliteConnectOptions::from_str(database_url)?
            .create_if_missing(true)
            .foreign_keys(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full);
        let pool = SqlitePoolOptions::new()
            .max_connections(4)
            .connect_with(options)
            .await?;
        sqlx::raw_sql(include_str!("compaction_schema.sql"))
            .execute(&pool)
            .await?;
        let store = Self { owner_id, pool };
        store.verify_integrity().await?;
        Ok(store)
    }

    #[must_use]
    pub fn owner_id(&self) -> &str {
        &self.owner_id
    }

    pub async fn publish(
        &self,
        bundle: &DurableCompactionBundleV1,
    ) -> Result<DurableCompactionPublicationReceiptV1, DurableCompactionError> {
        if bundle.owner_id != self.owner_id {
            return Err(invalid("publication owner does not match the opened store"));
        }
        let mut connection = self.pool.acquire().await?;
        sqlx::query("BEGIN IMMEDIATE")
            .execute(&mut *connection)
            .await?;
        let result = self.publish_tx(&mut connection, bundle).await;
        match result {
            Ok(receipt) => {
                sqlx::query("COMMIT").execute(&mut *connection).await?;
                Ok(receipt)
            }
            Err(error) => {
                let _ = sqlx::query("ROLLBACK").execute(&mut *connection).await;
                Err(error)
            }
        }
    }

    async fn publish_tx(
        &self,
        connection: &mut SqliteConnection,
        bundle: &DurableCompactionBundleV1,
    ) -> Result<DurableCompactionPublicationReceiptV1, DurableCompactionError> {
        if let Some(row) = sqlx::query(
            "SELECT candidate_digest FROM compaction_candidates
             WHERE owner_id = ? AND idempotency_key = ?",
        )
        .bind(&self.owner_id)
        .bind(&bundle.idempotency_key)
        .fetch_optional(&mut *connection)
        .await?
        {
            let existing: String = row.try_get("candidate_digest")?;
            if existing != bundle.candidate_digest.to_string() {
                return Err(conflict("idempotency key was reused with different semantics"));
            }
            let row = sqlx::query(
                "SELECT publication_digest FROM compaction_checkpoints
                 WHERE owner_id = ? AND checkpoint_digest = ?",
            )
            .bind(&self.owner_id)
            .bind(bundle.checkpoint_digest.to_string())
            .fetch_one(&mut *connection)
            .await?;
            let publication: String = row.try_get("publication_digest")?;
            if publication != bundle.publication_digest.to_string() {
                return Err(corrupt("idempotent checkpoint publication digest drift"));
            }
            return Ok(bundle.receipt(DurableCompactionDisposition::Unchanged));
        }

        for enrollment in [
            &bundle.trust.selector,
            &bundle.trust.generator,
            &bundle.trust.tokenizer,
            &bundle.trust.evaluator,
        ] {
            persist_trust_enrollment(connection, &self.owner_id, enrollment, bundle.accepted_at_unix_seconds)
                .await?;
        }

        insert_payload(connection, bundle).await?;
        insert_candidate(connection, bundle).await?;
        insert_evaluation(connection, bundle).await?;
        insert_proof(connection, bundle).await?;
        insert_checkpoint(connection, bundle).await?;
        advance_active_checkpoint(connection, bundle).await?;
        insert_outbox(connection, bundle, "checkpoint-published", outbox_payload(bundle)).await?;
        Ok(bundle.receipt(DurableCompactionDisposition::Inserted))
    }

    pub async fn select_current(
        &self,
        scope_id: &str,
        purpose_id: &str,
    ) -> Result<Option<DurableCompactionSelectionV1>, DurableCompactionError> {
        validate_text_identity("scope id", scope_id)?;
        validate_text_identity("purpose id", purpose_id)?;
        let active = sqlx::query(
            "SELECT generation, checkpoint_digest FROM active_compaction_checkpoint
             WHERE owner_id = ? AND scope_id = ? AND purpose_id = ?",
        )
        .bind(&self.owner_id)
        .bind(scope_id)
        .bind(purpose_id)
        .fetch_optional(&self.pool)
        .await?;
        let Some(active) = active else {
            return Ok(None);
        };
        let active_generation: i64 = active.try_get("generation")?;
        let active_digest: String = active.try_get("checkpoint_digest")?;
        let row = sqlx::query(
            "SELECT c.generation, c.checkpoint_digest, c.predecessor_checkpoint_digest,
                    c.source_snapshot_digest, c.source_memory_snapshot_digest,
                    c.candidate_digest, c.payload_digest, c.proof_digest,
                    c.publication_digest, c.checkpoint_image, c.checkpoint_image_digest,
                    p.payload_bytes, p.payload_bytes_digest,
                    r.proof_image, r.proof_image_digest
             FROM compaction_checkpoints c
             JOIN compaction_payloads p
               ON p.owner_id = c.owner_id AND p.payload_digest = c.payload_digest
             JOIN compaction_proofs r
               ON r.owner_id = c.owner_id AND r.proof_digest = c.proof_digest
             LEFT JOIN compaction_checkpoint_revocations v
               ON v.owner_id = c.owner_id AND v.checkpoint_digest = c.checkpoint_digest
             WHERE c.owner_id = ? AND c.scope_id = ? AND c.purpose_id = ?
               AND c.generation <= ? AND v.checkpoint_digest IS NULL
             ORDER BY c.generation DESC LIMIT 1",
        )
        .bind(&self.owner_id)
        .bind(scope_id)
        .bind(purpose_id)
        .bind(active_generation)
        .fetch_optional(&self.pool)
        .await?;
        let Some(row) = row else {
            return Ok(None);
        };
        decode_selection(row, &self.owner_id, scope_id, purpose_id, &active_digest)
    }

    pub async fn revoke_checkpoint(
        &self,
        checkpoint_digest: Digest32,
        reason_digest: Digest32,
        revoked_at_unix_seconds: u64,
    ) -> Result<Digest32, DurableCompactionError> {
        ensure_digest(checkpoint_digest, "checkpoint")?;
        ensure_digest(reason_digest, "revocation reason")?;
        let revocation_digest = digest_parts(
            REVOCATION_DOMAIN,
            &[
                self.owner_id.as_bytes(),
                checkpoint_digest.to_string().as_bytes(),
                reason_digest.to_string().as_bytes(),
                &revoked_at_unix_seconds.to_be_bytes(),
            ],
        );
        let mut connection = self.pool.acquire().await?;
        sqlx::query("BEGIN IMMEDIATE").execute(&mut *connection).await?;
        let result = async {
            let inserted = sqlx::query(
                "INSERT OR IGNORE INTO compaction_checkpoint_revocations
                 (owner_id, checkpoint_digest, revocation_digest, reason_digest, revoked_at_unix_seconds)
                 VALUES (?, ?, ?, ?, ?)",
            )
            .bind(&self.owner_id)
            .bind(checkpoint_digest.to_string())
            .bind(revocation_digest.to_string())
            .bind(reason_digest.to_string())
            .bind(to_i64(revoked_at_unix_seconds, "revocation time")?)
            .execute(&mut *connection)
            .await?;
            if inserted.rows_affected() == 0 {
                let existing: String = sqlx::query_scalar(
                    "SELECT revocation_digest FROM compaction_checkpoint_revocations
                     WHERE owner_id = ? AND checkpoint_digest = ?",
                )
                .bind(&self.owner_id)
                .bind(checkpoint_digest.to_string())
                .fetch_one(&mut *connection)
                .await?;
                if existing != revocation_digest.to_string() {
                    return Err(conflict("checkpoint was revoked with different semantics"));
                }
            }
            let publication: String = sqlx::query_scalar(
                "SELECT publication_digest FROM compaction_checkpoints
                 WHERE owner_id = ? AND checkpoint_digest = ?",
            )
            .bind(&self.owner_id)
            .bind(checkpoint_digest.to_string())
            .fetch_one(&mut *connection)
            .await?;
            let payload = format!("{checkpoint_digest}:{reason_digest}:{revoked_at_unix_seconds}")
                .into_bytes();
            insert_outbox_raw(
                &mut connection,
                &self.owner_id,
                &publication,
                "checkpoint-revoked",
                payload,
                revoked_at_unix_seconds,
            )
            .await?;
            Ok::<_, DurableCompactionError>(revocation_digest)
        }
        .await;
        match result {
            Ok(value) => {
                sqlx::query("COMMIT").execute(&mut *connection).await?;
                Ok(value)
            }
            Err(error) => {
                let _ = sqlx::query("ROLLBACK").execute(&mut *connection).await;
                Err(error)
            }
        }
    }

    pub async fn claim_next_outbox(
        &self,
        now_unix_seconds: u64,
        claim_token: &str,
    ) -> Result<Option<DurableCompactionOutboxEventV1>, DurableCompactionError> {
        validate_text_identity("outbox claim token", claim_token)?;
        let mut connection = self.pool.acquire().await?;
        sqlx::query("BEGIN IMMEDIATE").execute(&mut *connection).await?;
        let result = async {
            let row = sqlx::query(
                "SELECT event_id, publication_digest, event_kind, payload, attempt_count
                 FROM compaction_outbox
                 WHERE owner_id = ? AND state = 'pending' AND next_attempt_at_unix_seconds <= ?
                 ORDER BY created_at_unix_seconds, event_id LIMIT 1",
            )
            .bind(&self.owner_id)
            .bind(to_i64(now_unix_seconds, "outbox time")?)
            .fetch_optional(&mut *connection)
            .await?;
            let Some(row) = row else {
                return Ok(None);
            };
            let event_id_text: String = row.try_get("event_id")?;
            let updated = sqlx::query(
                "UPDATE compaction_outbox SET state = 'claimed', claim_token = ?,
                        attempt_count = attempt_count + 1
                 WHERE owner_id = ? AND event_id = ? AND state = 'pending'",
            )
            .bind(claim_token)
            .bind(&self.owner_id)
            .bind(&event_id_text)
            .execute(&mut *connection)
            .await?;
            if updated.rows_affected() != 1 {
                return Err(conflict("outbox claim lost its CAS"));
            }
            let attempt_count: i64 = row.try_get("attempt_count")?;
            Ok(Some(DurableCompactionOutboxEventV1 {
                event_id: parse_digest(&event_id_text, "outbox event")?,
                publication_digest: parse_digest(
                    &row.try_get::<String, _>("publication_digest")?,
                    "outbox publication",
                )?,
                event_kind: row.try_get("event_kind")?,
                payload: row.try_get("payload")?,
                attempt_count: u32::try_from(attempt_count + 1)
                    .map_err(|_| corrupt("outbox attempt count overflow"))?,
                claim_token: claim_token.to_string(),
            }))
        }
        .await;
        match result {
            Ok(value) => {
                sqlx::query("COMMIT").execute(&mut *connection).await?;
                Ok(value)
            }
            Err(error) => {
                let _ = sqlx::query("ROLLBACK").execute(&mut *connection).await;
                Err(error)
            }
        }
    }

    pub async fn complete_outbox(
        &self,
        event: &DurableCompactionOutboxEventV1,
        delivered_at_unix_seconds: u64,
    ) -> Result<(), DurableCompactionError> {
        let updated = sqlx::query(
            "UPDATE compaction_outbox SET state = 'delivered', delivered_at_unix_seconds = ?,
                    claim_token = NULL
             WHERE owner_id = ? AND event_id = ? AND state = 'claimed' AND claim_token = ?",
        )
        .bind(to_i64(delivered_at_unix_seconds, "delivery time")?)
        .bind(&self.owner_id)
        .bind(event.event_id.to_string())
        .bind(&event.claim_token)
        .execute(&self.pool)
        .await?;
        if updated.rows_affected() != 1 {
            return Err(conflict("outbox completion lost its claim fence"));
        }
        Ok(())
    }

    pub async fn reconcile_claims(
        &self,
        retry_at_unix_seconds: u64,
    ) -> Result<u64, DurableCompactionError> {
        let result = sqlx::query(
            "UPDATE compaction_outbox SET state = 'pending', claim_token = NULL,
                    next_attempt_at_unix_seconds = ?
             WHERE owner_id = ? AND state = 'claimed'",
        )
        .bind(to_i64(retry_at_unix_seconds, "retry time")?)
        .bind(&self.owner_id)
        .execute(&self.pool)
        .await?;
        Ok(result.rows_affected())
    }

    pub async fn revoke_trust(
        &self,
        role: CompactionTrustRoleV1,
        key_id: &StableId,
        trust_epoch: u64,
        revoked_at_unix_seconds: u64,
    ) -> Result<(), DurableCompactionError> {
        let updated = sqlx::query(
            "UPDATE compaction_trust_registry SET revoked_at_unix_seconds = ?
             WHERE owner_id = ? AND role = ? AND key_id = ? AND trust_epoch = ?
               AND revoked_at_unix_seconds IS NULL",
        )
        .bind(to_i64(revoked_at_unix_seconds, "trust revocation time")?)
        .bind(&self.owner_id)
        .bind(trust_role_name(role))
        .bind(key_id.as_str())
        .bind(to_i64(trust_epoch, "trust epoch")?)
        .execute(&self.pool)
        .await?;
        if updated.rows_affected() != 1 {
            return Err(conflict("trust enrollment was absent or already revoked"));
        }
        Ok(())
    }

    pub async fn verify_integrity(&self) -> Result<(), DurableCompactionError> {
        let integrity: String = sqlx::query_scalar("PRAGMA integrity_check")
            .fetch_one(&self.pool)
            .await?;
        if integrity != "ok" {
            return Err(corrupt(format!("SQLite integrity_check returned {integrity}")));
        }
        let foreign: Vec<sqlx::sqlite::SqliteRow> = sqlx::query("PRAGMA foreign_key_check")
            .fetch_all(&self.pool)
            .await?;
        if !foreign.is_empty() {
            return Err(corrupt("SQLite foreign_key_check reported violations"));
        }
        for object in [
            "compaction_candidates",
            "compaction_payloads",
            "compaction_evaluations",
            "compaction_proofs",
            "compaction_checkpoints",
            "active_compaction_checkpoint",
            "compaction_outbox",
            "compaction_trust_registry",
        ] {
            let found: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM sqlite_schema WHERE type = 'table' AND name = ?",
            )
            .bind(object)
            .fetch_one(&self.pool)
            .await?;
            if found != 1 {
                return Err(corrupt(format!("required schema object {object} is missing")));
            }
        }
        verify_payload_rows(&self.pool, &self.owner_id).await?;
        verify_active_rows(&self.pool, &self.owner_id).await?;
        Ok(())
    }
}

#[derive(Clone)]
pub struct MemoryCheckpointCoordinatorV1 {
    store: DurableCompactionStoreV1,
}

impl MemoryCheckpointCoordinatorV1 {
    #[must_use]
    pub fn new(store: DurableCompactionStoreV1) -> Self {
        Self { store }
    }

    pub async fn publish_verified_checkpoint(
        &self,
        bundle: &DurableCompactionBundleV1,
    ) -> Result<DurableCompactionPublicationReceiptV1, DurableCompactionError> {
        self.store.publish(bundle).await
    }

    pub async fn recover_current_checkpoint(
        &self,
        scope_id: &str,
        purpose_id: &str,
    ) -> Result<Option<DurableCompactionSelectionV1>, DurableCompactionError> {
        self.store.verify_integrity().await?;
        self.store.reconcile_claims(now_unix_seconds()?).await?;
        self.store.select_current(scope_id, purpose_id).await
    }
}

impl DurableCompactionBundleV1 {
    fn receipt(
        &self,
        disposition: DurableCompactionDisposition,
    ) -> DurableCompactionPublicationReceiptV1 {
        DurableCompactionPublicationReceiptV1 {
            schema_version: DURABLE_COMPACTION_SCHEMA_VERSION,
            caller: MEMORY_CHECKPOINT_COORDINATOR_CALLER.to_string(),
            owner_id: self.owner_id.clone(),
            idempotency_key: self.idempotency_key.clone(),
            scope_id: self.scope_id.clone(),
            purpose_id: self.purpose_id.clone(),
            generation: self.generation,
            checkpoint_digest: self.checkpoint_digest,
            publication_digest: self.publication_digest,
            outbox_event_id: outbox_event_id(self.publication_digest, "checkpoint-published"),
            disposition,
        }
    }
}

async fn persist_trust_enrollment(
    connection: &mut SqliteConnection,
    owner_id: &str,
    enrollment: &TrustEnrollmentV1,
    accepted_at: u64,
) -> Result<(), DurableCompactionError> {
    enrollment
        .validate_historical_at(accepted_at)
        .map_err(|error| invalid(format!("trust enrollment rejected: {error}")))?;
    let enrollment_digest = enrollment.identity_digest();
    let result = sqlx::query(
        "INSERT OR IGNORE INTO compaction_trust_registry
         (owner_id, role, key_id, trust_epoch, valid_from_unix_seconds,
          valid_until_unix_seconds, predecessor_key_digest, implementation_digest,
          attestation_digest, key_digest, verifying_key, enrollment_digest,
          enrolled_at_unix_seconds, revoked_at_unix_seconds)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(owner_id)
    .bind(trust_role_name(enrollment.role))
    .bind(enrollment.key_id.as_str())
    .bind(to_i64(enrollment.trust_epoch, "trust epoch")?)
    .bind(to_i64(enrollment.valid_from_unix_seconds, "trust valid from")?)
    .bind(to_i64(enrollment.valid_until_unix_seconds, "trust valid until")?)
    .bind(enrollment.predecessor_key_digest.map(|value| value.to_string()))
    .bind(enrollment.implementation_digest.to_string())
    .bind(enrollment.attestation_digest.to_string())
    .bind(enrollment.key_digest().to_string())
    .bind(enrollment.verifying_key.to_vec())
    .bind(enrollment_digest.to_string())
    .bind(to_i64(accepted_at, "trust enrollment time")?)
    .bind(enrollment.revoked_at_unix_seconds.map(|value| to_i64(value, "trust revoked at")).transpose()?)
    .execute(&mut *connection)
    .await?;
    if result.rows_affected() == 0 {
        let existing: String = sqlx::query_scalar(
            "SELECT enrollment_digest FROM compaction_trust_registry
             WHERE owner_id = ? AND role = ? AND key_id = ? AND trust_epoch = ?",
        )
        .bind(owner_id)
        .bind(trust_role_name(enrollment.role))
        .bind(enrollment.key_id.as_str())
        .bind(to_i64(enrollment.trust_epoch, "trust epoch")?)
        .fetch_one(&mut *connection)
        .await?;
        if existing != enrollment_digest.to_string() {
            return Err(conflict("trust enrollment identity was reused with drift"));
        }
    }
    Ok(())
}

async fn insert_payload(
    connection: &mut SqliteConnection,
    bundle: &DurableCompactionBundleV1,
) -> Result<(), DurableCompactionError> {
    let bytes_digest = Digest32::of_bytes(&bundle.payload);
    let result = sqlx::query(
        "INSERT OR IGNORE INTO compaction_payloads
         (owner_id, payload_digest, payload_bytes, payload_bytes_digest,
          encoded_bytes, token_count, generator_key_id, generator_trust_epoch,
          tokenizer_key_id, tokenizer_trust_epoch, created_at_unix_seconds)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&bundle.owner_id)
    .bind(bundle.payload_digest.to_string())
    .bind(&bundle.payload)
    .bind(bytes_digest.to_string())
    .bind(to_i64(bundle.payload.len() as u64, "payload bytes")?)
    .bind(to_i64(bundle.payload_tokens, "payload tokens")?)
    .bind(bundle.trust.generator.key_id.as_str())
    .bind(to_i64(bundle.trust.generator.trust_epoch, "generator epoch")?)
    .bind(bundle.trust.tokenizer.key_id.as_str())
    .bind(to_i64(bundle.trust.tokenizer.trust_epoch, "tokenizer epoch")?)
    .bind(to_i64(bundle.accepted_at_unix_seconds, "payload created at")?)
    .execute(&mut *connection)
    .await?;
    if result.rows_affected() == 0 {
        let row = sqlx::query(
            "SELECT payload_bytes_digest, encoded_bytes, token_count
             FROM compaction_payloads WHERE owner_id = ? AND payload_digest = ?",
        )
        .bind(&bundle.owner_id)
        .bind(bundle.payload_digest.to_string())
        .fetch_one(&mut *connection)
        .await?;
        let existing: String = row.try_get("payload_bytes_digest")?;
        let encoded: i64 = row.try_get("encoded_bytes")?;
        let tokens: i64 = row.try_get("token_count")?;
        if existing != bytes_digest.to_string()
            || encoded != to_i64(bundle.payload.len() as u64, "payload bytes")?
            || tokens != to_i64(bundle.payload_tokens, "payload tokens")?
        {
            return Err(conflict("payload digest was reused with different bytes or costs"));
        }
    }
    Ok(())
}

async fn insert_candidate(
    connection: &mut SqliteConnection,
    bundle: &DurableCompactionBundleV1,
) -> Result<(), DurableCompactionError> {
    sqlx::query(
        "INSERT INTO compaction_candidates
         (owner_id, idempotency_key, scope_id, purpose_id, generation,
          predecessor_checkpoint_digest, source_snapshot_digest,
          source_memory_snapshot_digest, source_retention_fence_digest,
          retain_source_until_unix_seconds, policy_digest, candidate_digest,
          candidate_image, candidate_image_digest, payload_digest,
          selector_key_id, selector_trust_epoch, generator_key_id,
          generator_trust_epoch, tokenizer_key_id, tokenizer_trust_epoch,
          accepted_at_unix_seconds)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&bundle.owner_id)
    .bind(&bundle.idempotency_key)
    .bind(&bundle.scope_id)
    .bind(&bundle.purpose_id)
    .bind(to_i64(bundle.generation, "generation")?)
    .bind(bundle.predecessor_checkpoint_digest.map(|value| value.to_string()))
    .bind(bundle.source_snapshot_digest.to_string())
    .bind(bundle.source_memory_snapshot_digest.to_string())
    .bind(bundle.source_retention_fence_digest.to_string())
    .bind(to_i64(bundle.retain_source_until_unix_seconds, "retention deadline")?)
    .bind(bundle.policy_digest.to_string())
    .bind(bundle.candidate_digest.to_string())
    .bind(&bundle.images.candidate_image)
    .bind(Digest32::of_bytes(&bundle.images.candidate_image).to_string())
    .bind(bundle.payload_digest.to_string())
    .bind(bundle.trust.selector.key_id.as_str())
    .bind(to_i64(bundle.trust.selector.trust_epoch, "selector epoch")?)
    .bind(bundle.trust.generator.key_id.as_str())
    .bind(to_i64(bundle.trust.generator.trust_epoch, "generator epoch")?)
    .bind(bundle.trust.tokenizer.key_id.as_str())
    .bind(to_i64(bundle.trust.tokenizer.trust_epoch, "tokenizer epoch")?)
    .bind(to_i64(bundle.accepted_at_unix_seconds, "candidate accepted at")?)
    .execute(&mut *connection)
    .await?;
    Ok(())
}

async fn insert_evaluation(
    connection: &mut SqliteConnection,
    bundle: &DurableCompactionBundleV1,
) -> Result<(), DurableCompactionError> {
    sqlx::query(
        "INSERT INTO compaction_evaluations
         (owner_id, evaluation_digest, candidate_digest, evaluator_key_id,
          evaluator_trust_epoch, evaluation_image, evaluation_image_digest,
          accepted_at_unix_seconds)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&bundle.owner_id)
    .bind(bundle.evaluation_digest.to_string())
    .bind(bundle.candidate_digest.to_string())
    .bind(bundle.trust.evaluator.key_id.as_str())
    .bind(to_i64(bundle.trust.evaluator.trust_epoch, "evaluator epoch")?)
    .bind(&bundle.images.evaluation_image)
    .bind(Digest32::of_bytes(&bundle.images.evaluation_image).to_string())
    .bind(to_i64(bundle.accepted_at_unix_seconds, "evaluation accepted at")?)
    .execute(&mut *connection)
    .await?;
    Ok(())
}

async fn insert_proof(
    connection: &mut SqliteConnection,
    bundle: &DurableCompactionBundleV1,
) -> Result<(), DurableCompactionError> {
    let mut witness = Vec::with_capacity(96);
    witness.extend_from_slice(&bundle.trusted_proof.witness.evaluator_verifying_key);
    witness.extend_from_slice(&bundle.trusted_proof.witness.qualification_signature);
    sqlx::query(
        "INSERT INTO compaction_proofs
         (owner_id, proof_digest, candidate_digest, checkpoint_digest,
          evaluation_digest, proof_image, proof_image_digest, proof_witness,
          accepted_at_unix_seconds)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&bundle.owner_id)
    .bind(bundle.proof_digest.to_string())
    .bind(bundle.candidate_digest.to_string())
    .bind(bundle.checkpoint_digest.to_string())
    .bind(bundle.evaluation_digest.to_string())
    .bind(&bundle.images.proof_image)
    .bind(Digest32::of_bytes(&bundle.images.proof_image).to_string())
    .bind(witness)
    .bind(to_i64(bundle.accepted_at_unix_seconds, "proof accepted at")?)
    .execute(&mut *connection)
    .await?;
    Ok(())
}

async fn insert_checkpoint(
    connection: &mut SqliteConnection,
    bundle: &DurableCompactionBundleV1,
) -> Result<(), DurableCompactionError> {
    sqlx::query(
        "INSERT INTO compaction_checkpoints
         (owner_id, scope_id, purpose_id, generation, checkpoint_digest,
          predecessor_checkpoint_digest, source_snapshot_digest,
          source_memory_snapshot_digest, candidate_digest, payload_digest,
          proof_digest, checkpoint_image, checkpoint_image_digest,
          publication_digest, published_at_unix_seconds)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&bundle.owner_id)
    .bind(&bundle.scope_id)
    .bind(&bundle.purpose_id)
    .bind(to_i64(bundle.generation, "generation")?)
    .bind(bundle.checkpoint_digest.to_string())
    .bind(bundle.predecessor_checkpoint_digest.map(|value| value.to_string()))
    .bind(bundle.source_snapshot_digest.to_string())
    .bind(bundle.source_memory_snapshot_digest.to_string())
    .bind(bundle.candidate_digest.to_string())
    .bind(bundle.payload_digest.to_string())
    .bind(bundle.proof_digest.to_string())
    .bind(&bundle.images.checkpoint_image)
    .bind(Digest32::of_bytes(&bundle.images.checkpoint_image).to_string())
    .bind(bundle.publication_digest.to_string())
    .bind(to_i64(bundle.accepted_at_unix_seconds, "published at")?)
    .execute(&mut *connection)
    .await?;
    Ok(())
}

async fn advance_active_checkpoint(
    connection: &mut SqliteConnection,
    bundle: &DurableCompactionBundleV1,
) -> Result<(), DurableCompactionError> {
    let active = sqlx::query(
        "SELECT generation, checkpoint_digest FROM active_compaction_checkpoint
         WHERE owner_id = ? AND scope_id = ? AND purpose_id = ?",
    )
    .bind(&bundle.owner_id)
    .bind(&bundle.scope_id)
    .bind(&bundle.purpose_id)
    .fetch_optional(&mut *connection)
    .await?;
    match active {
        None => {
            if bundle.generation != 1 || bundle.predecessor_checkpoint_digest.is_some() {
                return Err(conflict(
                    "first durable checkpoint must be generation one with no predecessor",
                ));
            }
            sqlx::query(
                "INSERT INTO active_compaction_checkpoint
                 (owner_id, scope_id, purpose_id, generation, checkpoint_digest,
                  predecessor_checkpoint_digest, publication_digest, updated_at_unix_seconds)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(&bundle.owner_id)
            .bind(&bundle.scope_id)
            .bind(&bundle.purpose_id)
            .bind(to_i64(bundle.generation, "generation")?)
            .bind(bundle.checkpoint_digest.to_string())
            .bind(Option::<String>::None)
            .bind(bundle.publication_digest.to_string())
            .bind(to_i64(bundle.accepted_at_unix_seconds, "active updated at")?)
            .execute(&mut *connection)
            .await?;
        }
        Some(row) => {
            let previous_generation: i64 = row.try_get("generation")?;
            let previous_digest: String = row.try_get("checkpoint_digest")?;
            if to_i64(bundle.generation, "generation")? != previous_generation + 1
                || bundle.predecessor_checkpoint_digest.map(|value| value.to_string())
                    != Some(previous_digest.clone())
            {
                return Err(conflict("checkpoint predecessor/generation CAS failed"));
            }
            let updated = sqlx::query(
                "UPDATE active_compaction_checkpoint
                 SET generation = ?, checkpoint_digest = ?, predecessor_checkpoint_digest = ?,
                     publication_digest = ?, updated_at_unix_seconds = ?
                 WHERE owner_id = ? AND scope_id = ? AND purpose_id = ?
                   AND generation = ? AND checkpoint_digest = ?",
            )
            .bind(to_i64(bundle.generation, "generation")?)
            .bind(bundle.checkpoint_digest.to_string())
            .bind(previous_digest.clone())
            .bind(bundle.publication_digest.to_string())
            .bind(to_i64(bundle.accepted_at_unix_seconds, "active updated at")?)
            .bind(&bundle.owner_id)
            .bind(&bundle.scope_id)
            .bind(&bundle.purpose_id)
            .bind(previous_generation)
            .bind(previous_digest)
            .execute(&mut *connection)
            .await?;
            if updated.rows_affected() != 1 {
                return Err(conflict("active checkpoint CAS lost a concurrent writer race"));
            }
        }
    }
    Ok(())
}

async fn insert_outbox(
    connection: &mut SqliteConnection,
    bundle: &DurableCompactionBundleV1,
    event_kind: &str,
    payload: Vec<u8>,
) -> Result<(), DurableCompactionError> {
    insert_outbox_raw(
        connection,
        &bundle.owner_id,
        &bundle.publication_digest.to_string(),
        event_kind,
        payload,
        bundle.accepted_at_unix_seconds,
    )
    .await
}

async fn insert_outbox_raw(
    connection: &mut SqliteConnection,
    owner_id: &str,
    publication_digest: &str,
    event_kind: &str,
    payload: Vec<u8>,
    created_at: u64,
) -> Result<(), DurableCompactionError> {
    if payload.is_empty() || payload.len() > MAX_DURABLE_COMPACTION_OUTBOX_PAYLOAD_BYTES {
        return Err(invalid("outbox payload is outside the durable bound"));
    }
    let publication = parse_digest(publication_digest, "outbox publication")?;
    let event_id = outbox_event_id(publication, event_kind);
    let payload_digest = Digest32::of_bytes(&payload);
    sqlx::query(
        "INSERT OR IGNORE INTO compaction_outbox
         (owner_id, event_id, publication_digest, event_kind, payload, payload_digest,
          state, attempt_count, claim_token, next_attempt_at_unix_seconds,
          created_at_unix_seconds, delivered_at_unix_seconds, terminal_error_digest)
         VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, NULL, ?, ?, NULL, NULL)",
    )
    .bind(owner_id)
    .bind(event_id.to_string())
    .bind(publication_digest)
    .bind(event_kind)
    .bind(payload)
    .bind(payload_digest.to_string())
    .bind(to_i64(created_at, "outbox next attempt")?)
    .bind(to_i64(created_at, "outbox created at")?)
    .execute(&mut *connection)
    .await?;
    Ok(())
}

fn decode_selection(
    row: sqlx::sqlite::SqliteRow,
    owner_id: &str,
    scope_id: &str,
    purpose_id: &str,
    active_digest: &str,
) -> Result<Option<DurableCompactionSelectionV1>, DurableCompactionError> {
    let payload: Vec<u8> = row.try_get("payload_bytes")?;
    let payload_digest_text: String = row.try_get("payload_digest")?;
    let payload_bytes_digest: String = row.try_get("payload_bytes_digest")?;
    if Digest32::of_bytes(&payload).to_string() != payload_bytes_digest
        || Digest32::of_bytes(&payload).to_string() != payload_digest_text
    {
        return Err(corrupt("persisted payload fails content-address verification"));
    }
    let proof_image: Vec<u8> = row.try_get("proof_image")?;
    let proof_image_digest: String = row.try_get("proof_image_digest")?;
    let checkpoint_image: Vec<u8> = row.try_get("checkpoint_image")?;
    let checkpoint_image_digest: String = row.try_get("checkpoint_image_digest")?;
    if Digest32::of_bytes(&proof_image).to_string() != proof_image_digest
        || Digest32::of_bytes(&checkpoint_image).to_string() != checkpoint_image_digest
    {
        return Err(corrupt("persisted proof/checkpoint image digest mismatch"));
    }
    let checkpoint_digest_text: String = row.try_get("checkpoint_digest")?;
    Ok(Some(DurableCompactionSelectionV1 {
        owner_id: owner_id.to_string(),
        scope_id: scope_id.to_string(),
        purpose_id: purpose_id.to_string(),
        generation: from_i64(row.try_get("generation")?, "generation")?,
        checkpoint_digest: parse_digest(&checkpoint_digest_text, "checkpoint")?,
        predecessor_checkpoint_digest: row
            .try_get::<Option<String>, _>("predecessor_checkpoint_digest")?
            .as_deref()
            .map(|value| parse_digest(value, "predecessor"))
            .transpose()?,
        source_snapshot_digest: parse_digest(
            &row.try_get::<String, _>("source_snapshot_digest")?,
            "source snapshot",
        )?,
        source_memory_snapshot_digest: parse_digest(
            &row.try_get::<String, _>("source_memory_snapshot_digest")?,
            "source memory snapshot",
        )?,
        candidate_digest: parse_digest(
            &row.try_get::<String, _>("candidate_digest")?,
            "candidate",
        )?,
        payload_digest: parse_digest(&payload_digest_text, "payload")?,
        proof_digest: parse_digest(&row.try_get::<String, _>("proof_digest")?, "proof")?,
        publication_digest: parse_digest(
            &row.try_get::<String, _>("publication_digest")?,
            "publication",
        )?,
        payload,
        proof_image,
        checkpoint_image,
        fell_back_from_revoked_head: checkpoint_digest_text != active_digest,
    }))
}

async fn verify_payload_rows(
    pool: &SqlitePool,
    owner_id: &str,
) -> Result<(), DurableCompactionError> {
    let rows = sqlx::query(
        "SELECT payload_digest, payload_bytes, payload_bytes_digest, encoded_bytes
         FROM compaction_payloads WHERE owner_id = ?",
    )
    .bind(owner_id)
    .fetch_all(pool)
    .await?;
    for row in rows {
        let payload: Vec<u8> = row.try_get("payload_bytes")?;
        let semantic_digest: String = row.try_get("payload_digest")?;
        let bytes_digest: String = row.try_get("payload_bytes_digest")?;
        let encoded: i64 = row.try_get("encoded_bytes")?;
        let actual = Digest32::of_bytes(&payload).to_string();
        if payload.is_empty()
            || payload.len() > MAX_DURABLE_COMPACTION_ARTIFACT_BYTES
            || actual != semantic_digest
            || actual != bytes_digest
            || encoded != i64::try_from(payload.len()).unwrap_or(i64::MAX)
        {
            return Err(corrupt("payload row fails digest/length verification"));
        }
    }
    Ok(())
}

async fn verify_active_rows(
    pool: &SqlitePool,
    owner_id: &str,
) -> Result<(), DurableCompactionError> {
    let rows = sqlx::query(
        "SELECT a.scope_id, a.purpose_id, a.generation, a.checkpoint_digest,
                c.checkpoint_digest AS stored_digest, c.predecessor_checkpoint_digest
         FROM active_compaction_checkpoint a
         LEFT JOIN compaction_checkpoints c
           ON c.owner_id = a.owner_id AND c.scope_id = a.scope_id
          AND c.purpose_id = a.purpose_id AND c.generation = a.generation
         WHERE a.owner_id = ?",
    )
    .bind(owner_id)
    .fetch_all(pool)
    .await?;
    for row in rows {
        let active: String = row.try_get("checkpoint_digest")?;
        let stored: Option<String> = row.try_get("stored_digest")?;
        if stored.as_deref() != Some(active.as_str()) {
            return Err(corrupt("active checkpoint pointer has no exact immutable target"));
        }
    }
    Ok(())
}

fn trust_role_name(role: CompactionTrustRoleV1) -> &'static str {
    match role {
        CompactionTrustRoleV1::RetentionSelector => "retention-selector",
        CompactionTrustRoleV1::SemanticGenerator => "semantic-generator",
        CompactionTrustRoleV1::Tokenizer => "tokenizer",
        CompactionTrustRoleV1::Evaluator => "evaluator",
    }
}

fn outbox_payload(bundle: &DurableCompactionBundleV1) -> Vec<u8> {
    format!(
        "{}:{}:{}:{}:{}",
        bundle.scope_id,
        bundle.purpose_id,
        bundle.generation,
        bundle.checkpoint_digest,
        bundle.publication_digest
    )
    .into_bytes()
}

fn outbox_event_id(publication_digest: Digest32, event_kind: &str) -> Digest32 {
    digest_parts(
        OUTBOX_DOMAIN,
        &[publication_digest.to_string().as_bytes(), event_kind.as_bytes()],
    )
}

fn source_retention_fence_digest(
    owner_id: &str,
    scope_id: &str,
    purpose_id: &str,
    snapshot_digest: Digest32,
    memory_digest: Digest32,
    generation: u64,
    retain_until: u64,
) -> Digest32 {
    digest_parts(
        SOURCE_RETENTION_DOMAIN,
        &[
            owner_id.as_bytes(),
            scope_id.as_bytes(),
            purpose_id.as_bytes(),
            snapshot_digest.to_string().as_bytes(),
            memory_digest.to_string().as_bytes(),
            &generation.to_be_bytes(),
            &retain_until.to_be_bytes(),
        ],
    )
}

#[allow(clippy::too_many_arguments)]
fn publication_digest(
    owner_id: &str,
    idempotency_key: &str,
    scope_id: &str,
    purpose_id: &str,
    generation: u64,
    predecessor: Option<Digest32>,
    source_snapshot: Digest32,
    source_memory: Digest32,
    source_retention: Digest32,
    policy: Digest32,
    candidate: Digest32,
    payload: Digest32,
    evaluation: Digest32,
    proof: Digest32,
    checkpoint: Digest32,
    selection_receipt: Digest32,
    generation_receipt: Digest32,
    trust: &DurableCompactionTrustSetV1,
    images: &CompactionArtifactImagesV1,
    accepted_at: u64,
) -> Digest32 {
    let predecessor_text = predecessor.map(|value| value.to_string()).unwrap_or_default();
    let generation_bytes = generation.to_be_bytes();
    let accepted_bytes = accepted_at.to_be_bytes();
    let image_digests = [
        Digest32::of_bytes(&images.candidate_image),
        Digest32::of_bytes(&images.evaluation_image),
        Digest32::of_bytes(&images.proof_image),
        Digest32::of_bytes(&images.checkpoint_image),
    ];
    let owned = [
        source_snapshot.to_string(),
        source_memory.to_string(),
        source_retention.to_string(),
        policy.to_string(),
        candidate.to_string(),
        payload.to_string(),
        evaluation.to_string(),
        proof.to_string(),
        checkpoint.to_string(),
        selection_receipt.to_string(),
        generation_receipt.to_string(),
        trust.selector.identity_digest().to_string(),
        trust.generator.identity_digest().to_string(),
        trust.tokenizer.identity_digest().to_string(),
        trust.evaluator.identity_digest().to_string(),
        image_digests[0].to_string(),
        image_digests[1].to_string(),
        image_digests[2].to_string(),
        image_digests[3].to_string(),
    ];
    let mut parts: Vec<&[u8]> = vec![
        owner_id.as_bytes(),
        idempotency_key.as_bytes(),
        scope_id.as_bytes(),
        purpose_id.as_bytes(),
        &generation_bytes,
        predecessor_text.as_bytes(),
    ];
    parts.extend(owned.iter().map(String::as_bytes));
    parts.push(&accepted_bytes);
    digest_parts(PUBLICATION_DOMAIN, &parts)
}

fn digest_parts(domain: &[u8], parts: &[&[u8]]) -> Digest32 {
    let mut hasher = Sha256::new();
    hasher.update(domain);
    for part in parts {
        hasher.update((part.len() as u64).to_be_bytes());
        hasher.update(part);
    }
    let output = hasher.finalize();
    let mut digest = [0_u8; 32];
    digest.copy_from_slice(&output);
    Digest32::from_array(digest)
}

fn validate_text_identity(name: &str, value: &str) -> Result<(), DurableCompactionError> {
    if value.trim() != value
        || value.is_empty()
        || value.len() > 128
        || value.as_bytes().contains(&0)
    {
        return Err(invalid(format!("{name} must contain 1..=128 canonical bytes")));
    }
    Ok(())
}

fn ensure_digest(value: Digest32, name: &str) -> Result<(), DurableCompactionError> {
    if value.is_zero() {
        return Err(invalid(format!("{name} digest must be non-zero")));
    }
    Ok(())
}

fn parse_digest(value: &str, name: &str) -> Result<Digest32, DurableCompactionError> {
    value
        .parse()
        .map_err(|error| corrupt(format!("invalid {name} digest: {error}")))
}

fn to_i64(value: u64, name: &str) -> Result<i64, DurableCompactionError> {
    i64::try_from(value).map_err(|_| invalid(format!("{name} exceeds SQLite integer range")))
}

fn from_i64(value: i64, name: &str) -> Result<u64, DurableCompactionError> {
    u64::try_from(value).map_err(|_| corrupt(format!("persisted {name} is negative")))
}

fn now_unix_seconds() -> Result<u64, DurableCompactionError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| invalid(format!("system clock error: {error}")))
        .map(|duration| duration.as_secs())
}

fn invalid(message: impl Into<String>) -> DurableCompactionError {
    DurableCompactionError::Invalid(message.into())
}

fn conflict(message: impl Into<String>) -> DurableCompactionError {
    DurableCompactionError::Conflict(message.into())
}

fn corrupt(message: impl Into<String>) -> DurableCompactionError {
    DurableCompactionError::Corrupt(message.into())
}

#[cfg(test)]
#[path = "durable_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "durable_fence_tests.rs"]
mod fence_tests;
