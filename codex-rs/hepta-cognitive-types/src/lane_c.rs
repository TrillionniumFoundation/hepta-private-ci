//! Canonical, authority-free Lane C contracts.
//!
//! The types in this module close the cross-module identity gaps between the
//! cognitive store, snapshot reader, retrieval, federation, knowledge graph,
//! compaction, prompt registry and context delivery path. They deliberately
//! contain no runtime handle, credential, model client, writer or ambient
//! authority. Every receipt is digest-bound and carries `DENY_ALL`.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

pub const MAX_MEMORY_ADMISSION_SUPPORTS: usize = 64;
pub const MAX_FEDERATED_RESULT_ITEMS: usize = 512;
pub const MAX_CONTEXT_DELIVERY_SEGMENTS: usize = 4_096;

const GENERATION_VECTOR_DOMAIN: &[u8] = b"hepta.lane-c.generation-vector.v1";
const MEMORY_ADMISSION_EVIDENCE_DOMAIN: &[u8] = b"hepta.memory-admission.evidence.v1";
const MEMORY_ADMISSION_CANDIDATE_DOMAIN: &[u8] = b"hepta.memory-admission.candidate.v1";
const FEDERATED_RESULT_DOMAIN: &[u8] = b"hepta.memory-federation.result.v1";
const GRAPH_GENERATION_DOMAIN: &[u8] = b"hepta.knowledge-graph.generation.v1";
const PROJECTION_RECEIPT_DOMAIN: &[u8] = b"hepta.knowledge-graph.projection-receipt.v1";
const COMPACT_CHECKPOINT_DOMAIN: &[u8] = b"hepta.compact.checkpoint.v1";
const COMPACTION_PROOF_DOMAIN: &[u8] = b"hepta.compact.proof.v1";
const PROMPT_REGISTRY_SNAPSHOT_DOMAIN: &[u8] = b"hepta.prompt-registry.snapshot-receipt.v1";
const CONTEXT_DELIVERY_DOMAIN: &[u8] = b"hepta.context.delivery-observation.v1";

/// One coherent cut across every Lane C source and rebuildable generation.
///
/// A consumer must bind either this entire vector or an explicitly documented
/// subset. Combining individually valid values from different vectors is not a
/// coherent snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneCGenerationVectorV1 {
    pub scope_id: StableId,
    pub purpose_id: StableId,
    pub memory_ledger_frontier: u64,
    pub knowledge_fact_frontier: u64,
    pub tombstone_frontier: u64,
    pub source_ledger_frontier: u64,
    pub knowledge_graph_generation: Generation,
    pub compact_checkpoint_generation: Generation,
    pub prompt_registry_revision: Revision,
    pub retrieval_profile_digest: Digest32,
    pub encoder_preprocessor_digest: Digest32,
    pub authority_epoch: u64,
    pub model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub template_digest: Digest32,
    pub tool_schema_digest: Digest32,
}

impl LaneCGenerationVectorV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        if self.authority_epoch == 0 {
            return Err(LaneCContractError::ZeroValue("authority_epoch"));
        }
        for (name, digest) in [
            ("retrieval_profile", self.retrieval_profile_digest),
            ("encoder_preprocessor", self.encoder_preprocessor_digest),
            ("model", self.model_digest),
            ("tokenizer", self.tokenizer_digest),
            ("template", self.template_digest),
            ("tool_schema", self.tool_schema_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(GENERATION_VECTOR_DOMAIN);
        push_id(&mut bytes, &self.scope_id);
        push_id(&mut bytes, &self.purpose_id);
        for value in [
            self.memory_ledger_frontier,
            self.knowledge_fact_frontier,
            self.tombstone_frontier,
            self.source_ledger_frontier,
        ] {
            push_u64(&mut bytes, value);
        }
        push_generation(&mut bytes, self.knowledge_graph_generation);
        push_generation(&mut bytes, self.compact_checkpoint_generation);
        push_revision(&mut bytes, self.prompt_registry_revision);
        push_digest(&mut bytes, self.retrieval_profile_digest);
        push_digest(&mut bytes, self.encoder_preprocessor_digest);
        push_u64(&mut bytes, self.authority_epoch);
        push_digest(&mut bytes, self.model_digest);
        push_digest(&mut bytes, self.tokenizer_digest);
        push_digest(&mut bytes, self.template_digest);
        push_digest(&mut bytes, self.tool_schema_digest);
        Digest32::of_bytes(&bytes)
    }
}

/// Integrity key for one exact Lane C generation vector.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveSnapshotKeyV1 {
    pub vector: LaneCGenerationVectorV1,
    pub vector_digest: Digest32,
}

impl CognitiveSnapshotKeyV1 {
    pub fn new(vector: LaneCGenerationVectorV1) -> Result<Self, LaneCContractError> {
        vector.validate()?;
        let vector_digest = vector.digest();
        Ok(Self {
            vector,
            vector_digest,
        })
    }

    pub fn validate(&self) -> Result<(), LaneCContractError> {
        self.vector.validate()?;
        if self.vector_digest != self.vector.digest() {
            return Err(LaneCContractError::DigestMismatch("generation_vector"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryAdmissionKind {
    Observation,
    Inference,
    Preference,
    Procedure,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryVerificationState {
    Unverified,
    Verified,
    Contradicted,
    Revoked,
}

/// One source-bound, privacy-bound support item for a memory candidate.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryAdmissionEvidenceV1 {
    pub evidence_id: StableId,
    pub source_id: StableId,
    pub source_digest: Digest32,
    pub observation_digest: Digest32,
    pub privacy_scope_digest: Digest32,
    pub redaction_manifest_digest: Digest32,
    pub observed_at_unix_ms: u64,
}

impl MemoryAdmissionEvidenceV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        if self.observed_at_unix_ms == 0 {
            return Err(LaneCContractError::ZeroValue("observed_at_unix_ms"));
        }
        for (name, digest) in [
            ("source", self.source_digest),
            ("observation", self.observation_digest),
            ("privacy_scope", self.privacy_scope_digest),
            ("redaction_manifest", self.redaction_manifest_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(MEMORY_ADMISSION_EVIDENCE_DOMAIN);
        push_id(&mut bytes, &self.evidence_id);
        push_id(&mut bytes, &self.source_id);
        push_digest(&mut bytes, self.source_digest);
        push_digest(&mut bytes, self.observation_digest);
        push_digest(&mut bytes, self.privacy_scope_digest);
        push_digest(&mut bytes, self.redaction_manifest_digest);
        push_u64(&mut bytes, self.observed_at_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

/// Candidate-only memory record. It is not a fact and carries no writer grant.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryAdmissionCandidateV1 {
    pub candidate_id: StableId,
    pub proposed_by: StableId,
    pub kind: MemoryAdmissionKind,
    pub content_digest: Digest32,
    pub policy_digest: Digest32,
    pub verification: MemoryVerificationState,
    pub supports: Vec<MemoryAdmissionEvidenceV1>,
}

impl MemoryAdmissionCandidateV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        ensure_digest("memory_candidate_content", self.content_digest)?;
        ensure_digest("memory_admission_policy", self.policy_digest)?;
        if self.supports.is_empty() {
            return Err(LaneCContractError::EmptyCollection("supports"));
        }
        if self.supports.len() > MAX_MEMORY_ADMISSION_SUPPORTS {
            return Err(LaneCContractError::LimitExceeded {
                field: "supports",
                actual: self.supports.len(),
                maximum: MAX_MEMORY_ADMISSION_SUPPORTS,
            });
        }
        let mut evidence_ids = BTreeSet::new();
        for support in &self.supports {
            support.validate()?;
            if !evidence_ids.insert(support.evidence_id.clone()) {
                return Err(LaneCContractError::DuplicateIdentity("evidence_id"));
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut supports = self.supports.iter().collect::<Vec<_>>();
        supports.sort_by(|left, right| left.evidence_id.cmp(&right.evidence_id));
        let mut bytes = Vec::new();
        bytes.extend_from_slice(MEMORY_ADMISSION_CANDIDATE_DOMAIN);
        push_id(&mut bytes, &self.candidate_id);
        push_id(&mut bytes, &self.proposed_by);
        bytes.push(memory_admission_kind_code(self.kind));
        push_digest(&mut bytes, self.content_digest);
        push_digest(&mut bytes, self.policy_digest);
        bytes.push(memory_verification_state_code(self.verification));
        push_len(&mut bytes, supports.len());
        for support in supports {
            push_digest(&mut bytes, support.digest());
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryWriteIntentV1 {
    pub intent_id: StableId,
    pub candidate_digest: Digest32,
    pub expected_snapshot: CognitiveSnapshotKeyV1,
    pub writer_fence_digest: Digest32,
    pub authorization_digest: Digest32,
}

impl MemoryWriteIntentV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        self.expected_snapshot.validate()?;
        ensure_digest("candidate", self.candidate_digest)?;
        ensure_digest("writer_fence", self.writer_fence_digest)?;
        ensure_digest("authorization", self.authorization_digest)?;
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryWriteDisposition {
    Inserted,
    Unchanged,
    Rejected,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryWriteReceiptV1 {
    pub intent_id: StableId,
    pub record_id: StableId,
    pub record_digest: Digest32,
    pub committed_frontier: u64,
    pub snapshot_key: CognitiveSnapshotKeyV1,
    pub disposition: MemoryWriteDisposition,
    pub authority: AuthorityPosture,
}

impl MemoryWriteReceiptV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        if self.committed_frontier == 0 {
            return Err(LaneCContractError::ZeroValue("committed_frontier"));
        }
        ensure_digest("record", self.record_digest)?;
        self.snapshot_key.validate()?;
        ensure_deny_all(self.authority)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedMemoryQueryV1 {
    pub query_id: StableId,
    pub peer_id: StableId,
    pub principal_id: StableId,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub snapshot_key: CognitiveSnapshotKeyV1,
    pub query_digest: Digest32,
    pub maximum_results: u32,
    pub deadline_unix_ms: u64,
    pub lease_epoch: u64,
    pub nonce_digest: Digest32,
}

impl FederatedMemoryQueryV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        self.snapshot_key.validate()?;
        let maximum_results = usize::try_from(self.maximum_results).unwrap_or(usize::MAX);
        if maximum_results == 0 || maximum_results > MAX_FEDERATED_RESULT_ITEMS {
            return Err(LaneCContractError::LimitExceeded {
                field: "maximum_results",
                actual: maximum_results,
                maximum: MAX_FEDERATED_RESULT_ITEMS,
            });
        }
        if self.deadline_unix_ms == 0 {
            return Err(LaneCContractError::ZeroValue("deadline_unix_ms"));
        }
        if self.lease_epoch == 0 {
            return Err(LaneCContractError::ZeroValue("lease_epoch"));
        }
        for (name, digest) in [
            ("scope", self.scope_digest),
            ("purpose", self.purpose_digest),
            ("query", self.query_digest),
            ("nonce", self.nonce_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedEvidenceItemV1 {
    pub source_owner_id: StableId,
    pub record_id: StableId,
    pub record_revision: Revision,
    pub record_digest: Digest32,
    pub support_digest: Digest32,
    pub validity_digest: Digest32,
}

impl FederatedEvidenceItemV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        ensure_digest("federated_record", self.record_digest)?;
        ensure_digest("federated_support", self.support_digest)?;
        ensure_digest("federated_validity", self.validity_digest)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederatedCompletenessV1 {
    Complete,
    Partial,
    Empty,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederatedValidityV1 {
    Valid,
    Stale,
    Revoked,
    ScopeMismatch,
    ProducerMismatch,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedCoverageV1 {
    pub requested_peers: u32,
    pub completed_peers: u32,
    pub failed_peers: u32,
    pub truncated_items: u32,
}

impl FederatedCoverageV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        if self.requested_peers == 0 {
            return Err(LaneCContractError::ZeroValue("requested_peers"));
        }
        let observed = u64::from(self.completed_peers) + u64::from(self.failed_peers);
        if observed > u64::from(self.requested_peers) {
            return Err(LaneCContractError::InvalidState("federated_coverage"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedEvidenceResultV1 {
    pub query_id: StableId,
    pub peer_id: StableId,
    pub observed_snapshot: CognitiveSnapshotKeyV1,
    pub items: Vec<FederatedEvidenceItemV1>,
    pub coverage: FederatedCoverageV1,
    pub completeness: FederatedCompletenessV1,
    pub validity: FederatedValidityV1,
    pub expires_unix_ms: u64,
    pub result_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl FederatedEvidenceResultV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        self.observed_snapshot.validate()?;
        self.coverage.validate()?;
        if self.items.len() > MAX_FEDERATED_RESULT_ITEMS {
            return Err(LaneCContractError::LimitExceeded {
                field: "federated_items",
                actual: self.items.len(),
                maximum: MAX_FEDERATED_RESULT_ITEMS,
            });
        }
        if self.expires_unix_ms == 0 {
            return Err(LaneCContractError::ZeroValue("expires_unix_ms"));
        }
        if matches!(self.completeness, FederatedCompletenessV1::Empty) && !self.items.is_empty() {
            return Err(LaneCContractError::InvalidState("federated_empty_result"));
        }
        if matches!(self.completeness, FederatedCompletenessV1::Indeterminate)
            != matches!(self.validity, FederatedValidityV1::Indeterminate)
        {
            return Err(LaneCContractError::InvalidState(
                "federated_indeterminate_state",
            ));
        }
        let mut identities = BTreeSet::new();
        for item in &self.items {
            item.validate()?;
            let identity = (
                item.source_owner_id.clone(),
                item.record_id.clone(),
                item.record_revision,
            );
            if !identities.insert(identity) {
                return Err(LaneCContractError::DuplicateIdentity(
                    "federated_evidence_item",
                ));
            }
        }
        if self.result_digest != self.compute_result_digest() {
            return Err(LaneCContractError::DigestMismatch("federated_result"));
        }
        ensure_deny_all(self.authority)
    }

    #[must_use]
    pub fn compute_result_digest(&self) -> Digest32 {
        let mut items = self.items.iter().collect::<Vec<_>>();
        items.sort_by(|left, right| {
            left.source_owner_id
                .cmp(&right.source_owner_id)
                .then_with(|| left.record_id.cmp(&right.record_id))
                .then_with(|| left.record_revision.cmp(&right.record_revision))
        });
        let mut bytes = Vec::new();
        bytes.extend_from_slice(FEDERATED_RESULT_DOMAIN);
        push_id(&mut bytes, &self.query_id);
        push_id(&mut bytes, &self.peer_id);
        push_digest(&mut bytes, self.observed_snapshot.vector_digest);
        push_len(&mut bytes, items.len());
        for item in items {
            push_id(&mut bytes, &item.source_owner_id);
            push_id(&mut bytes, &item.record_id);
            push_revision(&mut bytes, item.record_revision);
            push_digest(&mut bytes, item.record_digest);
            push_digest(&mut bytes, item.support_digest);
            push_digest(&mut bytes, item.validity_digest);
        }
        push_u64(&mut bytes, u64::from(self.coverage.requested_peers));
        push_u64(&mut bytes, u64::from(self.coverage.completed_peers));
        push_u64(&mut bytes, u64::from(self.coverage.failed_peers));
        push_u64(&mut bytes, u64::from(self.coverage.truncated_items));
        bytes.push(federated_completeness_code(self.completeness));
        bytes.push(federated_validity_code(self.validity));
        push_u64(&mut bytes, self.expires_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeGraphGenerationV1 {
    pub generation: Generation,
    pub source_snapshot: CognitiveSnapshotKeyV1,
    pub source_manifest_digest: Digest32,
    pub graph_profile_digest: Digest32,
    pub node_count: u64,
    pub edge_count: u64,
    pub graph_digest: Digest32,
}

impl KnowledgeGraphGenerationV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        self.source_snapshot.validate()?;
        ensure_digest("graph_source_manifest", self.source_manifest_digest)?;
        ensure_digest("graph_profile", self.graph_profile_digest)?;
        ensure_digest("graph", self.graph_digest)
    }

    #[must_use]
    pub fn semantic_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(GRAPH_GENERATION_DOMAIN);
        push_generation(&mut bytes, self.generation);
        push_digest(&mut bytes, self.source_snapshot.vector_digest);
        push_digest(&mut bytes, self.source_manifest_digest);
        push_digest(&mut bytes, self.graph_profile_digest);
        push_u64(&mut bytes, self.node_count);
        push_u64(&mut bytes, self.edge_count);
        push_digest(&mut bytes, self.graph_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProjectionDispositionV1 {
    Published,
    Unchanged,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProjectionReceiptV1 {
    pub projection_id: StableId,
    pub predecessor_generation: Option<Generation>,
    pub generation: KnowledgeGraphGenerationV1,
    pub publication_digest: Digest32,
    pub disposition: ProjectionDispositionV1,
    pub authority: AuthorityPosture,
}

impl ProjectionReceiptV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        self.generation.validate()?;
        match self.predecessor_generation {
            None if self.generation.generation.get() != 1 => {
                return Err(LaneCContractError::InvalidState(
                    "initial_projection_generation",
                ));
            }
            Some(predecessor) if predecessor.next().ok() != Some(self.generation.generation) => {
                return Err(LaneCContractError::InvalidState(
                    "projection_predecessor_generation",
                ));
            }
            _ => {}
        }
        if self.publication_digest != self.compute_publication_digest() {
            return Err(LaneCContractError::DigestMismatch("projection_publication"));
        }
        ensure_deny_all(self.authority)
    }

    #[must_use]
    pub fn compute_publication_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(PROJECTION_RECEIPT_DOMAIN);
        push_id(&mut bytes, &self.projection_id);
        match self.predecessor_generation {
            Some(value) => {
                bytes.push(1);
                push_generation(&mut bytes, value);
            }
            None => bytes.push(0),
        }
        push_digest(&mut bytes, self.generation.semantic_digest());
        bytes.push(projection_disposition_code(self.disposition));
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactCheckpointV1 {
    pub checkpoint_id: StableId,
    pub generation: Generation,
    pub source_snapshot: CognitiveSnapshotKeyV1,
    pub support_manifest_digest: Digest32,
    pub algorithm_digest: Digest32,
    pub payload_digest: Digest32,
    pub omitted_information_digest: Digest32,
    pub tombstone_cutoff: u64,
    pub predecessor_digest: Option<Digest32>,
    pub compatibility_digest: Digest32,
    pub checkpoint_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CompactCheckpointV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        self.source_snapshot.validate()?;
        for (name, digest) in [
            ("compact_support_manifest", self.support_manifest_digest),
            ("compact_algorithm", self.algorithm_digest),
            ("compact_payload", self.payload_digest),
            (
                "compact_omitted_information",
                self.omitted_information_digest,
            ),
            ("compact_compatibility", self.compatibility_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        match (self.generation.get(), self.predecessor_digest) {
            (1, None) => {}
            (1, Some(_)) | (_, None) => {
                return Err(LaneCContractError::InvalidState(
                    "compact_predecessor_generation",
                ));
            }
            (_, Some(digest)) => ensure_digest("compact_predecessor", digest)?,
        }
        if self.checkpoint_digest != self.compute_checkpoint_digest() {
            return Err(LaneCContractError::DigestMismatch("compact_checkpoint"));
        }
        ensure_deny_all(self.authority)
    }

    #[must_use]
    pub fn compute_checkpoint_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(COMPACT_CHECKPOINT_DOMAIN);
        push_id(&mut bytes, &self.checkpoint_id);
        push_generation(&mut bytes, self.generation);
        push_digest(&mut bytes, self.source_snapshot.vector_digest);
        push_digest(&mut bytes, self.support_manifest_digest);
        push_digest(&mut bytes, self.algorithm_digest);
        push_digest(&mut bytes, self.payload_digest);
        push_digest(&mut bytes, self.omitted_information_digest);
        push_u64(&mut bytes, self.tombstone_cutoff);
        match self.predecessor_digest {
            Some(value) => {
                bytes.push(1);
                push_digest(&mut bytes, value);
            }
            None => bytes.push(0),
        }
        push_digest(&mut bytes, self.compatibility_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionProofV1 {
    pub checkpoint_digest: Digest32,
    pub retained_query_suite_digest: Digest32,
    pub reconstruction_obligation_digest: Digest32,
    pub contradiction_holdout_digest: Digest32,
    pub deletion_cutoff: u64,
    pub source_count: u64,
    pub retained_count: u64,
    pub proof_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CompactionProofV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        for (name, digest) in [
            ("proof_checkpoint", self.checkpoint_digest),
            ("retained_query_suite", self.retained_query_suite_digest),
            (
                "reconstruction_obligation",
                self.reconstruction_obligation_digest,
            ),
            ("contradiction_holdout", self.contradiction_holdout_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.retained_count > self.source_count {
            return Err(LaneCContractError::InvalidState(
                "compaction_retained_count",
            ));
        }
        if self.proof_digest != self.compute_proof_digest() {
            return Err(LaneCContractError::DigestMismatch("compaction_proof"));
        }
        ensure_deny_all(self.authority)
    }

    #[must_use]
    pub fn compute_proof_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(COMPACTION_PROOF_DOMAIN);
        push_digest(&mut bytes, self.checkpoint_digest);
        push_digest(&mut bytes, self.retained_query_suite_digest);
        push_digest(&mut bytes, self.reconstruction_obligation_digest);
        push_digest(&mut bytes, self.contradiction_holdout_digest);
        push_u64(&mut bytes, self.deletion_cutoff);
        push_u64(&mut bytes, self.source_count);
        push_u64(&mut bytes, self.retained_count);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistrySnapshotV1 {
    pub revision: Revision,
    pub registry_digest: Digest32,
    pub lifecycle_frontier: u64,
    pub revocation_frontier: u64,
    pub model_compatibility_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptRegistrySnapshotV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        if self.revocation_frontier > self.lifecycle_frontier {
            return Err(LaneCContractError::InvalidState(
                "prompt_revocation_frontier",
            ));
        }
        ensure_digest("prompt_registry", self.registry_digest)?;
        ensure_digest(
            "prompt_model_compatibility",
            self.model_compatibility_digest,
        )?;
        if self.snapshot_digest != self.compute_snapshot_digest() {
            return Err(LaneCContractError::DigestMismatch(
                "prompt_registry_snapshot",
            ));
        }
        ensure_deny_all(self.authority)
    }

    #[must_use]
    pub fn compute_snapshot_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(PROMPT_REGISTRY_SNAPSHOT_DOMAIN);
        push_revision(&mut bytes, self.revision);
        push_digest(&mut bytes, self.registry_digest);
        push_u64(&mut bytes, self.lifecycle_frontier);
        push_u64(&mut bytes, self.revocation_frontier);
        push_digest(&mut bytes, self.model_compatibility_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ContextDeliveryDispositionV1 {
    Delivered,
    Rejected,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextDeliveryObservationV1 {
    pub observation_id: StableId,
    pub compilation_receipt_digest: Digest32,
    pub attachment_digest: Digest32,
    pub delivered_payload_digest: Digest32,
    pub model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub template_digest: Digest32,
    pub tool_schema_digest: Digest32,
    pub delivered_segment_count: u32,
    pub terminal_observed: bool,
    pub disposition: ContextDeliveryDispositionV1,
    pub observed_unix_ms: u64,
    pub observation_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl ContextDeliveryObservationV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        let delivered_segment_count =
            usize::try_from(self.delivered_segment_count).unwrap_or(usize::MAX);
        if delivered_segment_count > MAX_CONTEXT_DELIVERY_SEGMENTS {
            return Err(LaneCContractError::LimitExceeded {
                field: "delivered_segment_count",
                actual: delivered_segment_count,
                maximum: MAX_CONTEXT_DELIVERY_SEGMENTS,
            });
        }
        if self.observed_unix_ms == 0 {
            return Err(LaneCContractError::ZeroValue("observed_unix_ms"));
        }
        if matches!(self.disposition, ContextDeliveryDispositionV1::Delivered)
            && !self.terminal_observed
        {
            return Err(LaneCContractError::InvalidState(
                "delivered_without_terminal_observation",
            ));
        }
        for (name, digest) in [
            ("compilation_receipt", self.compilation_receipt_digest),
            ("attachment", self.attachment_digest),
            ("delivered_payload", self.delivered_payload_digest),
            ("delivery_model", self.model_digest),
            ("delivery_tokenizer", self.tokenizer_digest),
            ("delivery_template", self.template_digest),
            ("delivery_tool_schema", self.tool_schema_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.observation_digest != self.compute_observation_digest() {
            return Err(LaneCContractError::DigestMismatch(
                "context_delivery_observation",
            ));
        }
        ensure_deny_all(self.authority)
    }

    #[must_use]
    pub fn compute_observation_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(CONTEXT_DELIVERY_DOMAIN);
        push_id(&mut bytes, &self.observation_id);
        push_digest(&mut bytes, self.compilation_receipt_digest);
        push_digest(&mut bytes, self.attachment_digest);
        push_digest(&mut bytes, self.delivered_payload_digest);
        push_digest(&mut bytes, self.model_digest);
        push_digest(&mut bytes, self.tokenizer_digest);
        push_digest(&mut bytes, self.template_digest);
        push_digest(&mut bytes, self.tool_schema_digest);
        push_u64(&mut bytes, u64::from(self.delivered_segment_count));
        bytes.push(u8::from(self.terminal_observed));
        bytes.push(context_delivery_disposition_code(self.disposition));
        push_u64(&mut bytes, self.observed_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LaneCContractError {
    EmptyCollection(&'static str),
    ZeroValue(&'static str),
    EmptyDigest(&'static str),
    DuplicateIdentity(&'static str),
    DigestMismatch(&'static str),
    InvalidState(&'static str),
    AuthorityGranted,
    LimitExceeded {
        field: &'static str,
        actual: usize,
        maximum: usize,
    },
}

impl fmt::Display for LaneCContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LaneCContractError {}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), LaneCContractError> {
    if digest.is_zero() {
        return Err(LaneCContractError::EmptyDigest(name));
    }
    Ok(())
}

fn ensure_deny_all(authority: AuthorityPosture) -> Result<(), LaneCContractError> {
    if authority.grants_any() {
        return Err(LaneCContractError::AuthorityGranted);
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_generation(bytes: &mut Vec<u8>, value: Generation) {
    push_u64(bytes, value.get());
}

fn push_revision(bytes: &mut Vec<u8>, value: Revision) {
    push_u64(bytes, value.get());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

const fn memory_admission_kind_code(value: MemoryAdmissionKind) -> u8 {
    match value {
        MemoryAdmissionKind::Observation => 0,
        MemoryAdmissionKind::Inference => 1,
        MemoryAdmissionKind::Preference => 2,
        MemoryAdmissionKind::Procedure => 3,
    }
}

const fn memory_verification_state_code(value: MemoryVerificationState) -> u8 {
    match value {
        MemoryVerificationState::Unverified => 0,
        MemoryVerificationState::Verified => 1,
        MemoryVerificationState::Contradicted => 2,
        MemoryVerificationState::Revoked => 3,
    }
}

const fn federated_completeness_code(value: FederatedCompletenessV1) -> u8 {
    match value {
        FederatedCompletenessV1::Complete => 0,
        FederatedCompletenessV1::Partial => 1,
        FederatedCompletenessV1::Empty => 2,
        FederatedCompletenessV1::Indeterminate => 3,
    }
}

const fn federated_validity_code(value: FederatedValidityV1) -> u8 {
    match value {
        FederatedValidityV1::Valid => 0,
        FederatedValidityV1::Stale => 1,
        FederatedValidityV1::Revoked => 2,
        FederatedValidityV1::ScopeMismatch => 3,
        FederatedValidityV1::ProducerMismatch => 4,
        FederatedValidityV1::Indeterminate => 5,
    }
}

const fn projection_disposition_code(value: ProjectionDispositionV1) -> u8 {
    match value {
        ProjectionDispositionV1::Published => 0,
        ProjectionDispositionV1::Unchanged => 1,
    }
}

const fn context_delivery_disposition_code(value: ContextDeliveryDispositionV1) -> u8 {
    match value {
        ContextDeliveryDispositionV1::Delivered => 0,
        ContextDeliveryDispositionV1::Rejected => 1,
        ContextDeliveryDispositionV1::Indeterminate => 2,
    }
}

#[cfg(test)]
#[path = "lane_c_tests.rs"]
mod tests;
