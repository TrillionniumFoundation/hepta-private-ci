//! Production composition for canonical compact.engine checkpoints.
//!
//! This is deliberately separate from the older `local_development_only`
//! compact hook/persistence seams. The `CognitiveStore` remains the sole
//! authoritative SQLite writer. Checkpoint generations are immutable, head
//! selection is one `BEGIN IMMEDIATE` transaction, and every reload revalidates
//! the payload, snapshot, canonical checkpoint and qualified proof digests.

use std::str::FromStr;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
use codex_hepta_cognitive_types::lane_c::CompactionProofV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_compact_engine::CompactionEvaluatorEvidenceV1;
use codex_hepta_compact_engine::CompactionInputRecordV2;
use codex_hepta_compact_engine::CompactionPolicyV2;
use codex_hepta_compact_engine::CompactionQualificationV2;
use codex_hepta_compact_engine::QualifiedCompactionCandidateV2;
use codex_hepta_compact_engine::QualifiedCompactionProofV2;
use codex_hepta_compact_engine::SemanticCompactionArtifactV1;
use codex_hepta_compact_engine::build_qualified_candidate;
use codex_hepta_compact_engine::prove_compaction;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;

use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityVerifier;
use crate::PRODUCTION_DURABLE_WRITER_JOURNAL_MODE;
use crate::PRODUCTION_DURABLE_WRITER_SYNCHRONOUS_FULL;

const CANONICAL_COMPACT_BUNDLE_SCHEMA_VERSION: u32 = 1;
const GENERATIONS_TABLE: &str = "canonical_compact_checkpoint_generations";
const HEADS_TABLE: &str = "canonical_compact_checkpoint_heads";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PublishFault {
    None,
    AfterGenerationInsert,
}

#[derive(Serialize, Deserialize)]
struct PersistedVectorV1 {
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

#[derive(Serialize, Deserialize)]
struct PersistedCheckpointV1 {
    checkpoint_id: String,
    generation: u64,
    source_snapshot: PersistedVectorV1,
    support_manifest_digest: String,
    algorithm_digest: String,
    payload_digest: String,
    omitted_information_digest: String,
    tombstone_cutoff: u64,
    predecessor_digest: Option<String>,
    compatibility_digest: String,
    checkpoint_digest: String,
}

#[derive(Serialize, Deserialize)]
struct PersistedSemanticArtifactV1 {
    artifact_id: String,
    producer_id: String,
    source_snapshot_digest: String,
    payload_digest: String,
    algorithm_digest: String,
    model_digest: String,
    tokenizer_digest: String,
    encoded_bytes: u64,
    token_count: u64,
    artifact_digest: String,
}

#[derive(Serialize, Deserialize)]
struct PersistedEvaluatorEvidenceV1 {
    evaluator_id: String,
    evaluator_implementation_digest: String,
    evaluation_artifact_digest: String,
    attestation_digest: String,
    attestation_key_digest: String,
    signature_digest: String,
    evidence_digest: String,
}

#[derive(Serialize, Deserialize)]
struct PersistedBaseProofV1 {
    checkpoint_digest: String,
    retained_query_suite_digest: String,
    reconstruction_obligation_digest: String,
    contradiction_holdout_digest: String,
    deletion_cutoff: u64,
    source_count: u64,
    retained_count: u64,
    proof_digest: String,
}

#[derive(Serialize, Deserialize)]
struct PersistedQualifiedProofV2 {
    base_proof: PersistedBaseProofV1,
    evaluator_evidence: PersistedEvaluatorEvidenceV1,
    proof_digest: String,
}

#[derive(Serialize, Deserialize)]
struct PersistedBundleV1 {
    schema_version: u32,
    checkpoint: PersistedCheckpointV1,
    semantic_artifact: PersistedSemanticArtifactV1,
    proof: PersistedQualifiedProofV2,
}

impl CognitiveStore {
    /// Production compact.engine consumer and writer.
    ///
    /// The caller supplies externally verified authority material plus a
    /// digest-bound semantic payload artifact. This method independently
    /// revalidates authority shape/durability, derives the predecessor from the
    /// owner store, constructs and proves the candidate, then atomically
    /// publishes the complete bundle. A race after predecessor observation is
    /// rejected by the publication CAS.
    #[allow(clippy::too_many_arguments)]
    pub async fn compact_and_publish_authorized<V>(
        &self,
        authority: &ProductionAuthorityLease,
        verifier: &V,
        source_snapshot: CognitiveSnapshotKeyV1,
        generation: Generation,
        policy: &CompactionPolicyV2,
        semantic_artifact: SemanticCompactionArtifactV1,
        semantic_payload: &[u8],
        inputs: Vec<CompactionInputRecordV2>,
        qualification: CompactionQualificationV2,
    ) -> Result<
        (
            QualifiedCompactionCandidateV2,
            QualifiedCompactionProofV2,
            bool,
        ),
        CognitiveStoreError,
    >
    where
        V: ProductionAuthorityVerifier + ?Sized,
    {
        let authority_fence_digest =
            self.verify_compact_publication_authority(authority, verifier).await?;
        let predecessor = self
            .current_canonical_compact_head(&source_snapshot.vector.scope_id)
            .await?
            .map(|(_, digest)| digest);
        let candidate = build_qualified_candidate(
            source_snapshot,
            generation,
            predecessor,
            policy,
            semantic_artifact,
            inputs,
        )
        .map_err(|error| invalid(format!("build canonical compact candidate: {error}")))?;
        let proof = prove_compaction(&candidate, qualification)
            .map_err(|error| invalid(format!("prove canonical compact candidate: {error}")))?;
        let published = self
            .publish_compaction_checkpoint_with_fault(
                authority,
                &authority_fence_digest,
                &candidate,
                &proof,
                semantic_payload,
                PublishFault::None,
            )
            .await?;
        Ok((candidate, proof, published))
    }

    /// Load and fully validate the currently selected compact checkpoint for a
    /// scope. `None` means the owner has never published a canonical generation
    /// for that scope; malformed or tampered durable state fails closed as
    /// `CognitiveStoreError::Corrupt`.
    pub async fn load_current_compact_checkpoint(
        &self,
        scope_id: &StableId,
    ) -> Result<
        Option<(
            CompactCheckpointV1,
            QualifiedCompactionProofV2,
            SemanticCompactionArtifactV1,
            Vec<u8>,
        )>,
        CognitiveStoreError,
    > {
        verify_checkpoint_schema(&self.pool).await?;
        let row = sqlx::query(
            "SELECT h.generation AS head_generation,
                    h.checkpoint_digest AS head_checkpoint_digest,
                    g.bundle_json,
                    g.payload,
                    g.payload_digest,
                    g.proof_digest,
                    g.semantic_artifact_digest
             FROM canonical_compact_checkpoint_heads h
             JOIN canonical_compact_checkpoint_generations g
               ON g.scope_id = h.scope_id
              AND g.generation = h.generation
              AND g.checkpoint_digest = h.checkpoint_digest
             WHERE h.scope_id = ?",
        )
        .bind(scope_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(unavailable)?;
        let Some(row) = row else {
            return Ok(None);
        };

        let head_generation = decode_positive_u64(row.try_get::<i64, _>("head_generation")?,
            "head generation")?;
        let head_checkpoint_digest: String = row.try_get("head_checkpoint_digest")?;
        let bundle_json: String = row.try_get("bundle_json")?;
        let payload: Vec<u8> = row.try_get("payload")?;
        let payload_digest_column: String = row.try_get("payload_digest")?;
        let proof_digest_column: String = row.try_get("proof_digest")?;
        let semantic_digest_column: String = row.try_get("semantic_artifact_digest")?;

        let bundle: PersistedBundleV1 = serde_json::from_str(&bundle_json)
            .map_err(|error| corrupt(format!("compact bundle JSON: {error}")))?;
        if bundle.schema_version != CANONICAL_COMPACT_BUNDLE_SCHEMA_VERSION {
            return Err(corrupt("unsupported compact bundle schema"));
        }
        let checkpoint = bundle.checkpoint.into_checkpoint()?;
        let semantic_artifact = bundle.semantic_artifact.into_artifact()?;
        let proof = bundle.proof.into_proof()?;

        if checkpoint.source_snapshot.vector.scope_id != *scope_id {
            return Err(corrupt("checkpoint scope differs from selected head"));
        }
        if checkpoint.generation.get() != head_generation {
            return Err(corrupt("checkpoint generation differs from selected head"));
        }
        if checkpoint.checkpoint_digest.to_string() != head_checkpoint_digest {
            return Err(corrupt("checkpoint digest differs from selected head"));
        }
        if proof.base_proof.checkpoint_digest != checkpoint.checkpoint_digest {
            return Err(corrupt("proof points at a different checkpoint"));
        }
        if proof.proof_digest.to_string() != proof_digest_column {
            return Err(corrupt("qualified proof digest differs from durable column"));
        }
        if semantic_artifact.artifact_digest.to_string() != semantic_digest_column {
            return Err(corrupt("semantic artifact digest differs from durable column"));
        }
        if semantic_artifact.payload_digest != checkpoint.payload_digest {
            return Err(corrupt("semantic payload differs from checkpoint payload"));
        }
        if semantic_artifact.payload_digest.to_string() != payload_digest_column {
            return Err(corrupt("semantic payload digest differs from durable column"));
        }
        let actual_payload_digest = Digest32::of_bytes(&payload);
        if actual_payload_digest != semantic_artifact.payload_digest {
            return Err(corrupt("stored compact payload digest mismatch"));
        }
        let payload_len = u64::try_from(payload.len()).unwrap_or(u64::MAX);
        if payload_len != semantic_artifact.encoded_bytes {
            return Err(corrupt("stored compact payload byte count mismatch"));
        }

        checkpoint
            .validate()
            .map_err(|error| corrupt(format!("checkpoint contract: {error}")))?;
        semantic_artifact
            .validate()
            .map_err(|error| corrupt(format!("semantic artifact contract: {error}")))?;
        proof
            .validate()
            .map_err(|error| corrupt(format!("qualified proof contract: {error}")))?;
        Ok(Some((checkpoint, proof, semantic_artifact, payload)))
    }

    async fn current_canonical_compact_head(
        &self,
        scope_id: &StableId,
    ) -> Result<Option<(u64, Digest32)>, CognitiveStoreError> {
        verify_checkpoint_schema(&self.pool).await?;
        let row = sqlx::query(
            "SELECT generation, checkpoint_digest
             FROM canonical_compact_checkpoint_heads
             WHERE scope_id = ?",
        )
        .bind(scope_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(unavailable)?;
        let Some(row) = row else {
            return Ok(None);
        };
        let generation = decode_positive_u64(row.try_get::<i64, _>("generation")?, "head generation")?;
        let digest: String = row.try_get("checkpoint_digest")?;
        Ok(Some((generation, parse_digest(&digest, "head checkpoint digest")?)))
    }

    async fn verify_compact_publication_authority<V>(
        &self,
        authority: &ProductionAuthorityLease,
        verifier: &V,
    ) -> Result<String, CognitiveStoreError>
    where
        V: ProductionAuthorityVerifier + ?Sized,
    {
        verifier
            .verify(authority, self.owner_agent_id())
            .map_err(|error| CognitiveStoreError::AccessDenied(format!(
                "compact publication authority rejected: {error}"
            )))?;
        if &authority.agent_id != self.owner_agent_id() {
            return Err(CognitiveStoreError::AccessDenied(
                "compact publication authority belongs to another Agent".to_string(),
            ));
        }
        let now = now_unix_seconds()?;
        if authority.is_expired_at(now) {
            return Err(CognitiveStoreError::AccessDenied(format!(
                "compact publication authority expired at {}",
                authority.lease_expires_at_unix_seconds
            )));
        }
        let authority_fence_digest = authority
            .fencing_token_digest()
            .map_err(|error| CognitiveStoreError::AccessDenied(error.to_string()))?;
        verify_checkpoint_schema(&self.pool).await?;
        let journal_mode: String = sqlx::query_scalar("PRAGMA journal_mode")
            .fetch_one(&self.pool)
            .await
            .map_err(unavailable)?;
        let synchronous: i64 = sqlx::query_scalar("PRAGMA synchronous")
            .fetch_one(&self.pool)
            .await
            .map_err(unavailable)?;
        if !journal_mode.eq_ignore_ascii_case(PRODUCTION_DURABLE_WRITER_JOURNAL_MODE)
            || synchronous != PRODUCTION_DURABLE_WRITER_SYNCHRONOUS_FULL
        {
            return Err(CognitiveStoreError::Unavailable(format!(
                "compact publication requires WAL/FULL durability, observed {journal_mode}/{synchronous}"
            )));
        }
        Ok(authority_fence_digest.as_str().to_string())
    }

    async fn publish_compaction_checkpoint_with_fault(
        &self,
        authority: &ProductionAuthorityLease,
        authority_fence_digest: &str,
        candidate: &QualifiedCompactionCandidateV2,
        proof: &QualifiedCompactionProofV2,
        semantic_payload: &[u8],
        fault: PublishFault,
    ) -> Result<bool, CognitiveStoreError> {
        candidate
            .validate()
            .map_err(|error| invalid(format!("candidate contract: {error}")))?;
        proof
            .validate()
            .map_err(|error| invalid(format!("proof contract: {error}")))?;
        if proof.base_proof.checkpoint_digest != candidate.checkpoint.checkpoint_digest {
            return Err(invalid("proof points at a different checkpoint"));
        }
        if candidate.semantic_artifact.payload_digest != Digest32::of_bytes(semantic_payload) {
            return Err(invalid("semantic payload bytes do not match artifact digest"));
        }
        if u64::try_from(semantic_payload.len()).unwrap_or(u64::MAX)
            != candidate.semantic_artifact.encoded_bytes
        {
            return Err(invalid("semantic payload byte count does not match artifact"));
        }
        let bundle = PersistedBundleV1::from_parts(
            &candidate.checkpoint,
            &candidate.semantic_artifact,
            proof,
        );
        let bundle_json = serde_json::to_string(&bundle)
            .map_err(|error| invalid(format!("serialize compact bundle: {error}")))?;
        let scope_id = candidate.source_snapshot.vector.scope_id.as_str();
        let generation = candidate.checkpoint.generation.get();
        let checkpoint_digest = candidate.checkpoint.checkpoint_digest.to_string();
        let predecessor_digest = candidate
            .checkpoint
            .predecessor_digest
            .map(|digest| digest.to_string());
        let now = now_unix_seconds()?;

        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = sqlx::query(
            "SELECT generation, checkpoint_digest
             FROM canonical_compact_checkpoint_heads
             WHERE scope_id = ?",
        )
        .bind(scope_id)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?;

        match current {
            None => {
                if generation != 1 || candidate.checkpoint.predecessor_digest.is_some() {
                    return Err(CognitiveStoreError::Conflict(
                        "initial compact publication must be generation 1 without a predecessor"
                            .to_string(),
                    ));
                }
            }
            Some(row) => {
                let current_generation = decode_positive_u64(
                    row.try_get::<i64, _>("generation")?,
                    "current compact generation",
                )?;
                let current_digest: String = row.try_get("checkpoint_digest")?;
                if generation == current_generation && checkpoint_digest == current_digest {
                    let existing = sqlx::query(
                        "SELECT bundle_json, payload
                         FROM canonical_compact_checkpoint_generations
                         WHERE scope_id = ? AND generation = ? AND checkpoint_digest = ?",
                    )
                    .bind(scope_id)
                    .bind(to_i64(generation, "generation")?)
                    .bind(&checkpoint_digest)
                    .fetch_one(&mut *transaction)
                    .await
                    .map_err(unavailable)?;
                    let existing_bundle: String = existing.try_get("bundle_json")?;
                    let existing_payload: Vec<u8> = existing.try_get("payload")?;
                    if existing_bundle == bundle_json && existing_payload == semantic_payload {
                        transaction.commit().await.map_err(unavailable)?;
                        return Ok(false);
                    }
                    return Err(CognitiveStoreError::Conflict(
                        "checkpoint digest replay changed proof, artifact, or payload".to_string(),
                    ));
                }
                let expected_generation = current_generation
                    .checked_add(1)
                    .ok_or_else(|| CognitiveStoreError::Conflict(
                        "compact generation overflow".to_string(),
                    ))?;
                if generation != expected_generation {
                    return Err(CognitiveStoreError::Conflict(format!(
                        "compact generation CAS expected {expected_generation}, found {generation}"
                    )));
                }
                let expected_predecessor = parse_digest(&current_digest, "current checkpoint digest")?;
                if candidate.checkpoint.predecessor_digest != Some(expected_predecessor) {
                    return Err(CognitiveStoreError::Conflict(
                        "compact predecessor does not match selected head".to_string(),
                    ));
                }
            }
        }

        sqlx::query(
            "INSERT INTO canonical_compact_checkpoint_generations (
                 scope_id, generation, checkpoint_digest, predecessor_digest,
                 payload_digest, proof_digest, semantic_artifact_digest,
                 bundle_json, payload, owner_agent_id, grant_digest,
                 authority_fence_digest, authority_epoch, owner_epoch,
                 created_at_unix_seconds
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(scope_id)
        .bind(to_i64(generation, "generation")?)
        .bind(&checkpoint_digest)
        .bind(predecessor_digest.as_deref())
        .bind(candidate.semantic_artifact.payload_digest.to_string())
        .bind(proof.proof_digest.to_string())
        .bind(candidate.semantic_artifact.artifact_digest.to_string())
        .bind(&bundle_json)
        .bind(semantic_payload)
        .bind(self.owner_agent_id().as_str())
        .bind(authority.grant_digest.as_str())
        .bind(authority_fence_digest)
        .bind(to_i64(authority.authority_epoch, "authority epoch")?)
        .bind(to_i64(authority.owner_epoch, "owner epoch")?)
        .bind(to_i64(now, "publication time")?)
        .execute(&mut *transaction)
        .await
        .map_err(classify_publish_error)?;

        if fault == PublishFault::AfterGenerationInsert {
            return Err(CognitiveStoreError::Unavailable(
                "injected compact publication fault after generation insert".to_string(),
            ));
        }

        let affected = if generation == 1 {
            sqlx::query(
                "INSERT INTO canonical_compact_checkpoint_heads (
                     scope_id, generation, checkpoint_digest, updated_at_unix_seconds
                 ) VALUES (?, ?, ?, ?)",
            )
            .bind(scope_id)
            .bind(to_i64(generation, "generation")?)
            .bind(&checkpoint_digest)
            .bind(to_i64(now, "publication time")?)
            .execute(&mut *transaction)
            .await
            .map_err(classify_publish_error)?
            .rows_affected()
        } else {
            let predecessor = candidate
                .checkpoint
                .predecessor_digest
                .ok_or_else(|| CognitiveStoreError::Conflict(
                    "non-initial compact publication is missing predecessor".to_string(),
                ))?;
            sqlx::query(
                "UPDATE canonical_compact_checkpoint_heads
                    SET generation = ?, checkpoint_digest = ?, updated_at_unix_seconds = ?
                  WHERE scope_id = ? AND generation = ? AND checkpoint_digest = ?",
            )
            .bind(to_i64(generation, "generation")?)
            .bind(&checkpoint_digest)
            .bind(to_i64(now, "publication time")?)
            .bind(scope_id)
            .bind(to_i64(generation - 1, "previous generation")?)
            .bind(predecessor.to_string())
            .execute(&mut *transaction)
            .await
            .map_err(classify_publish_error)?
            .rows_affected()
        };
        if affected != 1 {
            return Err(CognitiveStoreError::Conflict(
                "compact head CAS lost publication race".to_string(),
            ));
        }
        transaction.commit().await.map_err(unavailable)?;
        Ok(true)
    }
}

impl PersistedBundleV1 {
    fn from_parts(
        checkpoint: &CompactCheckpointV1,
        semantic_artifact: &SemanticCompactionArtifactV1,
        proof: &QualifiedCompactionProofV2,
    ) -> Self {
        Self {
            schema_version: CANONICAL_COMPACT_BUNDLE_SCHEMA_VERSION,
            checkpoint: PersistedCheckpointV1::from_checkpoint(checkpoint),
            semantic_artifact: PersistedSemanticArtifactV1::from_artifact(semantic_artifact),
            proof: PersistedQualifiedProofV2::from_proof(proof),
        }
    }
}

impl PersistedVectorV1 {
    fn from_snapshot(snapshot: &CognitiveSnapshotKeyV1) -> Self {
        let vector = &snapshot.vector;
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
            vector_digest: snapshot.vector_digest.to_string(),
        }
    }

    fn into_snapshot(self) -> Result<CognitiveSnapshotKeyV1, CognitiveStoreError> {
        let stored_vector_digest = parse_digest(&self.vector_digest, "vector digest")?;
        let snapshot = CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
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
            prompt_registry_revision: parse_revision(
                self.prompt_registry_revision,
                "prompt registry revision",
            )?,
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
        })
        .map_err(|error| corrupt(format!("source snapshot contract: {error}")))?;
        if snapshot.vector_digest != stored_vector_digest {
            return Err(corrupt("stored source snapshot digest mismatch"));
        }
        Ok(snapshot)
    }
}

impl PersistedCheckpointV1 {
    fn from_checkpoint(checkpoint: &CompactCheckpointV1) -> Self {
        Self {
            checkpoint_id: checkpoint.checkpoint_id.to_string(),
            generation: checkpoint.generation.get(),
            source_snapshot: PersistedVectorV1::from_snapshot(&checkpoint.source_snapshot),
            support_manifest_digest: checkpoint.support_manifest_digest.to_string(),
            algorithm_digest: checkpoint.algorithm_digest.to_string(),
            payload_digest: checkpoint.payload_digest.to_string(),
            omitted_information_digest: checkpoint.omitted_information_digest.to_string(),
            tombstone_cutoff: checkpoint.tombstone_cutoff,
            predecessor_digest: checkpoint.predecessor_digest.map(|digest| digest.to_string()),
            compatibility_digest: checkpoint.compatibility_digest.to_string(),
            checkpoint_digest: checkpoint.checkpoint_digest.to_string(),
        }
    }

    fn into_checkpoint(self) -> Result<CompactCheckpointV1, CognitiveStoreError> {
        let stored_digest = parse_digest(&self.checkpoint_digest, "checkpoint digest")?;
        let checkpoint = CompactCheckpointV1 {
            checkpoint_id: parse_id(&self.checkpoint_id, "checkpoint id")?,
            generation: parse_generation(self.generation, "checkpoint generation")?,
            source_snapshot: self.source_snapshot.into_snapshot()?,
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
            compatibility_digest: parse_digest(
                &self.compatibility_digest,
                "compatibility digest",
            )?,
            checkpoint_digest: stored_digest,
            authority: AuthorityPosture::DENY_ALL,
        };
        checkpoint
            .validate()
            .map_err(|error| corrupt(format!("checkpoint contract: {error}")))?;
        Ok(checkpoint)
    }
}

impl PersistedSemanticArtifactV1 {
    fn from_artifact(artifact: &SemanticCompactionArtifactV1) -> Self {
        Self {
            artifact_id: artifact.artifact_id.to_string(),
            producer_id: artifact.producer_id.to_string(),
            source_snapshot_digest: artifact.source_snapshot_digest.to_string(),
            payload_digest: artifact.payload_digest.to_string(),
            algorithm_digest: artifact.algorithm_digest.to_string(),
            model_digest: artifact.model_digest.to_string(),
            tokenizer_digest: artifact.tokenizer_digest.to_string(),
            encoded_bytes: artifact.encoded_bytes,
            token_count: artifact.token_count,
            artifact_digest: artifact.artifact_digest.to_string(),
        }
    }

    fn into_artifact(self) -> Result<SemanticCompactionArtifactV1, CognitiveStoreError> {
        let stored_digest = parse_digest(&self.artifact_digest, "semantic artifact digest")?;
        let artifact = SemanticCompactionArtifactV1::new(
            parse_id(&self.artifact_id, "semantic artifact id")?,
            parse_id(&self.producer_id, "semantic producer id")?,
            parse_digest(&self.source_snapshot_digest, "semantic snapshot digest")?,
            parse_digest(&self.payload_digest, "semantic payload digest")?,
            parse_digest(&self.algorithm_digest, "semantic algorithm digest")?,
            parse_digest(&self.model_digest, "semantic model digest")?,
            parse_digest(&self.tokenizer_digest, "semantic tokenizer digest")?,
            self.encoded_bytes,
            self.token_count,
        )
        .map_err(|error| corrupt(format!("semantic artifact contract: {error}")))?;
        if artifact.artifact_digest != stored_digest {
            return Err(corrupt("stored semantic artifact digest mismatch"));
        }
        Ok(artifact)
    }
}

impl PersistedEvaluatorEvidenceV1 {
    fn from_evidence(evidence: &CompactionEvaluatorEvidenceV1) -> Self {
        Self {
            evaluator_id: evidence.evaluator_id.to_string(),
            evaluator_implementation_digest: evidence.evaluator_implementation_digest.to_string(),
            evaluation_artifact_digest: evidence.evaluation_artifact_digest.to_string(),
            attestation_digest: evidence.attestation_digest.to_string(),
            attestation_key_digest: evidence.attestation_key_digest.to_string(),
            signature_digest: evidence.signature_digest.to_string(),
            evidence_digest: evidence.evidence_digest.to_string(),
        }
    }

    fn into_evidence(self) -> Result<CompactionEvaluatorEvidenceV1, CognitiveStoreError> {
        let evidence = CompactionEvaluatorEvidenceV1 {
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
            attestation_key_digest: parse_digest(
                &self.attestation_key_digest,
                "attestation key digest",
            )?,
            signature_digest: parse_digest(&self.signature_digest, "signature digest")?,
            evidence_digest: parse_digest(&self.evidence_digest, "evaluator evidence digest")?,
        };
        evidence
            .validate()
            .map_err(|error| corrupt(format!("evaluator evidence contract: {error}")))?;
        Ok(evidence)
    }
}

impl PersistedBaseProofV1 {
    fn from_proof(proof: &CompactionProofV1) -> Self {
        Self {
            checkpoint_digest: proof.checkpoint_digest.to_string(),
            retained_query_suite_digest: proof.retained_query_suite_digest.to_string(),
            reconstruction_obligation_digest: proof.reconstruction_obligation_digest.to_string(),
            contradiction_holdout_digest: proof.contradiction_holdout_digest.to_string(),
            deletion_cutoff: proof.deletion_cutoff,
            source_count: proof.source_count,
            retained_count: proof.retained_count,
            proof_digest: proof.proof_digest.to_string(),
        }
    }

    fn into_proof(self) -> Result<CompactionProofV1, CognitiveStoreError> {
        let proof = CompactionProofV1 {
            checkpoint_digest: parse_digest(&self.checkpoint_digest, "proof checkpoint digest")?,
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
            proof_digest: parse_digest(&self.proof_digest, "base proof digest")?,
            authority: AuthorityPosture::DENY_ALL,
        };
        proof
            .validate()
            .map_err(|error| corrupt(format!("base proof contract: {error}")))?;
        Ok(proof)
    }
}

impl PersistedQualifiedProofV2 {
    fn from_proof(proof: &QualifiedCompactionProofV2) -> Self {
        Self {
            base_proof: PersistedBaseProofV1::from_proof(&proof.base_proof),
            evaluator_evidence: PersistedEvaluatorEvidenceV1::from_evidence(
                &proof.evaluator_evidence,
            ),
            proof_digest: proof.proof_digest.to_string(),
        }
    }

    fn into_proof(self) -> Result<QualifiedCompactionProofV2, CognitiveStoreError> {
        let proof = QualifiedCompactionProofV2 {
            base_proof: self.base_proof.into_proof()?,
            evaluator_evidence: self.evaluator_evidence.into_evidence()?,
            proof_digest: parse_digest(&self.proof_digest, "qualified proof digest")?,
            authority: AuthorityPosture::DENY_ALL,
        };
        proof
            .validate()
            .map_err(|error| corrupt(format!("qualified proof contract: {error}")))?;
        Ok(proof)
    }
}

async fn verify_checkpoint_schema(pool: &sqlx::SqlitePool) -> Result<(), CognitiveStoreError> {
    for (name, kind) in [
        (GENERATIONS_TABLE, "table"),
        (HEADS_TABLE, "table"),
        ("canonical_compact_checkpoint_generations_no_update", "trigger"),
        ("canonical_compact_checkpoint_generations_no_delete", "trigger"),
        (
            "canonical_compact_checkpoint_generations_checkpoint_lookup",
            "index",
        ),
    ] {
        let found: Option<i64> = sqlx::query_scalar(
            "SELECT 1 FROM sqlite_master WHERE name = ? AND type = ? LIMIT 1",
        )
        .bind(name)
        .bind(kind)
        .fetch_optional(pool)
        .await
        .map_err(unavailable)?;
        if found.is_none() {
            return Err(corrupt(format!(
                "canonical compact schema missing {kind} {name}"
            )));
        }
    }
    Ok(())
}

fn parse_digest(value: &str, label: &str) -> Result<Digest32, CognitiveStoreError> {
    Digest32::from_str(value).map_err(|error| corrupt(format!("{label}: {error}")))
}

fn parse_id(value: &str, label: &str) -> Result<StableId, CognitiveStoreError> {
    StableId::new(value.to_string()).map_err(|error| corrupt(format!("{label}: {error}")))
}

fn parse_generation(value: u64, label: &str) -> Result<Generation, CognitiveStoreError> {
    Generation::new(value).map_err(|error| corrupt(format!("{label}: {error}")))
}

fn parse_revision(value: u64, label: &str) -> Result<Revision, CognitiveStoreError> {
    Revision::new(value).map_err(|error| corrupt(format!("{label}: {error}")))
}

fn decode_positive_u64(value: i64, label: &str) -> Result<u64, CognitiveStoreError> {
    let value = u64::try_from(value).map_err(|_| corrupt(format!("negative {label}")))?;
    if value == 0 {
        return Err(corrupt(format!("zero {label}")));
    }
    Ok(value)
}

fn to_i64(value: u64, label: &str) -> Result<i64, CognitiveStoreError> {
    i64::try_from(value).map_err(|_| invalid(format!("{label} exceeds SQLite integer range")))
}

fn now_unix_seconds() -> Result<u64, CognitiveStoreError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|error| CognitiveStoreError::Unavailable(format!("system clock: {error}")))
}

fn invalid(message: impl Into<String>) -> CognitiveStoreError {
    CognitiveStoreError::Invalid(message.into())
}

fn corrupt(message: impl Into<String>) -> CognitiveStoreError {
    CognitiveStoreError::Corrupt(message.into())
}

fn unavailable(error: impl std::fmt::Display) -> CognitiveStoreError {
    CognitiveStoreError::Unavailable(error.to_string())
}

fn classify_publish_error(error: sqlx::Error) -> CognitiveStoreError {
    let text = error.to_string();
    if text.contains("UNIQUE constraint failed")
        || text.contains("FOREIGN KEY constraint failed")
        || text.contains("constraint failed")
    {
        CognitiveStoreError::Conflict(text)
    } else {
        CognitiveStoreError::Unavailable(text)
    }
}

impl From<sqlx::Error> for CognitiveStoreError {
    fn from(error: sqlx::Error) -> Self {
        unavailable(error)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use codex_hepta_cognitive_types::MemoryKind;
    use codex_hepta_cognitive_types::MemoryRecord;
    use codex_hepta_cognitive_types::RecordState;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_contracts::Sha256Digest;
    use codex_hepta_compact_engine::QualifiedCompactionError;
    use tempfile::TempDir;

    use crate::ProductionAuthorityToken;
    use crate::cognitive_test_support::agent_id;
    use crate::cognitive_test_support::layout;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }

    fn revision(value: u64) -> Revision {
        Revision::new(value).expect("revision")
    }

    fn snapshot(checkpoint_generation: u64) -> CognitiveSnapshotKeyV1 {
        CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
            scope_id: StableId::new("scope:canonical-compact").expect("scope"),
            purpose_id: StableId::new("purpose:canonical-compact").expect("purpose"),
            memory_ledger_frontier: 20,
            knowledge_fact_frontier: 14,
            tombstone_frontier: 6,
            source_ledger_frontier: 21,
            knowledge_graph_generation: generation(3),
            compact_checkpoint_generation: generation(checkpoint_generation),
            prompt_registry_revision: revision(4),
            retrieval_profile_digest: digest("retrieval"),
            encoder_preprocessor_digest: digest("encoder"),
            authority_epoch: 8,
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tool-schema"),
        })
        .expect("snapshot")
    }

    fn record(index: usize) -> MemoryRecord {
        MemoryRecord {
            record_id: StableId::new(format!("memory:{index:05}")).expect("record id"),
            revision: revision(1),
            kind: MemoryKind::Fact,
            content_digest: digest(&format!("content:{index}")),
            predecessor_digest: None,
            citations: Vec::new(),
            state: RecordState::Live,
        }
    }

    fn inputs(count: usize) -> Vec<CompactionInputRecordV2> {
        (0..count)
            .map(|index| CompactionInputRecordV2 {
                record: record(index),
                retention_priority: u32::try_from(count - index).unwrap_or(u32::MAX),
                retention_reason_digest: digest(&format!("reason:{index}")),
            })
            .collect()
    }

    fn policy(snapshot: &CognitiveSnapshotKeyV1, maximum: u32) -> CompactionPolicyV2 {
        CompactionPolicyV2 {
            policy_id: StableId::new("policy:canonical-compact").expect("policy"),
            algorithm_digest: digest("selection-algorithm"),
            semantic_compaction_digest: digest("semantic-algorithm"),
            compatibility_digest: digest("compatibility"),
            tokenizer_digest: snapshot.vector.tokenizer_digest,
            maximum_retained_records: maximum,
            maximum_payload_bytes: 1_048_576,
            maximum_payload_tokens: 262_144,
            protected_record_ids: Vec::new(),
        }
    }

    fn artifact(
        snapshot: &CognitiveSnapshotKeyV1,
        payload: &[u8],
        suffix: &str,
    ) -> SemanticCompactionArtifactV1 {
        SemanticCompactionArtifactV1::new(
            StableId::new(format!("artifact:{suffix}")).expect("artifact id"),
            StableId::new("producer:canonical-compact").expect("producer"),
            snapshot.vector_digest,
            Digest32::of_bytes(payload),
            digest("semantic-algorithm"),
            snapshot.vector.model_digest,
            snapshot.vector.tokenizer_digest,
            u64::try_from(payload.len()).expect("payload len"),
            32,
        )
        .expect("artifact")
    }

    fn qualification(suffix: &str) -> CompactionQualificationV2 {
        CompactionQualificationV2 {
            evaluator_id: StableId::new("evaluator:canonical-compact").expect("evaluator"),
            evaluator_implementation_digest: digest("evaluator-implementation"),
            evaluation_artifact_digest: digest(&format!("evaluation:{suffix}")),
            attestation_digest: digest(&format!("attestation:{suffix}")),
            attestation_key_digest: digest("attestation-key"),
            signature_digest: digest(&format!("signature:{suffix}")),
            retained_query_suite_digest: digest("retained-queries"),
            reconstruction_obligation_digest: digest("reconstruction"),
            contradiction_holdout_digest: digest("contradiction-holdout"),
            retained_queries_passed: true,
            reconstruction_passed: true,
            contradictions_preserved: true,
            deletion_non_resurrection_passed: true,
        }
    }

    fn authority(owner: &AgentId) -> ProductionAuthorityLease {
        ProductionAuthorityLease::from_verified_parts(
            owner.clone(),
            Sha256Digest::for_bytes(b"compact-production-grant"),
            7,
            9,
            4_000_000_000,
            ProductionAuthorityToken::from_verified_bytes(b"compact-production-token".to_vec())
                .expect("token"),
        )
        .expect("authority")
    }

    async fn open_store(temp: &TempDir, owner: &AgentId) -> CognitiveStore {
        CognitiveStore::open(&layout(temp, owner))
            .await
            .expect("cognitive store")
    }

    async fn publish_generation(
        store: &CognitiveStore,
        owner: &AgentId,
        generation_value: u64,
        payload: &[u8],
        suffix: &str,
        record_count: usize,
    ) -> Result<
        (
            QualifiedCompactionCandidateV2,
            QualifiedCompactionProofV2,
            bool,
        ),
        CognitiveStoreError,
    > {
        let snapshot = snapshot(generation_value.max(1));
        let max_records = u32::try_from(record_count.max(1)).unwrap_or(u32::MAX);
        let authority = authority(owner);
        let verifier = |_authority: &ProductionAuthorityLease, _agent: &AgentId| Ok(());
        store
            .compact_and_publish_authorized(
                &authority,
                &verifier,
                snapshot.clone(),
                generation(generation_value),
                &policy(&snapshot, max_records),
                artifact(&snapshot, payload, suffix),
                payload,
                inputs(record_count),
                qualification(suffix),
            )
            .await
    }

    #[tokio::test]
    async fn authorized_publish_reload_and_restart_revalidate_complete_bundle() {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(240);
        let store = open_store(&temp, &owner).await;
        let payload = b"bounded canonical compact payload";
        let (candidate, proof, published) = publish_generation(
            &store,
            &owner,
            1,
            payload,
            "generation-1",
            4,
        )
        .await
        .expect("publish");
        assert!(published);

        let loaded = store
            .load_current_compact_checkpoint(&candidate.source_snapshot.vector.scope_id)
            .await
            .expect("load")
            .expect("head");
        assert_eq!(loaded.0, candidate.checkpoint);
        assert_eq!(loaded.1, proof);
        assert_eq!(loaded.2, candidate.semantic_artifact);
        assert_eq!(loaded.3, payload);

        drop(store);
        let reopened = open_store(&temp, &owner).await;
        let after_restart = reopened
            .load_current_compact_checkpoint(&candidate.source_snapshot.vector.scope_id)
            .await
            .expect("reload")
            .expect("head after restart");
        assert_eq!(after_restart, loaded);
    }

    #[tokio::test]
    async fn crash_before_head_cas_rolls_back_inserted_generation() {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(241);
        let store = open_store(&temp, &owner).await;
        let payload = b"faulted compact payload";
        let snapshot = snapshot(1);
        let candidate = build_qualified_candidate(
            snapshot.clone(),
            generation(1),
            None,
            &policy(&snapshot, 2),
            artifact(&snapshot, payload, "fault"),
            inputs(2),
        )
        .expect("candidate");
        let proof = prove_compaction(&candidate, qualification("fault")).expect("proof");
        let auth = authority(&owner);
        let fence = auth.fencing_token_digest().expect("fence");
        let error = store
            .publish_compaction_checkpoint_with_fault(
                &auth,
                fence.as_str(),
                &candidate,
                &proof,
                payload,
                PublishFault::AfterGenerationInsert,
            )
            .await
            .expect_err("injected failure");
        assert!(matches!(error, CognitiveStoreError::Unavailable(_)));
        assert!(store
            .load_current_compact_checkpoint(&snapshot.vector.scope_id)
            .await
            .expect("load after rollback")
            .is_none());
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM canonical_compact_checkpoint_generations",
        )
        .fetch_one(&store.pool)
        .await
        .expect("count");
        assert_eq!(count, 0);
    }

    #[tokio::test]
    async fn competing_generation_publications_have_one_cas_winner() {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(242);
        let store = open_store(&temp, &owner).await;
        publish_generation(&store, &owner, 1, b"generation one", "one", 2)
            .await
            .expect("generation one");

        let left = store.clone();
        let right = store.clone();
        let left_owner = owner.clone();
        let right_owner = owner.clone();
        let (left_result, right_result) = tokio::join!(
            async move {
                publish_generation(&left, &left_owner, 2, b"generation two left", "left", 2).await
            },
            async move {
                publish_generation(
                    &right,
                    &right_owner,
                    2,
                    b"generation two right",
                    "right",
                    2,
                )
                .await
            }
        );
        let successes = usize::from(left_result.is_ok()) + usize::from(right_result.is_ok());
        assert_eq!(successes, 1);
        let failures = [left_result.err(), right_result.err()]
            .into_iter()
            .flatten()
            .collect::<Vec<_>>();
        assert_eq!(failures.len(), 1);
        assert!(matches!(failures[0], CognitiveStoreError::Conflict(_)));
    }

    #[tokio::test]
    async fn corrupted_selected_head_fails_closed_on_reload() {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(243);
        let store = open_store(&temp, &owner).await;
        let (candidate, _, _) =
            publish_generation(&store, &owner, 1, b"corruption target", "corrupt", 2)
                .await
                .expect("publish");
        sqlx::query(
            "UPDATE canonical_compact_checkpoint_heads
             SET checkpoint_digest = ?
             WHERE scope_id = ?",
        )
        .bind(digest("tampered-head").to_string())
        .bind(candidate.source_snapshot.vector.scope_id.as_str())
        .execute(&store.pool)
        .await
        .expect_err("foreign key prevents dangling head corruption");

        sqlx::query("PRAGMA foreign_keys = OFF")
            .execute(&store.pool)
            .await
            .expect("disable foreign keys for corruption fixture");
        sqlx::query(
            "UPDATE canonical_compact_checkpoint_heads
             SET checkpoint_digest = ?
             WHERE scope_id = ?",
        )
        .bind(digest("tampered-head").to_string())
        .bind(candidate.source_snapshot.vector.scope_id.as_str())
        .execute(&store.pool)
        .await
        .expect("tamper head");
        let error = store
            .load_current_compact_checkpoint(&candidate.source_snapshot.vector.scope_id)
            .await
            .expect_err("corruption must fail closed");
        assert!(matches!(error, CognitiveStoreError::Corrupt(_)));
    }

    #[tokio::test]
    async fn large_batch_build_publish_and_reload_is_bounded() {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(244);
        let store = open_store(&temp, &owner).await;
        let payload = vec![b'x'; 32 * 1024];
        let (candidate, _, published) = publish_generation(
            &store,
            &owner,
            1,
            &payload,
            "large-batch",
            10_000,
        )
        .await
        .expect("large publish");
        assert!(published);
        assert_eq!(candidate.loss_report.source_current_heads, 10_000);
        let loaded = store
            .load_current_compact_checkpoint(&candidate.source_snapshot.vector.scope_id)
            .await
            .expect("load")
            .expect("head");
        assert_eq!(loaded.3.len(), payload.len());
    }

    #[test]
    fn legacy_resurrection_cannot_reappear_through_public_compact_api() {
        let first = MemoryRecord {
            record_id: StableId::new("memory:resurrection").expect("id"),
            revision: revision(1),
            kind: MemoryKind::Fact,
            content_digest: digest("live-1"),
            predecessor_digest: None,
            citations: Vec::new(),
            state: RecordState::Live,
        };
        let tombstone = MemoryRecord {
            record_id: first.record_id.clone(),
            revision: revision(2),
            kind: MemoryKind::Fact,
            content_digest: digest("deleted-2"),
            predecessor_digest: Some(first.record_digest()),
            citations: Vec::new(),
            state: RecordState::Tombstone,
        };
        let resurrected = MemoryRecord {
            record_id: first.record_id.clone(),
            revision: revision(3),
            kind: MemoryKind::Fact,
            content_digest: digest("live-3"),
            predecessor_digest: Some(tombstone.record_digest()),
            citations: Vec::new(),
            state: RecordState::Live,
        };
        let snapshot = snapshot(1);
        let error = build_qualified_candidate(
            snapshot.clone(),
            generation(1),
            None,
            &policy(&snapshot, 3),
            artifact(&snapshot, b"payload", "resurrection"),
            vec![
                CompactionInputRecordV2 {
                    record: first,
                    retention_priority: 1,
                    retention_reason_digest: digest("reason-1"),
                },
                CompactionInputRecordV2 {
                    record: tombstone,
                    retention_priority: 1,
                    retention_reason_digest: digest("reason-2"),
                },
                CompactionInputRecordV2 {
                    record: resurrected,
                    retention_priority: 1,
                    retention_reason_digest: digest("reason-3"),
                },
            ],
        )
        .expect_err("resurrection denied");
        assert_eq!(
            error,
            QualifiedCompactionError::ResurrectionDenied("memory:resurrection".to_string())
        );
    }
}
