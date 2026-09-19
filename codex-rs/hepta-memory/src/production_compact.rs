//! Production publication/reload of canonical Lane C compaction checkpoints.
//!
//! Publications use the existing Agent-local append-only compact journal. Every
//! write is bound to the current externally-authorized ProductionDurableWriter
//! lease, serialized under BEGIN IMMEDIATE and checked with a checkpoint
//! generation/predecessor CAS. Reload verifies the complete row hash chain and
//! canonical checkpoint/proof digests before returning state.

use std::str::FromStr;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
use codex_hepta_cognitive_types::lane_c::CompactionProofV2;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_contracts::Sha256Digest;
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
use sqlx::Sqlite;
use sqlx::Transaction;
use thiserror::Error;

use crate::CognitiveStoreError;
use crate::ProductionDurableWriter;
use crate::ProductionWriterError;
use crate::framing::frame_part;

pub const PRODUCTION_COMPACT_NAMESPACE: &str = "compact.engine.production.v1";
pub const PRODUCTION_COMPACT_JOURNAL_ID: &str = "compact-engine:production:v1";
const MAX_EVENTS: usize = 4_096;
const MAX_EVENT_JSON_BYTES: usize = 65_536;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionCompactionPublication {
    pub checkpoint: CompactCheckpointV1,
    pub proof: CompactionProofV2,
    pub policy_digest: Digest32,
    pub candidate_digest: Digest32,
    pub retained_bytes: u64,
    pub retained_tokens: u64,
    pub omitted_bytes: u64,
    pub omitted_tokens: u64,
}

impl ProductionCompactionPublication {
    pub fn validate(&self) -> Result<(), ProductionCompactionError> {
        self.checkpoint
            .validate()
            .map_err(|error| ProductionCompactionError::Invalid(error.to_string()))?;
        self.proof
            .validate()
            .map_err(|error| ProductionCompactionError::Invalid(error.to_string()))?;
        if self.proof.checkpoint_digest != self.checkpoint.checkpoint_digest {
            return Err(ProductionCompactionError::Invalid(
                "proof/checkpoint digest mismatch".to_string(),
            ));
        }
        if self.policy_digest.is_zero() || self.candidate_digest.is_zero() {
            return Err(ProductionCompactionError::Invalid(
                "policy/candidate digests must be non-zero".to_string(),
            ));
        }
        if (self.proof.retained_count == 0)
            != (self.retained_bytes == 0 && self.retained_tokens == 0)
        {
            return Err(ProductionCompactionError::Invalid(
                "retained resource accounting mismatch".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionCompactionReceipt {
    pub sequence: u64,
    pub generation: Generation,
    pub checkpoint_digest: Digest32,
    pub proof_digest: Digest32,
    pub artifact_digest: Digest32,
    pub replayed: bool,
}

#[derive(Debug, Error)]
pub enum ProductionCompactionError {
    #[error(transparent)]
    Writer(#[from] ProductionWriterError),
    #[error(transparent)]
    Store(#[from] CognitiveStoreError),
    #[error("invalid production compaction publication: {0}")]
    Invalid(String),
    #[error("production compaction CAS conflict: {0}")]
    CasConflict(String),
    #[error("production compact journal is corrupt: {0}")]
    Corrupt(String),
    #[error("production compact serialization failed: {0}")]
    Serialization(String),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct DurableEvent {
    schema_version: u32,
    namespace: String,
    lease_generation: u64,
    payload: PublicationDto,
    artifact_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct PublicationDto {
    checkpoint: CheckpointDto,
    proof: ProofDto,
    policy_digest: String,
    candidate_digest: String,
    retained_bytes: u64,
    retained_tokens: u64,
    omitted_bytes: u64,
    omitted_tokens: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct SnapshotDto {
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

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct CheckpointDto {
    checkpoint_id: String,
    generation: u64,
    source_snapshot: SnapshotDto,
    support_manifest_digest: String,
    algorithm_digest: String,
    payload_digest: String,
    omitted_information_digest: String,
    tombstone_cutoff: u64,
    predecessor_digest: Option<String>,
    compatibility_digest: String,
    checkpoint_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct ProofDto {
    evaluator_id: String,
    evaluation_artifact_digest: String,
    evaluator_implementation_digest: String,
    attestation_digest: String,
    signature_digest: String,
    checkpoint_digest: String,
    retained_query_suite_digest: String,
    reconstruction_obligation_digest: String,
    contradiction_holdout_digest: String,
    deletion_cutoff: u64,
    source_count: u64,
    retained_count: u64,
    proof_digest: String,
}

#[derive(Clone)]
struct VerifiedRow {
    sequence: u64,
    event: DurableEvent,
    event_sha256: Sha256Digest,
}

impl ProductionDurableWriter {
    /// Atomically publish the next qualified canonical checkpoint.
    ///
    /// The production lease is revalidated inside the same SQLite write
    /// transaction. Generation/predecessor form a CAS against the latest
    /// verified publication. Identical replays are idempotent.
    pub async fn publish_compaction(
        &self,
        publication: &ProductionCompactionPublication,
    ) -> Result<ProductionCompactionReceipt, ProductionCompactionError> {
        self.verify_authority().await?;
        publication.validate()?;
        let payload = PublicationDto::from_publication(publication);
        let payload_bytes = serde_json::to_vec(&payload)
            .map_err(|error| ProductionCompactionError::Serialization(error.to_string()))?;
        let artifact_digest = Digest32::of_bytes(&payload_bytes);
        let event = DurableEvent {
            schema_version: 1,
            namespace: PRODUCTION_COMPACT_NAMESPACE.to_string(),
            lease_generation: self.generation(),
            payload,
            artifact_digest: artifact_digest.to_string(),
        };
        let event_json = serde_json::to_string(&event)
            .map_err(|error| ProductionCompactionError::Serialization(error.to_string()))?;
        if event_json.len() > MAX_EVENT_JSON_BYTES {
            return Err(ProductionCompactionError::Invalid(
                "publication exceeds compact journal row bound".to_string(),
            ));
        }

        let mut transaction = self
            .store()
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let current_lease = self
            .lease_handle()
            .verify_current_in_transaction(&mut transaction)
            .await
            .map_err(ProductionWriterError::Local)?;
        let rows = load_rows(
            &mut transaction,
            self.store().owner_agent_id().as_str(),
        )
        .await?;

        if let Some(latest) = rows.last() {
            let latest_publication = latest.event.payload.to_publication()?;
            let wanted_generation = latest_publication
                .checkpoint
                .generation
                .next()
                .map_err(|error| ProductionCompactionError::Invalid(error.to_string()))?;
            if publication.checkpoint.generation == latest_publication.checkpoint.generation {
                if publication == &latest_publication {
                    transaction
                        .commit()
                        .await
                        .map_err(crate::cognitive_store::unavailable)?;
                    return Ok(ProductionCompactionReceipt {
                        sequence: latest.sequence,
                        generation: publication.checkpoint.generation,
                        checkpoint_digest: publication.checkpoint.checkpoint_digest,
                        proof_digest: publication.proof.proof_digest,
                        artifact_digest,
                        replayed: true,
                    });
                }
                return Err(ProductionCompactionError::CasConflict(
                    "generation replay changed publication".to_string(),
                ));
            }
            if publication.checkpoint.generation != wanted_generation
                || publication.checkpoint.predecessor_digest
                    != Some(latest_publication.checkpoint.checkpoint_digest)
            {
                return Err(ProductionCompactionError::CasConflict(
                    "checkpoint generation/predecessor changed".to_string(),
                ));
            }
        } else if publication.checkpoint.generation.get() != 1
            || publication.checkpoint.predecessor_digest.is_some()
        {
            return Err(ProductionCompactionError::CasConflict(
                "first published checkpoint must be generation 1 without predecessor".to_string(),
            ));
        }

        let sequence = rows.last().map_or(1, |row| row.sequence + 1);
        let previous = rows
            .last()
            .map_or_else(empty_sha256, |row| row.event_sha256.clone());
        let event_sha256 = row_digest(
            self.store().owner_agent_id().as_str(),
            sequence,
            publication.checkpoint.generation.get(),
            &current_lease.fencing_token,
            &event_json,
            &previous,
        );
        let binding = binding_digest(
            &current_lease.lease_id,
            &current_lease.lease_sha256,
            &event_sha256,
        );
        let authority_epoch = current_lease.authority_epoch.ok_or_else(|| {
            ProductionCompactionError::Corrupt("lease missing authority epoch".to_string())
        })?;
        let owner_epoch = current_lease.owner_epoch.ok_or_else(|| {
            ProductionCompactionError::Corrupt("lease missing owner epoch".to_string())
        })?;
        sqlx::query(
            "INSERT INTO cognitive_compact_events (
                journal_id, owner_agent_id, sequence, generation, fencing_token,
                event_json, previous_sha256, event_sha256, recorded_at_unix_seconds,
                authority_epoch, owner_epoch, lease_id, lease_head_sha256,
                compact_previous_sha256, compact_event_binding_sha256
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(PRODUCTION_COMPACT_JOURNAL_ID)
        .bind(self.store().owner_agent_id().as_str())
        .bind(to_i64(sequence, "sequence")?)
        .bind(to_i64(
            publication.checkpoint.generation.get(),
            "checkpoint generation",
        )?)
        .bind(&current_lease.fencing_token)
        .bind(&event_json)
        .bind(previous.as_str())
        .bind(event_sha256.as_str())
        .bind(to_i64(now_unix_seconds()?, "recorded time")?)
        .bind(to_i64(authority_epoch, "authority epoch")?)
        .bind(to_i64(owner_epoch, "owner epoch")?)
        .bind(&current_lease.lease_id)
        .bind(current_lease.lease_sha256.as_str())
        .bind(previous.as_str())
        .bind(binding.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(crate::cognitive_store::unavailable)?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(ProductionCompactionReceipt {
            sequence,
            generation: publication.checkpoint.generation,
            checkpoint_digest: publication.checkpoint.checkpoint_digest,
            proof_digest: publication.proof.proof_digest,
            artifact_digest,
            replayed: false,
        })
    }

    /// Reload and revalidate the latest durable canonical checkpoint.
    ///
    /// Reopening a new ProductionDurableWriter after process restart exercises
    /// this same full-chain verification path.
    pub async fn load_current_compaction(
        &self,
    ) -> Result<Option<ProductionCompactionPublication>, ProductionCompactionError> {
        self.verify_authority().await?;
        let mut transaction = self
            .store()
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        self.lease_handle()
            .verify_current_in_transaction(&mut transaction)
            .await
            .map_err(ProductionWriterError::Local)?;
        let rows = load_rows(
            &mut transaction,
            self.store().owner_agent_id().as_str(),
        )
        .await?;
        let result = rows
            .last()
            .map(|row| row.event.payload.to_publication())
            .transpose()?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(result)
    }
}

impl PublicationDto {
    fn from_publication(value: &ProductionCompactionPublication) -> Self {
        Self {
            checkpoint: CheckpointDto::from_checkpoint(&value.checkpoint),
            proof: ProofDto::from_proof(&value.proof),
            policy_digest: value.policy_digest.to_string(),
            candidate_digest: value.candidate_digest.to_string(),
            retained_bytes: value.retained_bytes,
            retained_tokens: value.retained_tokens,
            omitted_bytes: value.omitted_bytes,
            omitted_tokens: value.omitted_tokens,
        }
    }

    fn to_publication(
        &self,
    ) -> Result<ProductionCompactionPublication, ProductionCompactionError> {
        let value = ProductionCompactionPublication {
            checkpoint: self.checkpoint.to_checkpoint()?,
            proof: self.proof.to_proof()?,
            policy_digest: parse_digest(&self.policy_digest)?,
            candidate_digest: parse_digest(&self.candidate_digest)?,
            retained_bytes: self.retained_bytes,
            retained_tokens: self.retained_tokens,
            omitted_bytes: self.omitted_bytes,
            omitted_tokens: self.omitted_tokens,
        };
        value.validate()?;
        Ok(value)
    }
}

impl SnapshotDto {
    fn from_snapshot(value: &CognitiveSnapshotKeyV1) -> Self {
        let vector = &value.vector;
        Self {
            scope_id: vector.scope_id.to_string(),
            purpose_id: vector.purpose_id.to_string(),
            memory_ledger_frontier: vector.memory_ledger_frontier,
            knowledge_fact_frontier: vector.knowledge_fact_frontier,
            tombstone_frontier: vector.tombstone_frontier,
            source_ledger_frontier: vector.source_ledger_frontier,
            knowledge_graph_generation: vector.knowledge_graph_generation.get(),
            compact_checkpoint_generation: vector.compact_checkpoint_generation.get(),
            prompt_registry_revision: vector.prompt_registry_revision.get(),
            retrieval_profile_digest: vector.retrieval_profile_digest.to_string(),
            encoder_preprocessor_digest: vector.encoder_preprocessor_digest.to_string(),
            authority_epoch: vector.authority_epoch,
            model_digest: vector.model_digest.to_string(),
            tokenizer_digest: vector.tokenizer_digest.to_string(),
            template_digest: vector.template_digest.to_string(),
            tool_schema_digest: vector.tool_schema_digest.to_string(),
            vector_digest: value.vector_digest.to_string(),
        }
    }

    fn to_snapshot(&self) -> Result<CognitiveSnapshotKeyV1, ProductionCompactionError> {
        let snapshot = CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
            scope_id: parse_id(&self.scope_id)?,
            purpose_id: parse_id(&self.purpose_id)?,
            memory_ledger_frontier: self.memory_ledger_frontier,
            knowledge_fact_frontier: self.knowledge_fact_frontier,
            tombstone_frontier: self.tombstone_frontier,
            source_ledger_frontier: self.source_ledger_frontier,
            knowledge_graph_generation: parse_generation(self.knowledge_graph_generation)?,
            compact_checkpoint_generation: parse_generation(
                self.compact_checkpoint_generation,
            )?,
            prompt_registry_revision: Revision::new(self.prompt_registry_revision)
                .map_err(identity_error)?,
            retrieval_profile_digest: parse_digest(&self.retrieval_profile_digest)?,
            encoder_preprocessor_digest: parse_digest(
                &self.encoder_preprocessor_digest,
            )?,
            authority_epoch: self.authority_epoch,
            model_digest: parse_digest(&self.model_digest)?,
            tokenizer_digest: parse_digest(&self.tokenizer_digest)?,
            template_digest: parse_digest(&self.template_digest)?,
            tool_schema_digest: parse_digest(&self.tool_schema_digest)?,
        })
        .map_err(contract_error)?;
        if snapshot.vector_digest != parse_digest(&self.vector_digest)? {
            return Err(ProductionCompactionError::Corrupt(
                "snapshot vector digest mismatch".to_string(),
            ));
        }
        Ok(snapshot)
    }
}

impl CheckpointDto {
    fn from_checkpoint(value: &CompactCheckpointV1) -> Self {
        Self {
            checkpoint_id: value.checkpoint_id.to_string(),
            generation: value.generation.get(),
            source_snapshot: SnapshotDto::from_snapshot(&value.source_snapshot),
            support_manifest_digest: value.support_manifest_digest.to_string(),
            algorithm_digest: value.algorithm_digest.to_string(),
            payload_digest: value.payload_digest.to_string(),
            omitted_information_digest: value.omitted_information_digest.to_string(),
            tombstone_cutoff: value.tombstone_cutoff,
            predecessor_digest: value.predecessor_digest.map(|digest| digest.to_string()),
            compatibility_digest: value.compatibility_digest.to_string(),
            checkpoint_digest: value.checkpoint_digest.to_string(),
        }
    }

    fn to_checkpoint(&self) -> Result<CompactCheckpointV1, ProductionCompactionError> {
        let value = CompactCheckpointV1 {
            checkpoint_id: parse_id(&self.checkpoint_id)?,
            generation: parse_generation(self.generation)?,
            source_snapshot: self.source_snapshot.to_snapshot()?,
            support_manifest_digest: parse_digest(&self.support_manifest_digest)?,
            algorithm_digest: parse_digest(&self.algorithm_digest)?,
            payload_digest: parse_digest(&self.payload_digest)?,
            omitted_information_digest: parse_digest(&self.omitted_information_digest)?,
            tombstone_cutoff: self.tombstone_cutoff,
            predecessor_digest: self
                .predecessor_digest
                .as_deref()
                .map(parse_digest)
                .transpose()?,
            compatibility_digest: parse_digest(&self.compatibility_digest)?,
            checkpoint_digest: parse_digest(&self.checkpoint_digest)?,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.validate().map_err(contract_error)?;
        Ok(value)
    }
}

impl ProofDto {
    fn from_proof(value: &CompactionProofV2) -> Self {
        Self {
            evaluator_id: value.evaluator_id.to_string(),
            evaluation_artifact_digest: value.evaluation_artifact_digest.to_string(),
            evaluator_implementation_digest: value.evaluator_implementation_digest.to_string(),
            attestation_digest: value.attestation_digest.to_string(),
            signature_digest: value.signature_digest.to_string(),
            checkpoint_digest: value.checkpoint_digest.to_string(),
            retained_query_suite_digest: value.retained_query_suite_digest.to_string(),
            reconstruction_obligation_digest: value
                .reconstruction_obligation_digest
                .to_string(),
            contradiction_holdout_digest: value.contradiction_holdout_digest.to_string(),
            deletion_cutoff: value.deletion_cutoff,
            source_count: value.source_count,
            retained_count: value.retained_count,
            proof_digest: value.proof_digest.to_string(),
        }
    }

    fn to_proof(&self) -> Result<CompactionProofV2, ProductionCompactionError> {
        let value = CompactionProofV2 {
            evaluator_id: parse_id(&self.evaluator_id)?,
            evaluation_artifact_digest: parse_digest(&self.evaluation_artifact_digest)?,
            evaluator_implementation_digest: parse_digest(
                &self.evaluator_implementation_digest,
            )?,
            attestation_digest: parse_digest(&self.attestation_digest)?,
            signature_digest: parse_digest(&self.signature_digest)?,
            checkpoint_digest: parse_digest(&self.checkpoint_digest)?,
            retained_query_suite_digest: parse_digest(
                &self.retained_query_suite_digest,
            )?,
            reconstruction_obligation_digest: parse_digest(
                &self.reconstruction_obligation_digest,
            )?,
            contradiction_holdout_digest: parse_digest(
                &self.contradiction_holdout_digest,
            )?,
            deletion_cutoff: self.deletion_cutoff,
            source_count: self.source_count,
            retained_count: self.retained_count,
            proof_digest: parse_digest(&self.proof_digest)?,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.validate().map_err(contract_error)?;
        Ok(value)
    }
}

async fn load_rows(
    transaction: &mut Transaction<'_, Sqlite>,
    owner: &str,
) -> Result<Vec<VerifiedRow>, ProductionCompactionError> {
    let rows = sqlx::query(
        "SELECT sequence, owner_agent_id, generation, fencing_token, event_json,
                previous_sha256, event_sha256, authority_epoch, owner_epoch,
                lease_id, lease_head_sha256, compact_previous_sha256,
                compact_event_binding_sha256
         FROM cognitive_compact_events
         WHERE journal_id = ? ORDER BY sequence LIMIT ?",
    )
    .bind(PRODUCTION_COMPACT_JOURNAL_ID)
    .bind(i64::try_from(MAX_EVENTS + 1).unwrap_or(i64::MAX))
    .fetch_all(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if rows.len() > MAX_EVENTS {
        return Err(ProductionCompactionError::Corrupt(
            "compact journal exceeds bounds".to_string(),
        ));
    }

    let mut verified: Vec<VerifiedRow> = Vec::with_capacity(rows.len());
    let mut previous = empty_sha256();
    for (index, row) in rows.iter().enumerate() {
        let sequence = u64::try_from(
            row.try_get::<i64, _>("sequence")
                .map_err(sql_error)?,
        )
        .map_err(|_| ProductionCompactionError::Corrupt("negative sequence".to_string()))?;
        if sequence != index as u64 + 1 {
            return Err(ProductionCompactionError::Corrupt(
                "non-contiguous compact sequence".to_string(),
            ));
        }
        let stored_owner: String = row.try_get("owner_agent_id").map_err(sql_error)?;
        if stored_owner != owner {
            return Err(ProductionCompactionError::Corrupt(
                "compact owner mismatch".to_string(),
            ));
        }
        let generation = u64::try_from(
            row.try_get::<i64, _>("generation")
                .map_err(sql_error)?,
        )
        .map_err(|_| ProductionCompactionError::Corrupt("negative generation".to_string()))?;
        let fencing: String = row.try_get("fencing_token").map_err(sql_error)?;
        let event_json: String = row.try_get("event_json").map_err(sql_error)?;
        if event_json.len() > MAX_EVENT_JSON_BYTES {
            return Err(ProductionCompactionError::Corrupt(
                "compact event json exceeds bounds".to_string(),
            ));
        }
        let stored_previous: String = row.try_get("previous_sha256").map_err(sql_error)?;
        let explicit_previous: Option<String> =
            row.try_get("compact_previous_sha256").map_err(sql_error)?;
        if stored_previous != previous.as_str()
            || explicit_previous.as_deref() != Some(previous.as_str())
        {
            return Err(ProductionCompactionError::Corrupt(
                "compact predecessor chain mismatch".to_string(),
            ));
        }
        let observed = row_digest(
            owner,
            sequence,
            generation,
            &fencing,
            &event_json,
            &previous,
        );
        let stored_event: String = row.try_get("event_sha256").map_err(sql_error)?;
        if stored_event != observed.as_str() {
            return Err(ProductionCompactionError::Corrupt(
                "compact event digest mismatch".to_string(),
            ));
        }

        let authority_epoch: Option<i64> =
            row.try_get("authority_epoch").map_err(sql_error)?;
        let owner_epoch: Option<i64> = row.try_get("owner_epoch").map_err(sql_error)?;
        if authority_epoch.unwrap_or(0) <= 0 || owner_epoch.unwrap_or(0) <= 0 {
            return Err(ProductionCompactionError::Corrupt(
                "compact row missing epoch binding".to_string(),
            ));
        }
        let lease_id: Option<String> = row.try_get("lease_id").map_err(sql_error)?;
        let lease_head: Option<String> =
            row.try_get("lease_head_sha256").map_err(sql_error)?;
        let binding: Option<String> = row
            .try_get("compact_event_binding_sha256")
            .map_err(sql_error)?;
        let (lease_id, lease_head, binding) = match (lease_id, lease_head, binding) {
            (Some(lease_id), Some(lease_head), Some(binding)) => {
                (lease_id, lease_head, binding)
            }
            _ => {
                return Err(ProductionCompactionError::Corrupt(
                    "compact row missing lease binding".to_string(),
                ));
            }
        };
        let lease_head = Sha256Digest::parse(lease_head).map_err(|_| {
            ProductionCompactionError::Corrupt("invalid lease head digest".to_string())
        })?;
        if binding != binding_digest(&lease_id, &lease_head, &observed).as_str() {
            return Err(ProductionCompactionError::Corrupt(
                "compact lease/event binding mismatch".to_string(),
            ));
        }

        let event: DurableEvent = serde_json::from_str(&event_json).map_err(|error| {
            ProductionCompactionError::Corrupt(format!(
                "invalid compact event json: {error}"
            ))
        })?;
        if event.schema_version != 1 || event.namespace != PRODUCTION_COMPACT_NAMESPACE {
            return Err(ProductionCompactionError::Corrupt(
                "compact event namespace/version mismatch".to_string(),
            ));
        }
        let artifact = serde_json::to_vec(&event.payload)
            .map_err(|error| ProductionCompactionError::Serialization(error.to_string()))?;
        if event.artifact_digest != Digest32::of_bytes(&artifact).to_string() {
            return Err(ProductionCompactionError::Corrupt(
                "compact artifact digest mismatch".to_string(),
            ));
        }
        let publication = event.payload.to_publication()?;
        if publication.checkpoint.generation.get() != generation {
            return Err(ProductionCompactionError::Corrupt(
                "row/checkpoint generation mismatch".to_string(),
            ));
        }
        if let Some(prior) = verified.last() {
            let prior_publication = prior.event.payload.to_publication()?;
            let expected_generation = prior_publication
                .checkpoint
                .generation
                .next()
                .map_err(|error| ProductionCompactionError::Corrupt(error.to_string()))?;
            if publication.checkpoint.generation != expected_generation
                || publication.checkpoint.predecessor_digest
                    != Some(prior_publication.checkpoint.checkpoint_digest)
            {
                return Err(ProductionCompactionError::Corrupt(
                    "published checkpoint lineage mismatch".to_string(),
                ));
            }
        } else if generation != 1 || publication.checkpoint.predecessor_digest.is_some() {
            return Err(ProductionCompactionError::Corrupt(
                "invalid first checkpoint lineage".to_string(),
            ));
        }

        previous = observed.clone();
        verified.push(VerifiedRow {
            sequence,
            event,
            event_sha256: observed,
        });
    }
    Ok(verified)
}

fn row_digest(
    owner: &str,
    sequence: u64,
    generation: u64,
    fencing: &str,
    event_json: &str,
    previous: &Sha256Digest,
) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(
        &mut hasher,
        b"hepta:compact-engine:production-row:v1",
    );
    frame_part(&mut hasher, owner.as_bytes());
    frame_part(&mut hasher, &sequence.to_be_bytes());
    frame_part(&mut hasher, &generation.to_be_bytes());
    frame_part(&mut hasher, fencing.as_bytes());
    frame_part(&mut hasher, event_json.as_bytes());
    frame_part(&mut hasher, previous.as_str().as_bytes());
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn binding_digest(
    lease_id: &str,
    lease_head: &Sha256Digest,
    event: &Sha256Digest,
) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(
        &mut hasher,
        b"hepta:compact-engine:production-lease-binding:v1",
    );
    frame_part(&mut hasher, lease_id.as_bytes());
    frame_part(&mut hasher, lease_head.as_str().as_bytes());
    frame_part(&mut hasher, event.as_str().as_bytes());
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn empty_sha256() -> Sha256Digest {
    Sha256Digest::for_bytes(&[])
}

fn now_unix_seconds() -> Result<u64, ProductionCompactionError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|error| {
            ProductionCompactionError::Invalid(format!(
                "system clock failed: {error}"
            ))
        })
}

fn parse_digest(value: &str) -> Result<Digest32, ProductionCompactionError> {
    Digest32::from_str(value).map_err(|_| {
        ProductionCompactionError::Corrupt("invalid compact digest".to_string())
    })
}

fn parse_id(value: &str) -> Result<StableId, ProductionCompactionError> {
    StableId::new(value.to_string()).map_err(identity_error)
}

fn parse_generation(value: u64) -> Result<Generation, ProductionCompactionError> {
    Generation::new(value).map_err(identity_error)
}

fn to_i64(value: u64, label: &str) -> Result<i64, ProductionCompactionError> {
    i64::try_from(value).map_err(|_| {
        ProductionCompactionError::Invalid(format!("{label} exceeds sqlite integer range"))
    })
}

fn identity_error(error: impl std::fmt::Display) -> ProductionCompactionError {
    ProductionCompactionError::Corrupt(error.to_string())
}

fn contract_error(error: impl std::fmt::Display) -> ProductionCompactionError {
    ProductionCompactionError::Corrupt(error.to_string())
}

fn sql_error(error: sqlx::Error) -> ProductionCompactionError {
    ProductionCompactionError::Corrupt(error.to_string())
}
