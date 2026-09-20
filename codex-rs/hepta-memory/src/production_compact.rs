//! Production publication/reload owner for compact.engine checkpoints.
//!
//! This module deliberately uses the existing cognitive_1.sqlite3 owner and
//! the already-migrated cognitive_compact_events append-only table. It does not
//! introduce a second memory database. Each publication is a BEGIN IMMEDIATE
//! CAS transaction whose durable row contains enough canonical information to
//! reconstruct and revalidate both CompactCheckpointV1 and CompactionProofV2.

use std::collections::BTreeSet;
use std::str::FromStr;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::CompactionProofV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_compact_engine::CompactCheckpointV1;
use codex_hepta_compact_engine::CompactionProofV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::CognitiveStore;

pub const PRODUCTION_COMPACT_OWNER_SCHEMA_VERSION: u32 = 1;
pub const PRODUCTION_COMPACT_OWNER_NAMESPACE: &str = "compact.engine.production.v1";
pub const PRODUCTION_COMPACT_OWNER_WRITER: bool = true;
pub const PRODUCTION_COMPACT_OWNER_EXTERNAL_EFFECTS: bool = false;
pub const PRODUCTION_COMPACT_OWNER_KG_WRITE_AUTHORITY: bool = false;

const MAX_PRODUCTION_COMPACT_EVENTS: usize = 4_096;
const PRODUCTION_EVENT_DOMAIN: &[u8] = b"hepta.production-compact.event.v1";
const PRODUCTION_RECEIPT_DOMAIN: &[u8] = b"hepta.production-compact.receipt.v1";
const EMPTY_EVENT_DOMAIN: &[u8] = b"hepta.production-compact.empty.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionCompactFenceV1 {
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: Generation,
    pub fencing_token_digest: Digest32,
}

impl ProductionCompactFenceV1 {
    pub fn new(
        authority_epoch: u64,
        owner_epoch: u64,
        generation: Generation,
        fencing_token_digest: Digest32,
    ) -> Result<Self, ProductionCompactError> {
        let value = Self {
            authority_epoch,
            owner_epoch,
            generation,
            fencing_token_digest,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ProductionCompactError> {
        if self.authority_epoch == 0 || self.owner_epoch == 0 {
            return Err(ProductionCompactError::Invalid(
                "authority/owner epoch must be non-zero".to_string(),
            ));
        }
        if self.fencing_token_digest.is_zero() {
            return Err(ProductionCompactError::Invalid(
                "fencing token digest must be non-zero".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductionCompactPublishDisposition {
    Published,
    Replay,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionCompactPublicationReceiptV1 {
    pub operation_id: StableId,
    pub sequence: u64,
    pub checkpoint_digest: Digest32,
    pub proof_digest: Digest32,
    pub event_digest: Digest32,
    pub disposition: ProductionCompactPublishDisposition,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl ProductionCompactPublicationReceiptV1 {
    fn new(
        operation_id: StableId,
        sequence: u64,
        checkpoint_digest: Digest32,
        proof_digest: Digest32,
        event_digest: Digest32,
        disposition: ProductionCompactPublishDisposition,
    ) -> Self {
        let mut value = Self {
            operation_id,
            sequence,
            checkpoint_digest,
            proof_digest,
            event_digest,
            disposition,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.receipt_digest = value.compute_digest();
        value
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(PRODUCTION_RECEIPT_DOMAIN);
        push_text(&mut bytes, self.operation_id.as_str());
        push_u64(&mut bytes, self.sequence);
        push_digest(&mut bytes, self.checkpoint_digest);
        push_digest(&mut bytes, self.proof_digest);
        push_digest(&mut bytes, self.event_digest);
        bytes.push(match self.disposition {
            ProductionCompactPublishDisposition::Published => 0,
            ProductionCompactPublishDisposition::Replay => 1,
        });
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionCompactReloadV1 {
    pub operation_id: StableId,
    pub sequence: u64,
    pub owner_epoch: u64,
    pub fencing_token_digest: Digest32,
    pub event_digest: Digest32,
    pub checkpoint: CompactCheckpointV1,
    pub proof: CompactionProofV2,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum ProductionCompactError {
    #[error("invalid production compact input: {0}")]
    Invalid(String),
    #[error("production compact CAS conflict: {0}")]
    Conflict(String),
    #[error("production compact journal is corrupt: {0}")]
    Corrupt(String),
    #[error("production compact store unavailable: {0}")]
    Unavailable(String),
    #[error("production compact serialization failed: {0}")]
    Serialization(String),
    #[error("production compact fault injected before commit")]
    FaultInjected,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
struct DurableCompactRecordV1 {
    checkpoint_id: String,
    generation: u64,
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
    source_vector_digest: String,
    support_manifest_digest: String,
    algorithm_digest: String,
    payload_digest: String,
    omitted_information_digest: String,
    checkpoint_tombstone_cutoff: u64,
    predecessor_digest: Option<String>,
    compatibility_digest: String,
    checkpoint_digest: String,

    retained_query_suite_digest: String,
    reconstruction_obligation_digest: String,
    contradiction_holdout_digest: String,
    proof_deletion_cutoff: u64,
    proof_source_count: u64,
    proof_retained_count: u64,
    base_proof_digest: String,

    candidate_digest: String,
    evaluator_id: String,
    evaluator_implementation_digest: String,
    evaluator_attestation_digest: String,
    evaluation_artifact_digest: String,
    evaluator_key_digest: String,
    qualification_digest: String,
    proof_digest: String,
}

impl DurableCompactRecordV1 {
    fn from_values(
        checkpoint: &CompactCheckpointV1,
        proof: &CompactionProofV2,
    ) -> Result<Self, ProductionCompactError> {
        checkpoint
            .validate()
            .map_err(|error| ProductionCompactError::Invalid(error.to_string()))?;
        proof
            .validate()
            .map_err(|error| ProductionCompactError::Invalid(error.to_string()))?;
        if proof.base_proof.checkpoint_digest != checkpoint.checkpoint_digest
            || proof.base_proof.deletion_cutoff != checkpoint.tombstone_cutoff
        {
            return Err(ProductionCompactError::Invalid(
                "proof is not bound to the supplied checkpoint".to_string(),
            ));
        }

        let vector = &checkpoint.source_snapshot.vector;
        Ok(Self {
            checkpoint_id: checkpoint.checkpoint_id.to_string(),
            generation: checkpoint.generation.get(),
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
            source_vector_digest: checkpoint.source_snapshot.vector_digest.to_string(),
            support_manifest_digest: checkpoint.support_manifest_digest.to_string(),
            algorithm_digest: checkpoint.algorithm_digest.to_string(),
            payload_digest: checkpoint.payload_digest.to_string(),
            omitted_information_digest: checkpoint.omitted_information_digest.to_string(),
            checkpoint_tombstone_cutoff: checkpoint.tombstone_cutoff,
            predecessor_digest: checkpoint.predecessor_digest.map(|digest| digest.to_string()),
            compatibility_digest: checkpoint.compatibility_digest.to_string(),
            checkpoint_digest: checkpoint.checkpoint_digest.to_string(),
            retained_query_suite_digest: proof
                .base_proof
                .retained_query_suite_digest
                .to_string(),
            reconstruction_obligation_digest: proof
                .base_proof
                .reconstruction_obligation_digest
                .to_string(),
            contradiction_holdout_digest: proof
                .base_proof
                .contradiction_holdout_digest
                .to_string(),
            proof_deletion_cutoff: proof.base_proof.deletion_cutoff,
            proof_source_count: proof.base_proof.source_count,
            proof_retained_count: proof.base_proof.retained_count,
            base_proof_digest: proof.base_proof.proof_digest.to_string(),
            candidate_digest: proof.candidate_digest.to_string(),
            evaluator_id: proof.evaluator_id.to_string(),
            evaluator_implementation_digest: proof
                .evaluator_implementation_digest
                .to_string(),
            evaluator_attestation_digest: proof.evaluator_attestation_digest.to_string(),
            evaluation_artifact_digest: proof.evaluation_artifact_digest.to_string(),
            evaluator_key_digest: proof.evaluator_key_digest.to_string(),
            qualification_digest: proof.qualification_digest.to_string(),
            proof_digest: proof.proof_digest.to_string(),
        })
    }

    fn to_values(
        &self,
    ) -> Result<(CompactCheckpointV1, CompactionProofV2), ProductionCompactError> {
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
                .map_err(|error| ProductionCompactError::Corrupt(error.to_string()))?,
            retrieval_profile_digest: parse_digest(
                &self.retrieval_profile_digest,
                "retrieval profile",
            )?,
            encoder_preprocessor_digest: parse_digest(
                &self.encoder_preprocessor_digest,
                "encoder preprocessor",
            )?,
            authority_epoch: self.authority_epoch,
            model_digest: parse_digest(&self.model_digest, "model")?,
            tokenizer_digest: parse_digest(&self.tokenizer_digest, "tokenizer")?,
            template_digest: parse_digest(&self.template_digest, "template")?,
            tool_schema_digest: parse_digest(&self.tool_schema_digest, "tool schema")?,
        };
        let snapshot = CognitiveSnapshotKeyV1::new(vector)
            .map_err(|error| ProductionCompactError::Corrupt(error.to_string()))?;
        if snapshot.vector_digest
            != parse_digest(&self.source_vector_digest, "source vector")?
        {
            return Err(ProductionCompactError::Corrupt(
                "source vector digest does not reconstruct".to_string(),
            ));
        }

        let checkpoint = CompactCheckpointV1 {
            checkpoint_id: parse_id(&self.checkpoint_id, "checkpoint id")?,
            generation: parse_generation(self.generation, "checkpoint generation")?,
            source_snapshot: snapshot,
            support_manifest_digest: parse_digest(
                &self.support_manifest_digest,
                "support manifest",
            )?,
            algorithm_digest: parse_digest(&self.algorithm_digest, "algorithm")?,
            payload_digest: parse_digest(&self.payload_digest, "payload")?,
            omitted_information_digest: parse_digest(
                &self.omitted_information_digest,
                "omitted information",
            )?,
            tombstone_cutoff: self.checkpoint_tombstone_cutoff,
            predecessor_digest: self
                .predecessor_digest
                .as_deref()
                .map(|value| parse_digest(value, "predecessor"))
                .transpose()?,
            compatibility_digest: parse_digest(
                &self.compatibility_digest,
                "compatibility",
            )?,
            checkpoint_digest: parse_digest(&self.checkpoint_digest, "checkpoint")?,
            authority: AuthorityPosture::DENY_ALL,
        };
        checkpoint
            .validate()
            .map_err(|error| ProductionCompactError::Corrupt(error.to_string()))?;

        let base_proof = CompactionProofV1 {
            checkpoint_digest: checkpoint.checkpoint_digest,
            retained_query_suite_digest: parse_digest(
                &self.retained_query_suite_digest,
                "retained query suite",
            )?,
            reconstruction_obligation_digest: parse_digest(
                &self.reconstruction_obligation_digest,
                "reconstruction obligation",
            )?,
            contradiction_holdout_digest: parse_digest(
                &self.contradiction_holdout_digest,
                "contradiction holdout",
            )?,
            deletion_cutoff: self.proof_deletion_cutoff,
            source_count: self.proof_source_count,
            retained_count: self.proof_retained_count,
            proof_digest: parse_digest(&self.base_proof_digest, "base proof")?,
            authority: AuthorityPosture::DENY_ALL,
        };
        let proof = CompactionProofV2 {
            base_proof,
            candidate_digest: parse_digest(&self.candidate_digest, "candidate")?,
            evaluator_id: parse_id(&self.evaluator_id, "evaluator id")?,
            evaluator_implementation_digest: parse_digest(
                &self.evaluator_implementation_digest,
                "evaluator implementation",
            )?,
            evaluator_attestation_digest: parse_digest(
                &self.evaluator_attestation_digest,
                "evaluator attestation",
            )?,
            evaluation_artifact_digest: parse_digest(
                &self.evaluation_artifact_digest,
                "evaluation artifact",
            )?,
            evaluator_key_digest: parse_digest(
                &self.evaluator_key_digest,
                "evaluator key",
            )?,
            qualification_digest: parse_digest(
                &self.qualification_digest,
                "qualification",
            )?,
            proof_digest: parse_digest(&self.proof_digest, "proof")?,
            authority: AuthorityPosture::DENY_ALL,
        };
        proof
            .validate()
            .map_err(|error| ProductionCompactError::Corrupt(error.to_string()))?;
        if proof.base_proof.checkpoint_digest != checkpoint.checkpoint_digest {
            return Err(ProductionCompactError::Corrupt(
                "reloaded proof/checkpoint binding differs".to_string(),
            ));
        }
        Ok((checkpoint, proof))
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
struct ProductionCompactEventPayloadV1 {
    schema_version: u32,
    namespace: String,
    sequence: u64,
    owner_agent_id: String,
    operation_id: String,
    owner_epoch: u64,
    fencing_token_digest: String,
    record: DurableCompactRecordV1,
    previous_event_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
struct ProductionCompactEventV1 {
    payload: ProductionCompactEventPayloadV1,
    event_digest: String,
}

impl ProductionCompactEventV1 {
    fn new(
        payload: ProductionCompactEventPayloadV1,
    ) -> Result<Self, ProductionCompactError> {
        let event_digest = event_digest(&payload)?.to_string();
        Ok(Self {
            payload,
            event_digest,
        })
    }

    fn validate(&self) -> Result<(), ProductionCompactError> {
        if self.payload.schema_version != PRODUCTION_COMPACT_OWNER_SCHEMA_VERSION
            || self.payload.namespace != PRODUCTION_COMPACT_OWNER_NAMESPACE
            || self.payload.sequence == 0
            || self.payload.owner_epoch == 0
        {
            return Err(ProductionCompactError::Corrupt(
                "production compact event identity is invalid".to_string(),
            ));
        }
        let expected = event_digest(&self.payload)?;
        if parse_digest(&self.event_digest, "event digest")? != expected {
            return Err(ProductionCompactError::Corrupt(
                "production compact event digest mismatch".to_string(),
            ));
        }
        let _ = self.payload.record.to_values()?;
        Ok(())
    }
}

impl CognitiveStore {
    pub async fn publish_production_compact_checkpoint(
        &self,
        operation_id: StableId,
        checkpoint: &CompactCheckpointV1,
        proof: &CompactionProofV2,
        fence: &ProductionCompactFenceV1,
    ) -> Result<ProductionCompactPublicationReceiptV1, ProductionCompactError> {
        self.publish_production_compact_internal(
            operation_id,
            checkpoint,
            proof,
            fence,
            false,
        )
        .await
    }

    pub async fn load_production_compact_checkpoint(
        &self,
        scope_id: &StableId,
    ) -> Result<Option<ProductionCompactReloadV1>, ProductionCompactError> {
        let journal_id = journal_id(scope_id)?;
        let mut transaction = self
            .pool
            .begin()
            .await
            .map_err(unavailable)?;
        let events = self
            .load_production_compact_events(&mut transaction, &journal_id)
            .await?;
        transaction.commit().await.map_err(unavailable)?;
        let Some(event) = events.last() else {
            return Ok(None);
        };
        let (checkpoint, proof) = event.payload.record.to_values()?;
        Ok(Some(ProductionCompactReloadV1 {
            operation_id: parse_id(&event.payload.operation_id, "operation id")?,
            sequence: event.payload.sequence,
            owner_epoch: event.payload.owner_epoch,
            fencing_token_digest: parse_digest(
                &event.payload.fencing_token_digest,
                "fencing token",
            )?,
            event_digest: parse_digest(&event.event_digest, "event digest")?,
            checkpoint,
            proof,
            authority: AuthorityPosture::DENY_ALL,
        }))
    }

    #[cfg(test)]
    pub(crate) async fn publish_production_compact_checkpoint_crash_before_commit(
        &self,
        operation_id: StableId,
        checkpoint: &CompactCheckpointV1,
        proof: &CompactionProofV2,
        fence: &ProductionCompactFenceV1,
    ) -> Result<ProductionCompactPublicationReceiptV1, ProductionCompactError> {
        self.publish_production_compact_internal(
            operation_id,
            checkpoint,
            proof,
            fence,
            true,
        )
        .await
    }

    async fn publish_production_compact_internal(
        &self,
        operation_id: StableId,
        checkpoint: &CompactCheckpointV1,
        proof: &CompactionProofV2,
        fence: &ProductionCompactFenceV1,
        crash_before_commit: bool,
    ) -> Result<ProductionCompactPublicationReceiptV1, ProductionCompactError> {
        fence.validate()?;
        checkpoint
            .validate()
            .map_err(|error| ProductionCompactError::Invalid(error.to_string()))?;
        proof
            .validate()
            .map_err(|error| ProductionCompactError::Invalid(error.to_string()))?;
        if proof.base_proof.checkpoint_digest != checkpoint.checkpoint_digest {
            return Err(ProductionCompactError::Invalid(
                "proof/checkpoint digest mismatch".to_string(),
            ));
        }
        if fence.authority_epoch != checkpoint.source_snapshot.vector.authority_epoch
            || fence.generation != checkpoint.generation
        {
            return Err(ProductionCompactError::Conflict(
                "publication fence does not match checkpoint generation/authority".to_string(),
            ));
        }
        let expected_from_snapshot = checkpoint
            .source_snapshot
            .vector
            .compact_checkpoint_generation
            .get()
            .checked_add(1)
            .ok_or_else(|| {
                ProductionCompactError::Invalid(
                    "compact checkpoint generation overflow".to_string(),
                )
            })?;
        if checkpoint.generation.get() != expected_from_snapshot {
            return Err(ProductionCompactError::Conflict(
                "checkpoint generation is not the successor of the source snapshot".to_string(),
            ));
        }

        let record = DurableCompactRecordV1::from_values(checkpoint, proof)?;
        let journal_id = journal_id(&checkpoint.source_snapshot.vector.scope_id)?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let events = self
            .load_production_compact_events(&mut transaction, &journal_id)
            .await?;

        for event in &events {
            if event.payload.operation_id == operation_id.as_str() {
                if event.payload.record == record
                    && event.payload.owner_epoch == fence.owner_epoch
                    && event.payload.fencing_token_digest
                        == fence.fencing_token_digest.to_string()
                {
                    transaction.commit().await.map_err(unavailable)?;
                    return Ok(ProductionCompactPublicationReceiptV1::new(
                        operation_id,
                        event.payload.sequence,
                        checkpoint.checkpoint_digest,
                        proof.proof_digest,
                        parse_digest(&event.event_digest, "event digest")?,
                        ProductionCompactPublishDisposition::Replay,
                    ));
                }
                return Err(ProductionCompactError::Conflict(
                    "operation id replay changed compact semantics".to_string(),
                ));
            }
        }

        match events.last() {
            Some(current) => {
                let current_checkpoint =
                    parse_digest(&current.payload.record.checkpoint_digest, "current checkpoint")?;
                let expected_generation = current
                    .payload
                    .record
                    .generation
                    .checked_add(1)
                    .ok_or_else(|| {
                        ProductionCompactError::Conflict(
                            "current checkpoint generation overflow".to_string(),
                        )
                    })?;
                if checkpoint.predecessor_digest != Some(current_checkpoint)
                    || checkpoint.generation.get() != expected_generation
                {
                    return Err(ProductionCompactError::Conflict(
                        "checkpoint predecessor/generation CAS failed".to_string(),
                    ));
                }
            }
            None => {
                if checkpoint.predecessor_digest.is_some() {
                    return Err(ProductionCompactError::Conflict(
                        "first production checkpoint must not name an unknown predecessor"
                            .to_string(),
                    ));
                }
            }
        }

        let sequence = u64::try_from(events.len())
            .map_err(|_| ProductionCompactError::Invalid("sequence overflow".to_string()))?
            .checked_add(1)
            .ok_or_else(|| ProductionCompactError::Invalid("sequence overflow".to_string()))?;
        let previous_event_digest = events
            .last()
            .map(|event| event.event_digest.clone())
            .unwrap_or_else(|| empty_event_digest().to_string());
        let event = ProductionCompactEventV1::new(ProductionCompactEventPayloadV1 {
            schema_version: PRODUCTION_COMPACT_OWNER_SCHEMA_VERSION,
            namespace: PRODUCTION_COMPACT_OWNER_NAMESPACE.to_string(),
            sequence,
            owner_agent_id: self.owner_agent_id().as_str().to_string(),
            operation_id: operation_id.to_string(),
            owner_epoch: fence.owner_epoch,
            fencing_token_digest: fence.fencing_token_digest.to_string(),
            record,
            previous_event_digest,
        })?;
        event.validate()?;
        self.insert_production_compact_event(
            &mut transaction,
            &journal_id,
            &event,
            fence,
        )
        .await?;

        if crash_before_commit {
            transaction.rollback().await.map_err(unavailable)?;
            return Err(ProductionCompactError::FaultInjected);
        }

        transaction.commit().await.map_err(unavailable)?;
        Ok(ProductionCompactPublicationReceiptV1::new(
            operation_id,
            sequence,
            checkpoint.checkpoint_digest,
            proof.proof_digest,
            parse_digest(&event.event_digest, "event digest")?,
            ProductionCompactPublishDisposition::Published,
        ))
    }

    async fn load_production_compact_events(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        journal_id: &str,
    ) -> Result<Vec<ProductionCompactEventV1>, ProductionCompactError> {
        let rows = sqlx::query(
            "SELECT sequence, owner_agent_id, authority_epoch, owner_epoch,
                    generation, fencing_token, event_json, previous_sha256,
                    event_sha256, lease_id, lease_head_sha256,
                    compact_previous_sha256, compact_event_binding_sha256
             FROM cognitive_compact_events
             WHERE journal_id = ?
             ORDER BY sequence",
        )
        .bind(journal_id)
        .fetch_all(&mut **transaction)
        .await
        .map_err(unavailable)?;

        if rows.len() > MAX_PRODUCTION_COMPACT_EVENTS {
            return Err(ProductionCompactError::Corrupt(
                "production compact journal exceeds reopen bound".to_string(),
            ));
        }

        let mut events = Vec::with_capacity(rows.len());
        let mut previous = empty_event_digest();
        let mut operation_ids = BTreeSet::new();
        let mut previous_checkpoint: Option<(u64, Digest32)> = None;

        for (index, row) in rows.into_iter().enumerate() {
            let sequence: i64 = row.try_get("sequence").map_err(unavailable)?;
            let owner_agent_id: String =
                row.try_get("owner_agent_id").map_err(unavailable)?;
            let authority_epoch: Option<i64> =
                row.try_get("authority_epoch").map_err(unavailable)?;
            let owner_epoch: Option<i64> =
                row.try_get("owner_epoch").map_err(unavailable)?;
            let generation: i64 = row.try_get("generation").map_err(unavailable)?;
            let fencing_token: String =
                row.try_get("fencing_token").map_err(unavailable)?;
            let event_json: String =
                row.try_get("event_json").map_err(unavailable)?;
            let previous_sha256: String =
                row.try_get("previous_sha256").map_err(unavailable)?;
            let event_sha256: String =
                row.try_get("event_sha256").map_err(unavailable)?;
            let lease_id: Option<String> = row.try_get("lease_id").map_err(unavailable)?;
            let lease_head_sha256: Option<String> =
                row.try_get("lease_head_sha256").map_err(unavailable)?;
            let compact_previous_sha256: Option<String> =
                row.try_get("compact_previous_sha256").map_err(unavailable)?;
            let compact_event_binding_sha256: Option<String> =
                row.try_get("compact_event_binding_sha256").map_err(unavailable)?;

            if lease_id.is_some()
                || lease_head_sha256.is_some()
                || compact_previous_sha256.is_some()
                || compact_event_binding_sha256.is_some()
            {
                return Err(ProductionCompactError::Corrupt(
                    "production compact row overlaps local lease-bound encoding".to_string(),
                ));
            }

            let event: ProductionCompactEventV1 = serde_json::from_str(&event_json)
                .map_err(|error| ProductionCompactError::Serialization(error.to_string()))?;
            event.validate()?;
            let expected_sequence = u64::try_from(index)
                .map_err(|_| ProductionCompactError::Corrupt("sequence overflow".to_string()))?
                .checked_add(1)
                .ok_or_else(|| {
                    ProductionCompactError::Corrupt("sequence overflow".to_string())
                })?;
            let row_authority_epoch = authority_epoch
                .and_then(|value| u64::try_from(value).ok())
                .ok_or_else(|| {
                    ProductionCompactError::Corrupt(
                        "production compact row has no authority epoch".to_string(),
                    )
                })?;
            let row_owner_epoch = owner_epoch
                .and_then(|value| u64::try_from(value).ok())
                .ok_or_else(|| {
                    ProductionCompactError::Corrupt(
                        "production compact row has no owner epoch".to_string(),
                    )
                })?;
            let row_generation = u64::try_from(generation).map_err(|_| {
                ProductionCompactError::Corrupt(
                    "production compact generation is invalid".to_string(),
                )
            })?;
            if u64::try_from(sequence).ok() != Some(expected_sequence)
                || event.payload.sequence != expected_sequence
                || owner_agent_id != self.owner_agent_id().as_str()
                || event.payload.owner_agent_id != owner_agent_id
                || event.payload.record.authority_epoch != row_authority_epoch
                || event.payload.owner_epoch != row_owner_epoch
                || event.payload.record.generation != row_generation
                || event.payload.fencing_token_digest != fencing_token
                || event.payload.previous_event_digest != previous.to_string()
                || previous_sha256 != previous.to_string()
                || event_sha256 != event.event_digest
            {
                return Err(ProductionCompactError::Corrupt(
                    "production compact row/event binding mismatch".to_string(),
                ));
            }
            if !operation_ids.insert(event.payload.operation_id.clone()) {
                return Err(ProductionCompactError::Corrupt(
                    "duplicate production compact operation id".to_string(),
                ));
            }

            let (checkpoint, proof) = event.payload.record.to_values()?;
            if proof.base_proof.checkpoint_digest != checkpoint.checkpoint_digest {
                return Err(ProductionCompactError::Corrupt(
                    "reloaded proof/checkpoint digest mismatch".to_string(),
                ));
            }
            match previous_checkpoint {
                Some((prior_generation, prior_digest)) => {
                    if checkpoint.generation.get()
                        != prior_generation.checked_add(1).ok_or_else(|| {
                            ProductionCompactError::Corrupt(
                                "checkpoint generation overflow".to_string(),
                            )
                        })?
                        || checkpoint.predecessor_digest != Some(prior_digest)
                    {
                        return Err(ProductionCompactError::Corrupt(
                            "production checkpoint lineage is not contiguous".to_string(),
                        ));
                    }
                }
                None => {
                    if checkpoint.predecessor_digest.is_some() {
                        return Err(ProductionCompactError::Corrupt(
                            "first production checkpoint names a predecessor".to_string(),
                        ));
                    }
                }
            }
            previous_checkpoint =
                Some((checkpoint.generation.get(), checkpoint.checkpoint_digest));
            previous = parse_digest(&event.event_digest, "event digest")?;
            events.push(event);
        }
        Ok(events)
    }

    async fn insert_production_compact_event(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        journal_id: &str,
        event: &ProductionCompactEventV1,
        fence: &ProductionCompactFenceV1,
    ) -> Result<(), ProductionCompactError> {
        let event_json = serde_json::to_string(event)
            .map_err(|error| ProductionCompactError::Serialization(error.to_string()))?;
        if event_json.len() > 65_536 {
            return Err(ProductionCompactError::Invalid(
                "production compact event exceeds SQLite event bound".to_string(),
            ));
        }
        let recorded_at_unix_seconds = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| ProductionCompactError::Unavailable(error.to_string()))?
            .as_secs();
        let recorded_at_unix_seconds = i64::try_from(recorded_at_unix_seconds)
            .map_err(|_| ProductionCompactError::Invalid("timestamp overflow".to_string()))?;

        sqlx::query(
            "INSERT INTO cognitive_compact_events (
                journal_id, owner_agent_id, sequence, generation, fencing_token,
                event_json, previous_sha256, event_sha256, recorded_at_unix_seconds,
                authority_epoch, owner_epoch
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(journal_id)
        .bind(self.owner_agent_id().as_str())
        .bind(i64::try_from(event.payload.sequence).map_err(|_| {
            ProductionCompactError::Invalid("sequence overflow".to_string())
        })?)
        .bind(i64::try_from(fence.generation.get()).map_err(|_| {
            ProductionCompactError::Invalid("generation overflow".to_string())
        })?)
        .bind(fence.fencing_token_digest.to_string())
        .bind(event_json)
        .bind(&event.payload.previous_event_digest)
        .bind(&event.event_digest)
        .bind(recorded_at_unix_seconds)
        .bind(i64::try_from(fence.authority_epoch).map_err(|_| {
            ProductionCompactError::Invalid("authority epoch overflow".to_string())
        })?)
        .bind(i64::try_from(fence.owner_epoch).map_err(|_| {
            ProductionCompactError::Invalid("owner epoch overflow".to_string())
        })?)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        Ok(())
    }
}

fn journal_id(scope_id: &StableId) -> Result<String, ProductionCompactError> {
    let value = format!("{PRODUCTION_COMPACT_OWNER_NAMESPACE}:{}", scope_id.as_str());
    if value.len() > 512 {
        return Err(ProductionCompactError::Invalid(
            "production compact journal id exceeds SQLite bound".to_string(),
        ));
    }
    Ok(value)
}

fn event_digest(
    payload: &ProductionCompactEventPayloadV1,
) -> Result<Digest32, ProductionCompactError> {
    let bytes = serde_json::to_vec(payload)
        .map_err(|error| ProductionCompactError::Serialization(error.to_string()))?;
    Ok(Digest32::of_parts(&[PRODUCTION_EVENT_DOMAIN, &bytes]))
}

fn empty_event_digest() -> Digest32 {
    Digest32::of_bytes(EMPTY_EVENT_DOMAIN)
}

fn parse_digest(
    value: &str,
    label: &str,
) -> Result<Digest32, ProductionCompactError> {
    Digest32::from_str(value).map_err(|error| {
        ProductionCompactError::Corrupt(format!("{label} digest: {error}"))
    })
}

fn parse_id(value: &str, label: &str) -> Result<StableId, ProductionCompactError> {
    StableId::new(value.to_string()).map_err(|error| {
        ProductionCompactError::Corrupt(format!("{label}: {error}"))
    })
}

fn parse_generation(
    value: u64,
    label: &str,
) -> Result<Generation, ProductionCompactError> {
    Generation::new(value).map_err(|error| {
        ProductionCompactError::Corrupt(format!("{label}: {error}"))
    })
}

fn unavailable(error: impl fmt::Display) -> ProductionCompactError {
    ProductionCompactError::Unavailable(error.to_string())
}

use std::fmt;

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    push_u64(bytes, u64::try_from(value.len()).unwrap_or(u64::MAX));
    bytes.extend_from_slice(value.as_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, digest: Digest32) {
    bytes.extend_from_slice(digest.as_array());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}
