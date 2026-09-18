//! Durable canonical Lane C compact checkpoint publication.
//!
//! The cognitive SQLite owner persists compact.engine metadata without ever
//! rewriting source facts. Publication is guarded by the existing live local
//! lease/fence, uses `BEGIN IMMEDIATE`, performs generation/predecessor CAS,
//! and stores complete authority-free checkpoint/proof images that are
//! reconstructed and revalidated on every reopen.

use std::collections::BTreeMap;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
use codex_hepta_cognitive_types::lane_c::CompactionProofV2;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::SqlitePool;
use thiserror::Error;

use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::CompactFence;
use crate::LocalLeaseOutbox;
use crate::LocalLeaseOutboxError;
use crate::cognitive_store::unavailable;
use crate::framing::frame_part;

const MAX_QUALIFIED_CHECKPOINT_ROWS: usize = 16_384;
const PUBLICATION_DOMAIN: &[u8] = b"hepta-memory:qualified-compact-publication:v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum QualifiedCompactPublicationDisposition {
    Inserted,
    Unchanged,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedCompactCheckpointPublication {
    pub checkpoint: CompactCheckpointV1,
    pub proof: CompactionProofV2,
    pub publication_digest: Digest32,
    pub disposition: QualifiedCompactPublicationDisposition,
    pub authority: AuthorityPosture,
}

#[derive(Debug, Error)]
pub enum QualifiedCompactStoreError {
    #[error("invalid qualified compact checkpoint: {0}")]
    Invalid(String),
    #[error("qualified compact checkpoint CAS conflict: {0}")]
    Conflict(String),
    #[error("qualified compact checkpoint store is corrupt: {0}")]
    Corrupt(String),
    #[error(transparent)]
    Store(#[from] CognitiveStoreError),
    #[error(transparent)]
    Lease(#[from] LocalLeaseOutboxError),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct SnapshotImageV1 {
    scope_id: String,
    purpose_id: String,
    memory_ledger_frontier: u64,
    knowledge_fact_frontier: u64,
    tombstone_frontier: u64,
    source_ledger_frontier: u64,
    knowledge_graph_generation: u64,
    compact_checkpoint_generation: u64,
    prompt_registry_revision: u64,
    retrieval_profile_digest: String,
    encoder_preprocessor_digest: String,
    authority_epoch: u64,
    model_digest: String,
    tokenizer_digest: String,
    template_digest: String,
    tool_schema_digest: String,
    vector_digest: String,
}

impl SnapshotImageV1 {
    fn from_contract(snapshot: &CognitiveSnapshotKeyV1) -> Self {
        Self {
            scope_id: snapshot.vector.scope_id.to_string(),
            purpose_id: snapshot.vector.purpose_id.to_string(),
            memory_ledger_frontier: snapshot.vector.memory_ledger_frontier,
            knowledge_fact_frontier: snapshot.vector.knowledge_fact_frontier,
            tombstone_frontier: snapshot.vector.tombstone_frontier,
            source_ledger_frontier: snapshot.vector.source_ledger_frontier,
            knowledge_graph_generation: snapshot.vector.knowledge_graph_generation.get(),
            compact_checkpoint_generation: snapshot.vector.compact_checkpoint_generation.get(),
            prompt_registry_revision: snapshot.vector.prompt_registry_revision.get(),
            retrieval_profile_digest: snapshot.vector.retrieval_profile_digest.to_string(),
            encoder_preprocessor_digest: snapshot.vector.encoder_preprocessor_digest.to_string(),
            authority_epoch: snapshot.vector.authority_epoch,
            model_digest: snapshot.vector.model_digest.to_string(),
            tokenizer_digest: snapshot.vector.tokenizer_digest.to_string(),
            template_digest: snapshot.vector.template_digest.to_string(),
            tool_schema_digest: snapshot.vector.tool_schema_digest.to_string(),
            vector_digest: snapshot.vector_digest.to_string(),
        }
    }

    fn to_contract(&self) -> Result<CognitiveSnapshotKeyV1, QualifiedCompactStoreError> {
        let vector = LaneCGenerationVectorV1 {
            scope_id: parse_id(&self.scope_id, "scope id")?,
            purpose_id: parse_id(&self.purpose_id, "purpose id")?,
            memory_ledger_frontier: self.memory_ledger_frontier,
            knowledge_fact_frontier: self.knowledge_fact_frontier,
            tombstone_frontier: self.tombstone_frontier,
            source_ledger_frontier: self.source_ledger_frontier,
            knowledge_graph_generation: parse_generation(
                self.knowledge_graph_generation,
                "knowledge graph generation",
            )?,
            compact_checkpoint_generation: parse_generation(
                self.compact_checkpoint_generation,
                "compact checkpoint generation",
            )?,
            prompt_registry_revision: Revision::new(self.prompt_registry_revision)
                .map_err(|error| corrupt(format!("invalid prompt registry revision: {error}")))?,
            retrieval_profile_digest: parse_digest(
                &self.retrieval_profile_digest,
                "retrieval profile digest",
            )?,
            encoder_preprocessor_digest: parse_digest(
                &self.encoder_preprocessor_digest,
                "encoder preprocessor digest",
            )?,
            authority_epoch: self.authority_epoch,
            model_digest: parse_digest(&self.model_digest, "model digest")?,
            tokenizer_digest: parse_digest(&self.tokenizer_digest, "tokenizer digest")?,
            template_digest: parse_digest(&self.template_digest, "template digest")?,
            tool_schema_digest: parse_digest(&self.tool_schema_digest, "tool schema digest")?,
        };
        let snapshot = CognitiveSnapshotKeyV1::new(vector)
            .map_err(|error| corrupt(format!("invalid source snapshot: {error}")))?;
        if snapshot.vector_digest
            != parse_digest(&self.vector_digest, "source snapshot vector digest")?
        {
            return Err(corrupt("source snapshot vector digest mismatch"));
        }
        Ok(snapshot)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct CheckpointImageV1 {
    checkpoint_id: String,
    generation: u64,
    source_snapshot: SnapshotImageV1,
    support_manifest_digest: String,
    algorithm_digest: String,
    payload_digest: String,
    omitted_information_digest: String,
    tombstone_cutoff: u64,
    predecessor_digest: Option<String>,
    compatibility_digest: String,
    checkpoint_digest: String,
}

impl CheckpointImageV1 {
    fn from_contract(checkpoint: &CompactCheckpointV1) -> Self {
        Self {
            checkpoint_id: checkpoint.checkpoint_id.to_string(),
            generation: checkpoint.generation.get(),
            source_snapshot: SnapshotImageV1::from_contract(&checkpoint.source_snapshot),
            support_manifest_digest: checkpoint.support_manifest_digest.to_string(),
            algorithm_digest: checkpoint.algorithm_digest.to_string(),
            payload_digest: checkpoint.payload_digest.to_string(),
            omitted_information_digest: checkpoint.omitted_information_digest.to_string(),
            tombstone_cutoff: checkpoint.tombstone_cutoff,
            predecessor_digest: checkpoint.predecessor_digest.map(|value| value.to_string()),
            compatibility_digest: checkpoint.compatibility_digest.to_string(),
            checkpoint_digest: checkpoint.checkpoint_digest.to_string(),
        }
    }

    fn to_contract(&self) -> Result<CompactCheckpointV1, QualifiedCompactStoreError> {
        let checkpoint = CompactCheckpointV1 {
            checkpoint_id: parse_id(&self.checkpoint_id, "checkpoint id")?,
            generation: parse_generation(self.generation, "checkpoint generation")?,
            source_snapshot: self.source_snapshot.to_contract()?,
            support_manifest_digest: parse_digest(
                &self.support_manifest_digest,
                "support manifest digest",
            )?,
            algorithm_digest: parse_digest(&self.algorithm_digest, "algorithm digest")?,
            payload_digest: parse_digest(&self.payload_digest, "payload digest")?,
            omitted_information_digest: parse_digest(
                &self.omitted_information_digest,
                "omitted information digest",
            )?,
            tombstone_cutoff: self.tombstone_cutoff,
            predecessor_digest: self
                .predecessor_digest
                .as_deref()
                .map(|value| parse_digest(value, "predecessor digest"))
                .transpose()?,
            compatibility_digest: parse_digest(&self.compatibility_digest, "compatibility digest")?,
            checkpoint_digest: parse_digest(&self.checkpoint_digest, "checkpoint digest")?,
            authority: AuthorityPosture::DENY_ALL,
        };
        checkpoint
            .validate()
            .map_err(|error| corrupt(format!("invalid persisted checkpoint: {error}")))?;
        Ok(checkpoint)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct ProofImageV2 {
    checkpoint_digest: String,
    candidate_digest: String,
    evaluator_id: String,
    evaluator_implementation_digest: String,
    evaluation_artifact_digest: String,
    attestation_digest: String,
    attestation_signature_digest: String,
    signature_verification_receipt_digest: String,
    retained_query_suite_digest: String,
    reconstruction_obligation_digest: String,
    contradiction_holdout_digest: String,
    deletion_cutoff: u64,
    source_count: u64,
    retained_count: u64,
    proof_digest: String,
}

impl ProofImageV2 {
    fn from_contract(proof: &CompactionProofV2) -> Self {
        Self {
            checkpoint_digest: proof.checkpoint_digest.to_string(),
            candidate_digest: proof.candidate_digest.to_string(),
            evaluator_id: proof.evaluator_id.to_string(),
            evaluator_implementation_digest: proof.evaluator_implementation_digest.to_string(),
            evaluation_artifact_digest: proof.evaluation_artifact_digest.to_string(),
            attestation_digest: proof.attestation_digest.to_string(),
            attestation_signature_digest: proof.attestation_signature_digest.to_string(),
            signature_verification_receipt_digest: proof
                .signature_verification_receipt_digest
                .to_string(),
            retained_query_suite_digest: proof.retained_query_suite_digest.to_string(),
            reconstruction_obligation_digest: proof.reconstruction_obligation_digest.to_string(),
            contradiction_holdout_digest: proof.contradiction_holdout_digest.to_string(),
            deletion_cutoff: proof.deletion_cutoff,
            source_count: proof.source_count,
            retained_count: proof.retained_count,
            proof_digest: proof.proof_digest.to_string(),
        }
    }

    fn to_contract(&self) -> Result<CompactionProofV2, QualifiedCompactStoreError> {
        let proof = CompactionProofV2 {
            checkpoint_digest: parse_digest(&self.checkpoint_digest, "proof checkpoint digest")?,
            candidate_digest: parse_digest(&self.candidate_digest, "candidate digest")?,
            evaluator_id: parse_id(&self.evaluator_id, "evaluator id")?,
            evaluator_implementation_digest: parse_digest(
                &self.evaluator_implementation_digest,
                "evaluator implementation digest",
            )?,
            evaluation_artifact_digest: parse_digest(
                &self.evaluation_artifact_digest,
                "evaluation artifact digest",
            )?,
            attestation_digest: parse_digest(&self.attestation_digest, "attestation digest")?,
            attestation_signature_digest: parse_digest(
                &self.attestation_signature_digest,
                "attestation signature digest",
            )?,
            signature_verification_receipt_digest: parse_digest(
                &self.signature_verification_receipt_digest,
                "signature verification receipt digest",
            )?,
            retained_query_suite_digest: parse_digest(
                &self.retained_query_suite_digest,
                "retained query suite digest",
            )?,
            reconstruction_obligation_digest: parse_digest(
                &self.reconstruction_obligation_digest,
                "reconstruction obligation digest",
            )?,
            contradiction_holdout_digest: parse_digest(
                &self.contradiction_holdout_digest,
                "contradiction holdout digest",
            )?,
            deletion_cutoff: self.deletion_cutoff,
            source_count: self.source_count,
            retained_count: self.retained_count,
            proof_digest: parse_digest(&self.proof_digest, "proof digest")?,
            authority: AuthorityPosture::DENY_ALL,
        };
        proof
            .validate()
            .map_err(|error| corrupt(format!("invalid persisted proof: {error}")))?;
        Ok(proof)
    }
}

impl CognitiveStore {
    /// Atomically publish a canonical compact checkpoint/proof under an exact
    /// live owner lease.  Identical retries are idempotent; changed payloads or
    /// non-successor generations fail closed.
    pub async fn publish_qualified_compact_checkpoint(
        &self,
        lease: &LocalLeaseOutbox,
        fence: &CompactFence,
        checkpoint: &CompactCheckpointV1,
        proof: &CompactionProofV2,
    ) -> Result<QualifiedCompactCheckpointPublication, QualifiedCompactStoreError> {
        validate_pair(checkpoint, proof)?;
        if !self.is_same_local_store(lease.store()) {
            return Err(invalid(
                "checkpoint publisher and lease belong to different local stores",
            ));
        }
        let binding = lease.binding().ok_or_else(|| {
            invalid("qualified checkpoint publication requires a schema-bound live lease")
        })?;
        if binding.authority_epoch != fence.authority_epoch
            || binding.owner_epoch != fence.owner_epoch
            || lease.generation() != fence.generation
            || lease.fencing_token() != fence.fencing_token
        {
            return Err(QualifiedCompactStoreError::Conflict(
                "lease binding does not match compact fence".to_string(),
            ));
        }
        if checkpoint.source_snapshot.vector.authority_epoch != fence.authority_epoch {
            return Err(QualifiedCompactStoreError::Conflict(
                "checkpoint snapshot authority epoch does not match the active fence".to_string(),
            ));
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = lease
            .verify_current_in_transaction(&mut transaction)
            .await?;
        if current.lease_id != lease.lease_id()
            || current.authority_epoch != Some(binding.authority_epoch)
            || current.owner_epoch != Some(binding.owner_epoch)
            || current.lease_expires_at_unix_seconds != Some(binding.lease_expires_at_unix_seconds)
        {
            return Err(QualifiedCompactStoreError::Conflict(
                "lease head changed before checkpoint publication".to_string(),
            ));
        }

        let scope_id = checkpoint.source_snapshot.vector.scope_id.as_str();
        let purpose_id = checkpoint.source_snapshot.vector.purpose_id.as_str();
        let latest = sqlx::query(
            "SELECT generation, checkpoint_digest, predecessor_digest,
                    candidate_digest, proof_digest, source_snapshot_digest,
                    tokenizer_digest, publication_digest, checkpoint_json, proof_json
             FROM cognitive_qualified_compact_checkpoints
             WHERE owner_agent_id = ? AND scope_id = ? AND purpose_id = ?
             ORDER BY generation DESC LIMIT 1",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_id)
        .bind(purpose_id)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?;

        if let Some(row) = latest.as_ref() {
            let latest_publication = decode_row(row)?;
            let latest_generation = latest_publication.checkpoint.generation.get();
            if latest_generation == checkpoint.generation.get() {
                let expected_publication_digest = publication_digest(checkpoint, proof);
                if latest_publication.checkpoint == *checkpoint
                    && latest_publication.proof == *proof
                    && latest_publication.publication_digest == expected_publication_digest
                {
                    transaction.commit().await.map_err(unavailable)?;
                    return Ok(QualifiedCompactCheckpointPublication {
                        checkpoint: checkpoint.clone(),
                        proof: proof.clone(),
                        publication_digest: expected_publication_digest,
                        disposition: QualifiedCompactPublicationDisposition::Unchanged,
                        authority: AuthorityPosture::DENY_ALL,
                    });
                }
                return Err(QualifiedCompactStoreError::Conflict(
                    "checkpoint generation was reused with different content".to_string(),
                ));
            }
            if latest_publication.checkpoint.generation.next().ok() != Some(checkpoint.generation) {
                return Err(QualifiedCompactStoreError::Conflict(
                    "checkpoint generation is not the durable successor".to_string(),
                ));
            }
            if checkpoint.predecessor_digest
                != Some(latest_publication.checkpoint.checkpoint_digest)
            {
                return Err(QualifiedCompactStoreError::Conflict(
                    "checkpoint predecessor does not match the durable head".to_string(),
                ));
            }
        } else if checkpoint.generation.get() > 1 && checkpoint.predecessor_digest.is_none() {
            return Err(QualifiedCompactStoreError::Conflict(
                "bootstrap successor checkpoint is missing its predecessor digest".to_string(),
            ));
        }

        let checkpoint_image = CheckpointImageV1::from_contract(checkpoint);
        let proof_image = ProofImageV2::from_contract(proof);
        let checkpoint_json = serde_json::to_string(&checkpoint_image)
            .map_err(|error| invalid(format!("checkpoint serialization failed: {error}")))?;
        let proof_json = serde_json::to_string(&proof_image)
            .map_err(|error| invalid(format!("proof serialization failed: {error}")))?;
        if checkpoint_json.len() > 32_768 || proof_json.len() > 32_768 {
            return Err(invalid(
                "qualified checkpoint persistence image is oversized",
            ));
        }
        let publication_digest = publication_digest(checkpoint, proof);
        let published_at = now_unix_seconds()?;

        sqlx::query(
            "INSERT INTO cognitive_qualified_compact_checkpoints (
                owner_agent_id, scope_id, purpose_id, generation,
                checkpoint_digest, predecessor_digest, candidate_digest, proof_digest,
                source_snapshot_digest, tokenizer_digest, publication_digest,
                checkpoint_json, proof_json, published_at_unix_seconds
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_id)
        .bind(purpose_id)
        .bind(
            i64::try_from(checkpoint.generation.get())
                .map_err(|_| invalid("checkpoint generation overflows SQLite"))?,
        )
        .bind(checkpoint.checkpoint_digest.to_string())
        .bind(checkpoint.predecessor_digest.map(|value| value.to_string()))
        .bind(proof.candidate_digest.to_string())
        .bind(proof.proof_digest.to_string())
        .bind(checkpoint.source_snapshot.vector_digest.to_string())
        .bind(
            checkpoint
                .source_snapshot
                .vector
                .tokenizer_digest
                .to_string(),
        )
        .bind(publication_digest.to_string())
        .bind(checkpoint_json)
        .bind(proof_json)
        .bind(published_at)
        .execute(&mut *transaction)
        .await
        .map_err(|error| {
            QualifiedCompactStoreError::Conflict(format!(
                "qualified checkpoint insert failed: {error}"
            ))
        })?;

        transaction.commit().await.map_err(unavailable)?;
        Ok(QualifiedCompactCheckpointPublication {
            checkpoint: checkpoint.clone(),
            proof: proof.clone(),
            publication_digest,
            disposition: QualifiedCompactPublicationDisposition::Inserted,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    /// Reopen the latest durable canonical checkpoint for one scope/purpose.
    /// Every row in that lineage is decoded, digest-checked and predecessor
    /// checked before the head is returned.
    pub async fn latest_qualified_compact_checkpoint(
        &self,
        scope_id: &StableId,
        purpose_id: &StableId,
    ) -> Result<Option<QualifiedCompactCheckpointPublication>, QualifiedCompactStoreError> {
        let rows = sqlx::query(
            "SELECT generation, checkpoint_digest, predecessor_digest,
                    candidate_digest, proof_digest, source_snapshot_digest,
                    tokenizer_digest, publication_digest, checkpoint_json, proof_json
             FROM cognitive_qualified_compact_checkpoints
             WHERE owner_agent_id = ? AND scope_id = ? AND purpose_id = ?
             ORDER BY generation",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_id.as_str())
        .bind(purpose_id.as_str())
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        let publications = decode_lineage(&rows, scope_id.as_str(), purpose_id.as_str())?;
        Ok(publications.last().cloned())
    }
}

pub(crate) async fn verify_qualified_compact_store(
    pool: &SqlitePool,
    owner: &codex_hepta_contracts::AgentId,
) -> Result<(), CognitiveStoreError> {
    let expected_objects = [
        ("cognitive_qualified_compact_checkpoints", "table"),
        (
            "cognitive_qualified_compact_checkpoints_no_update",
            "trigger",
        ),
        (
            "cognitive_qualified_compact_checkpoints_no_delete",
            "trigger",
        ),
        ("cognitive_qualified_compact_checkpoints_latest", "index"),
    ];
    for (name, expected_type) in expected_objects {
        let actual: Option<String> =
            sqlx::query_scalar("SELECT type FROM sqlite_schema WHERE name = ?")
                .bind(name)
                .fetch_optional(pool)
                .await
                .map_err(unavailable)?;
        if actual.as_deref() != Some(expected_type) {
            return Err(CognitiveStoreError::Corrupt(format!(
                "qualified compact schema object {name} is missing or has the wrong type"
            )));
        }
    }

    let foreign_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_qualified_compact_checkpoints
         WHERE owner_agent_id != ?",
    )
    .bind(owner.as_str())
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if foreign_rows != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "qualified compact checkpoint table contains a foreign owner".to_string(),
        ));
    }

    let rows = sqlx::query(
        "SELECT scope_id, purpose_id, generation, checkpoint_digest, predecessor_digest,
                candidate_digest, proof_digest, source_snapshot_digest,
                tokenizer_digest, publication_digest, checkpoint_json, proof_json
         FROM cognitive_qualified_compact_checkpoints
         WHERE owner_agent_id = ?
         ORDER BY scope_id, purpose_id, generation",
    )
    .bind(owner.as_str())
    .fetch_all(pool)
    .await
    .map_err(unavailable)?;
    if rows.len() > MAX_QUALIFIED_CHECKPOINT_ROWS {
        return Err(CognitiveStoreError::Corrupt(format!(
            "qualified compact checkpoint table exceeds {MAX_QUALIFIED_CHECKPOINT_ROWS} rows"
        )));
    }

    let mut groups = BTreeMap::<(String, String), Vec<sqlx::sqlite::SqliteRow>>::new();
    for row in rows {
        let scope_id: String = row.try_get("scope_id").map_err(unavailable)?;
        let purpose_id: String = row.try_get("purpose_id").map_err(unavailable)?;
        groups.entry((scope_id, purpose_id)).or_default().push(row);
    }
    for ((scope_id, purpose_id), rows) in groups {
        decode_lineage(&rows, &scope_id, &purpose_id)
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    }
    Ok(())
}

fn decode_lineage(
    rows: &[sqlx::sqlite::SqliteRow],
    expected_scope_id: &str,
    expected_purpose_id: &str,
) -> Result<Vec<QualifiedCompactCheckpointPublication>, QualifiedCompactStoreError> {
    if rows.len() > MAX_QUALIFIED_CHECKPOINT_ROWS {
        return Err(corrupt("qualified checkpoint lineage exceeds reopen limit"));
    }
    let mut publications = Vec::with_capacity(rows.len());
    let mut previous: Option<&QualifiedCompactCheckpointPublication> = None;
    for row in rows {
        let publication = decode_row(row)?;
        if publication
            .checkpoint
            .source_snapshot
            .vector
            .scope_id
            .as_str()
            != expected_scope_id
            || publication
                .checkpoint
                .source_snapshot
                .vector
                .purpose_id
                .as_str()
                != expected_purpose_id
        {
            return Err(corrupt("qualified checkpoint row scope/purpose mismatch"));
        }
        if let Some(previous) = previous {
            if previous.checkpoint.generation.next().ok() != Some(publication.checkpoint.generation)
                || publication.checkpoint.predecessor_digest
                    != Some(previous.checkpoint.checkpoint_digest)
            {
                return Err(corrupt("qualified checkpoint durable lineage is broken"));
            }
        }
        publications.push(publication);
        previous = publications.last();
    }
    Ok(publications)
}

fn decode_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<QualifiedCompactCheckpointPublication, QualifiedCompactStoreError> {
    let generation: i64 = row.try_get("generation").map_err(unavailable)?;
    let checkpoint_digest_text: String = row.try_get("checkpoint_digest").map_err(unavailable)?;
    let predecessor_digest_text: Option<String> =
        row.try_get("predecessor_digest").map_err(unavailable)?;
    let candidate_digest_text: String = row.try_get("candidate_digest").map_err(unavailable)?;
    let proof_digest_text: String = row.try_get("proof_digest").map_err(unavailable)?;
    let source_snapshot_digest_text: String =
        row.try_get("source_snapshot_digest").map_err(unavailable)?;
    let tokenizer_digest_text: String = row.try_get("tokenizer_digest").map_err(unavailable)?;
    let publication_digest_text: String = row.try_get("publication_digest").map_err(unavailable)?;
    let checkpoint_json: String = row.try_get("checkpoint_json").map_err(unavailable)?;
    let proof_json: String = row.try_get("proof_json").map_err(unavailable)?;

    let checkpoint_image: CheckpointImageV1 = serde_json::from_str(&checkpoint_json)
        .map_err(|error| corrupt(format!("checkpoint JSON is invalid: {error}")))?;
    let proof_image: ProofImageV2 = serde_json::from_str(&proof_json)
        .map_err(|error| corrupt(format!("proof JSON is invalid: {error}")))?;
    let checkpoint = checkpoint_image.to_contract()?;
    let proof = proof_image.to_contract()?;
    validate_pair(&checkpoint, &proof)?;

    if generation != i64::try_from(checkpoint.generation.get()).unwrap_or(i64::MAX)
        || checkpoint_digest_text != checkpoint.checkpoint_digest.to_string()
        || predecessor_digest_text != checkpoint.predecessor_digest.map(|value| value.to_string())
        || candidate_digest_text != proof.candidate_digest.to_string()
        || proof_digest_text != proof.proof_digest.to_string()
        || source_snapshot_digest_text != checkpoint.source_snapshot.vector_digest.to_string()
        || tokenizer_digest_text
            != checkpoint
                .source_snapshot
                .vector
                .tokenizer_digest
                .to_string()
    {
        return Err(corrupt(
            "qualified checkpoint row metadata does not match its canonical payload",
        ));
    }

    let expected_publication_digest = publication_digest(&checkpoint, &proof);
    if publication_digest_text != expected_publication_digest.to_string() {
        return Err(corrupt("qualified checkpoint publication digest mismatch"));
    }

    Ok(QualifiedCompactCheckpointPublication {
        checkpoint,
        proof,
        publication_digest: expected_publication_digest,
        disposition: QualifiedCompactPublicationDisposition::Inserted,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_pair(
    checkpoint: &CompactCheckpointV1,
    proof: &CompactionProofV2,
) -> Result<(), QualifiedCompactStoreError> {
    checkpoint
        .validate()
        .map_err(|error| invalid(format!("checkpoint contract rejected: {error}")))?;
    proof
        .validate()
        .map_err(|error| invalid(format!("proof contract rejected: {error}")))?;
    if proof.checkpoint_digest != checkpoint.checkpoint_digest {
        return Err(invalid("proof does not bind the checkpoint digest"));
    }
    if checkpoint
        .source_snapshot
        .vector
        .compact_checkpoint_generation
        .next()
        .ok()
        != Some(checkpoint.generation)
    {
        return Err(invalid(
            "checkpoint generation is not the successor of the source snapshot",
        ));
    }
    if proof.deletion_cutoff != checkpoint.tombstone_cutoff {
        return Err(invalid(
            "proof deletion cutoff does not match the checkpoint tombstone frontier",
        ));
    }
    Ok(())
}

fn publication_digest(checkpoint: &CompactCheckpointV1, proof: &CompactionProofV2) -> Digest32 {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, PUBLICATION_DOMAIN);
    frame_part(&mut hasher, &checkpoint.generation.get().to_be_bytes());
    frame_part(
        &mut hasher,
        checkpoint
            .source_snapshot
            .vector
            .scope_id
            .as_str()
            .as_bytes(),
    );
    frame_part(
        &mut hasher,
        checkpoint
            .source_snapshot
            .vector
            .purpose_id
            .as_str()
            .as_bytes(),
    );
    frame_part(&mut hasher, checkpoint.checkpoint_digest.as_array());
    frame_part(&mut hasher, proof.candidate_digest.as_array());
    frame_part(&mut hasher, proof.proof_digest.as_array());
    let output = hasher.finalize();
    let mut digest = [0_u8; 32];
    digest.copy_from_slice(&output);
    Digest32::from_array(digest)
}

fn parse_digest(value: &str, label: &str) -> Result<Digest32, QualifiedCompactStoreError> {
    value
        .parse()
        .map_err(|error| corrupt(format!("invalid {label}: {error}")))
}

fn parse_id(value: &str, label: &str) -> Result<StableId, QualifiedCompactStoreError> {
    StableId::new(value.to_string()).map_err(|error| corrupt(format!("invalid {label}: {error}")))
}

fn parse_generation(value: u64, label: &str) -> Result<Generation, QualifiedCompactStoreError> {
    Generation::new(value).map_err(|error| corrupt(format!("invalid {label}: {error}")))
}

fn now_unix_seconds() -> Result<i64, QualifiedCompactStoreError> {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| invalid(format!("system clock error: {error}")))?
        .as_secs();
    i64::try_from(seconds).map_err(|_| invalid("system clock overflow"))
}

fn invalid(message: impl Into<String>) -> QualifiedCompactStoreError {
    QualifiedCompactStoreError::Invalid(message.into())
}

fn corrupt(message: impl Into<String>) -> QualifiedCompactStoreError {
    QualifiedCompactStoreError::Corrupt(message.into())
}

#[cfg(test)]
#[path = "qualified_compact_store_tests.rs"]
mod tests;
