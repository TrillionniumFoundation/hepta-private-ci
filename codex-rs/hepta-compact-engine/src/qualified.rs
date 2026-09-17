//! Loss-bounded, deletion-aware compaction qualification.
//!
//! Compaction never rewrites or deletes source facts. It normalizes one
//! coherent Lane C snapshot, rejects resurrection, selects bounded support,
//! binds a separately-produced semantic context artifact, records omissions,
//! and emits a canonical checkpoint plus an independently attributable proof.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
use codex_hepta_cognitive_types::lane_c::CompactionProofV1;
use codex_hepta_cognitive_types::lane_c::LaneCContractError;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub const MAX_QUALIFIED_COMPACTION_INPUTS: usize = 65_536;
pub const MAX_PROTECTED_COMPACTION_REFS: usize = 4_096;
pub const MAX_COMPACT_PAYLOAD_BYTES: u64 = 16 * 1024 * 1024;
pub const MAX_COMPACT_PAYLOAD_TOKENS: u64 = 1_048_576;

const POLICY_DOMAIN: &[u8] = b"hepta.compaction-policy.v2";
const CANDIDATE_DOMAIN: &[u8] = b"hepta.compaction-candidate.v2";
const SUPPORT_MANIFEST_DOMAIN: &[u8] = b"hepta.compaction-support-manifest.v2";
const RETENTION_MANIFEST_DOMAIN: &[u8] = b"hepta.compaction-retention-manifest.v1";
const OMITTED_DOMAIN: &[u8] = b"hepta.compaction-omitted.v2";
const LOSS_REPORT_DOMAIN: &[u8] = b"hepta.compaction-loss-report.v2";
const SEMANTIC_ARTIFACT_DOMAIN: &[u8] = b"hepta.compaction-semantic-artifact.v1";
const EVALUATOR_EVIDENCE_DOMAIN: &[u8] = b"hepta.compaction-evaluator-evidence.v1";
const QUALIFIED_PROOF_DOMAIN: &[u8] = b"hepta.compaction-qualified-proof.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionPolicyV2 {
    pub policy_id: StableId,
    /// Deterministic support-selection algorithm/version.
    pub algorithm_digest: Digest32,
    /// Semantic compressor/summarizer implementation that may produce payloads.
    pub semantic_compaction_digest: Digest32,
    pub compatibility_digest: Digest32,
    /// Tokenizer used for the final compact payload accounting.
    pub tokenizer_digest: Digest32,
    pub maximum_retained_records: u32,
    pub maximum_payload_bytes: u64,
    pub maximum_payload_tokens: u64,
    pub protected_record_ids: Vec<StableId>,
}

impl CompactionPolicyV2 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        for (name, digest) in [
            ("algorithm", self.algorithm_digest),
            ("semantic_compaction", self.semantic_compaction_digest),
            ("compatibility", self.compatibility_digest),
            ("tokenizer", self.tokenizer_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        let maximum = usize::try_from(self.maximum_retained_records).unwrap_or(usize::MAX);
        if maximum == 0 || maximum > MAX_QUALIFIED_COMPACTION_INPUTS {
            return Err(QualifiedCompactionError::InvalidRetentionLimit);
        }
        if self.maximum_payload_bytes == 0
            || self.maximum_payload_bytes > MAX_COMPACT_PAYLOAD_BYTES
        {
            return Err(QualifiedCompactionError::InvalidPayloadByteLimit);
        }
        if self.maximum_payload_tokens == 0
            || self.maximum_payload_tokens > MAX_COMPACT_PAYLOAD_TOKENS
        {
            return Err(QualifiedCompactionError::InvalidPayloadTokenLimit);
        }
        if self.protected_record_ids.len() > MAX_PROTECTED_COMPACTION_REFS {
            return Err(QualifiedCompactionError::ProtectedReferenceLimitExceeded);
        }
        ensure_unique_ids(&self.protected_record_ids)?;
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut protected = self.protected_record_ids.iter().collect::<Vec<_>>();
        protected.sort();
        let mut bytes = Vec::new();
        bytes.extend_from_slice(POLICY_DOMAIN);
        push_id(&mut bytes, &self.policy_id);
        push_digest(&mut bytes, self.algorithm_digest);
        push_digest(&mut bytes, self.semantic_compaction_digest);
        push_digest(&mut bytes, self.compatibility_digest);
        push_digest(&mut bytes, self.tokenizer_digest);
        push_u64(&mut bytes, u64::from(self.maximum_retained_records));
        push_u64(&mut bytes, self.maximum_payload_bytes);
        push_u64(&mut bytes, self.maximum_payload_tokens);
        push_len(&mut bytes, protected.len());
        for record_id in protected {
            push_id(&mut bytes, record_id);
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Digest-bound output of the semantic compaction responsibility.
///
/// This engine does not grant a model or compressor authority. The producer
/// supplies a payload digest plus exact byte/token accounting. The artifact is
/// bound to the same snapshot/model/tokenizer as the checkpoint and can never
/// be admitted as a source fact by this contract.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticCompactionArtifactV1 {
    pub artifact_id: StableId,
    pub producer_id: StableId,
    pub source_snapshot_digest: Digest32,
    pub payload_digest: Digest32,
    pub algorithm_digest: Digest32,
    pub model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub encoded_bytes: u64,
    pub token_count: u64,
    fact_admission: bool,
    pub artifact_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl SemanticCompactionArtifactV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        artifact_id: StableId,
        producer_id: StableId,
        source_snapshot_digest: Digest32,
        payload_digest: Digest32,
        algorithm_digest: Digest32,
        model_digest: Digest32,
        tokenizer_digest: Digest32,
        encoded_bytes: u64,
        token_count: u64,
    ) -> Result<Self, QualifiedCompactionError> {
        let mut artifact = Self {
            artifact_id,
            producer_id,
            source_snapshot_digest,
            payload_digest,
            algorithm_digest,
            model_digest,
            tokenizer_digest,
            encoded_bytes,
            token_count,
            fact_admission: false,
            artifact_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        artifact.artifact_digest = artifact.compute_artifact_digest();
        artifact.validate()?;
        Ok(artifact)
    }

    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        for (name, digest) in [
            ("semantic_source_snapshot", self.source_snapshot_digest),
            ("semantic_payload", self.payload_digest),
            ("semantic_algorithm", self.algorithm_digest),
            ("semantic_model", self.model_digest),
            ("semantic_tokenizer", self.tokenizer_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.encoded_bytes == 0 || self.encoded_bytes > MAX_COMPACT_PAYLOAD_BYTES {
            return Err(QualifiedCompactionError::SemanticArtifactTooLarge);
        }
        if self.token_count == 0 || self.token_count > MAX_COMPACT_PAYLOAD_TOKENS {
            return Err(QualifiedCompactionError::SemanticArtifactTooManyTokens);
        }
        if self.fact_admission {
            return Err(QualifiedCompactionError::SemanticFactAdmission);
        }
        if self.authority.grants_any() {
            return Err(QualifiedCompactionError::AuthorityGranted);
        }
        if self.artifact_digest != self.compute_artifact_digest() {
            return Err(QualifiedCompactionError::DigestMismatch("semantic_artifact"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_artifact_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(SEMANTIC_ARTIFACT_DOMAIN);
        push_id(&mut bytes, &self.artifact_id);
        push_id(&mut bytes, &self.producer_id);
        push_digest(&mut bytes, self.source_snapshot_digest);
        push_digest(&mut bytes, self.payload_digest);
        push_digest(&mut bytes, self.algorithm_digest);
        push_digest(&mut bytes, self.model_digest);
        push_digest(&mut bytes, self.tokenizer_digest);
        push_u64(&mut bytes, self.encoded_bytes);
        push_u64(&mut bytes, self.token_count);
        bytes.push(u8::from(self.fact_admission));
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn fact_admission(&self) -> bool {
        self.fact_admission
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionInputRecordV2 {
    pub record: MemoryRecord,
    pub retention_priority: u32,
    pub retention_reason_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionLossReportV2 {
    pub source_current_heads: u64,
    pub live_source_heads: u64,
    pub retained_records: u64,
    pub omitted_live_records: u64,
    pub deleted_records: u64,
    pub protected_live_records: u64,
    pub protected_retained_records: u64,
    pub protected_deleted_records: u64,
    pub loss_report_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CompactionLossReportV2 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        if self.live_source_heads + self.deleted_records != self.source_current_heads {
            return Err(QualifiedCompactionError::InvalidLossAccounting);
        }
        if self.retained_records + self.omitted_live_records != self.live_source_heads {
            return Err(QualifiedCompactionError::InvalidLossAccounting);
        }
        if self.protected_retained_records != self.protected_live_records
            || self.protected_live_records + self.protected_deleted_records
                > self.source_current_heads
        {
            return Err(QualifiedCompactionError::ProtectedReferenceLost);
        }
        if self.authority.grants_any() {
            return Err(QualifiedCompactionError::AuthorityGranted);
        }
        if self.loss_report_digest != self.compute_digest() {
            return Err(QualifiedCompactionError::DigestMismatch("loss_report"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(LOSS_REPORT_DOMAIN);
        for value in [
            self.source_current_heads,
            self.live_source_heads,
            self.retained_records,
            self.omitted_live_records,
            self.deleted_records,
            self.protected_live_records,
            self.protected_retained_records,
            self.protected_deleted_records,
        ] {
            push_u64(&mut bytes, value);
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedCompactionCandidateV2 {
    pub source_snapshot: CognitiveSnapshotKeyV1,
    pub policy_digest: Digest32,
    pub retention_manifest_digest: Digest32,
    pub semantic_artifact: SemanticCompactionArtifactV1,
    pub retained_records: Vec<MemoryRecord>,
    pub omitted_record_digests: Vec<Digest32>,
    pub checkpoint: CompactCheckpointV1,
    pub loss_report: CompactionLossReportV2,
    pub candidate_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl QualifiedCompactionCandidateV2 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        self.source_snapshot
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        ensure_digest("policy", self.policy_digest)?;
        ensure_digest("retention_manifest", self.retention_manifest_digest)?;
        self.semantic_artifact.validate()?;
        self.checkpoint
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        self.loss_report.validate()?;
        if self.checkpoint.source_snapshot != self.source_snapshot {
            return Err(QualifiedCompactionError::SnapshotMismatch);
        }
        if self.semantic_artifact.source_snapshot_digest != self.source_snapshot.vector_digest {
            return Err(QualifiedCompactionError::SemanticSnapshotMismatch);
        }
        if self.semantic_artifact.model_digest != self.source_snapshot.vector.model_digest {
            return Err(QualifiedCompactionError::ModelMismatch);
        }
        if self.semantic_artifact.tokenizer_digest != self.source_snapshot.vector.tokenizer_digest {
            return Err(QualifiedCompactionError::TokenizerMismatch);
        }
        if self.checkpoint.payload_digest != self.semantic_artifact.payload_digest {
            return Err(QualifiedCompactionError::SemanticPayloadMismatch);
        }
        if self.checkpoint.algorithm_digest != self.semantic_artifact.algorithm_digest {
            return Err(QualifiedCompactionError::SemanticAlgorithmMismatch);
        }
        if self.authority.grants_any() {
            return Err(QualifiedCompactionError::AuthorityGranted);
        }
        let retained_count = u64::try_from(self.retained_records.len()).unwrap_or(u64::MAX);
        let omitted_count =
            u64::try_from(self.omitted_record_digests.len()).unwrap_or(u64::MAX);
        if retained_count != self.loss_report.retained_records
            || omitted_count != self.loss_report.omitted_live_records
        {
            return Err(QualifiedCompactionError::InvalidLossAccounting);
        }
        let mut identities = BTreeSet::new();
        for record in &self.retained_records {
            record
                .validate()
                .map_err(|error| QualifiedCompactionError::InvalidRecord(error.to_string()))?;
            if record.state != RecordState::Live {
                return Err(QualifiedCompactionError::TombstoneRetained(
                    record.record_id.to_string(),
                ));
            }
            if !identities.insert(record.record_id.clone()) {
                return Err(QualifiedCompactionError::DuplicateRetainedRecord(
                    record.record_id.to_string(),
                ));
            }
        }
        if self.candidate_digest != self.compute_candidate_digest() {
            return Err(QualifiedCompactionError::DigestMismatch("candidate"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_candidate_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(CANDIDATE_DOMAIN);
        push_digest(&mut bytes, self.source_snapshot.vector_digest);
        push_digest(&mut bytes, self.policy_digest);
        push_digest(&mut bytes, self.retention_manifest_digest);
        push_digest(&mut bytes, self.semantic_artifact.artifact_digest);
        push_digest(&mut bytes, self.checkpoint.checkpoint_digest);
        push_digest(&mut bytes, self.loss_report.loss_report_digest);
        push_len(&mut bytes, self.retained_records.len());
        for record in &self.retained_records {
            push_digest(&mut bytes, record.record_digest());
        }
        push_len(&mut bytes, self.omitted_record_digests.len());
        for digest in &self.omitted_record_digests {
            push_digest(&mut bytes, *digest);
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionQualificationV2 {
    pub evaluator_id: StableId,
    pub evaluator_implementation_digest: Digest32,
    pub evaluation_artifact_digest: Digest32,
    pub attestation_digest: Digest32,
    pub attestation_key_digest: Digest32,
    pub signature_digest: Digest32,
    pub retained_query_suite_digest: Digest32,
    pub reconstruction_obligation_digest: Digest32,
    pub contradiction_holdout_digest: Digest32,
    pub retained_queries_passed: bool,
    pub reconstruction_passed: bool,
    pub contradictions_preserved: bool,
    pub deletion_non_resurrection_passed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionEvaluatorEvidenceV1 {
    pub evaluator_id: StableId,
    pub evaluator_implementation_digest: Digest32,
    pub evaluation_artifact_digest: Digest32,
    pub attestation_digest: Digest32,
    pub attestation_key_digest: Digest32,
    pub signature_digest: Digest32,
    pub evidence_digest: Digest32,
}

impl CompactionEvaluatorEvidenceV1 {
    fn from_qualification(
        qualification: &CompactionQualificationV2,
    ) -> Result<Self, QualifiedCompactionError> {
        let mut evidence = Self {
            evaluator_id: qualification.evaluator_id.clone(),
            evaluator_implementation_digest: qualification.evaluator_implementation_digest,
            evaluation_artifact_digest: qualification.evaluation_artifact_digest,
            attestation_digest: qualification.attestation_digest,
            attestation_key_digest: qualification.attestation_key_digest,
            signature_digest: qualification.signature_digest,
            evidence_digest: Digest32::ZERO,
        };
        evidence.evidence_digest = evidence.compute_digest();
        evidence.validate()?;
        Ok(evidence)
    }

    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        for (name, digest) in [
            ("evaluator_implementation", self.evaluator_implementation_digest),
            ("evaluation_artifact", self.evaluation_artifact_digest),
            ("attestation", self.attestation_digest),
            ("attestation_key", self.attestation_key_digest),
            ("signature", self.signature_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.evidence_digest != self.compute_digest() {
            return Err(QualifiedCompactionError::DigestMismatch("evaluator_evidence"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(EVALUATOR_EVIDENCE_DOMAIN);
        push_id(&mut bytes, &self.evaluator_id);
        push_digest(&mut bytes, self.evaluator_implementation_digest);
        push_digest(&mut bytes, self.evaluation_artifact_digest);
        push_digest(&mut bytes, self.attestation_digest);
        push_digest(&mut bytes, self.attestation_key_digest);
        push_digest(&mut bytes, self.signature_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedCompactionProofV2 {
    pub base_proof: CompactionProofV1,
    pub evaluator_evidence: CompactionEvaluatorEvidenceV1,
    pub proof_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl QualifiedCompactionProofV2 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        self.base_proof
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        self.evaluator_evidence.validate()?;
        if self.authority.grants_any() {
            return Err(QualifiedCompactionError::AuthorityGranted);
        }
        if self.proof_digest != self.compute_proof_digest() {
            return Err(QualifiedCompactionError::DigestMismatch("qualified_proof"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_proof_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(QUALIFIED_PROOF_DOMAIN);
        push_digest(&mut bytes, self.base_proof.proof_digest);
        push_digest(&mut bytes, self.evaluator_evidence.evidence_digest);
        Digest32::of_bytes(&bytes)
    }
}

pub fn build_qualified_candidate(
    source_snapshot: CognitiveSnapshotKeyV1,
    generation: Generation,
    predecessor_checkpoint_digest: Option<Digest32>,
    policy: &CompactionPolicyV2,
    semantic_artifact: SemanticCompactionArtifactV1,
    inputs: Vec<CompactionInputRecordV2>,
) -> Result<QualifiedCompactionCandidateV2, QualifiedCompactionError> {
    source_snapshot
        .validate()
        .map_err(QualifiedCompactionError::Contract)?;
    policy.validate()?;
    semantic_artifact.validate()?;
    if inputs.len() > MAX_QUALIFIED_COMPACTION_INPUTS {
        return Err(QualifiedCompactionError::InputLimitExceeded);
    }
    if policy.tokenizer_digest != source_snapshot.vector.tokenizer_digest
        || semantic_artifact.tokenizer_digest != source_snapshot.vector.tokenizer_digest
    {
        return Err(QualifiedCompactionError::TokenizerMismatch);
    }
    if semantic_artifact.model_digest != source_snapshot.vector.model_digest {
        return Err(QualifiedCompactionError::ModelMismatch);
    }
    if semantic_artifact.source_snapshot_digest != source_snapshot.vector_digest {
        return Err(QualifiedCompactionError::SemanticSnapshotMismatch);
    }
    if semantic_artifact.algorithm_digest != policy.semantic_compaction_digest {
        return Err(QualifiedCompactionError::SemanticAlgorithmMismatch);
    }
    if semantic_artifact.encoded_bytes > policy.maximum_payload_bytes {
        return Err(QualifiedCompactionError::SemanticArtifactTooLarge);
    }
    if semantic_artifact.token_count > policy.maximum_payload_tokens {
        return Err(QualifiedCompactionError::SemanticArtifactTooManyTokens);
    }

    let mut by_record = BTreeMap::<StableId, Vec<CompactionInputRecordV2>>::new();
    for input in inputs {
        input
            .record
            .validate()
            .map_err(|error| QualifiedCompactionError::InvalidRecord(error.to_string()))?;
        ensure_digest("retention_reason", input.retention_reason_digest)?;
        by_record
            .entry(input.record.record_id.clone())
            .or_default()
            .push(input);
    }

    let protected = policy
        .protected_record_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    for record_id in &protected {
        if !by_record.contains_key(record_id) {
            return Err(QualifiedCompactionError::ProtectedReferenceMissing(
                record_id.to_string(),
            ));
        }
    }

    let normalized = normalize_current_heads(by_record, &protected)?;
    let mut live_heads = normalized.live_heads;
    live_heads.sort_by(|left, right| {
        protected
            .contains(&right.record.record_id)
            .cmp(&protected.contains(&left.record.record_id))
            .then_with(|| right.retention_priority.cmp(&left.retention_priority))
            .then_with(|| left.record.record_id.cmp(&right.record.record_id))
            .then_with(|| left.record.revision.cmp(&right.record.revision))
    });

    let protected_live_records = live_heads
        .iter()
        .filter(|input| protected.contains(&input.record.record_id))
        .count();
    let maximum = usize::try_from(policy.maximum_retained_records).unwrap_or(usize::MAX);
    if protected_live_records > maximum {
        return Err(QualifiedCompactionError::ProtectedReferencesExceedCapacity);
    }

    let retained_inputs = live_heads.iter().take(maximum).collect::<Vec<_>>();
    let omitted_inputs = live_heads.iter().skip(maximum).collect::<Vec<_>>();
    if retained_inputs
        .iter()
        .filter(|input| protected.contains(&input.record.record_id))
        .count()
        != protected_live_records
    {
        return Err(QualifiedCompactionError::ProtectedReferenceLost);
    }

    let retained_records = retained_inputs
        .iter()
        .map(|input| input.record.clone())
        .collect::<Vec<_>>();
    let omitted_record_digests = omitted_inputs
        .iter()
        .map(|input| input.record.record_digest())
        .collect::<Vec<_>>();
    let live_source_heads = u64::try_from(live_heads.len()).unwrap_or(u64::MAX);
    let retained_count = u64::try_from(retained_records.len()).unwrap_or(u64::MAX);
    let omitted_count = u64::try_from(omitted_record_digests.len()).unwrap_or(u64::MAX);

    let support_manifest_digest = digest_record_set(
        SUPPORT_MANIFEST_DOMAIN,
        live_heads.iter().map(|input| &input.record),
    );
    let retention_manifest_digest = digest_retention_manifest(&live_heads);
    let omitted_information_digest = digest_digests(OMITTED_DOMAIN, &omitted_record_digests);
    let checkpoint_id = StableId::new(format!(
        "compact:{}:{}",
        generation.get(),
        source_snapshot.vector_digest
    ))
    .map_err(|_| QualifiedCompactionError::InvalidCheckpointIdentity)?;
    let mut checkpoint = CompactCheckpointV1 {
        checkpoint_id,
        generation,
        source_snapshot: source_snapshot.clone(),
        support_manifest_digest,
        algorithm_digest: semantic_artifact.algorithm_digest,
        payload_digest: semantic_artifact.payload_digest,
        omitted_information_digest,
        tombstone_cutoff: source_snapshot.vector.tombstone_frontier,
        predecessor_digest: predecessor_checkpoint_digest,
        compatibility_digest: policy.compatibility_digest,
        checkpoint_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    checkpoint.checkpoint_digest = checkpoint.compute_checkpoint_digest();
    checkpoint
        .validate()
        .map_err(QualifiedCompactionError::Contract)?;

    let mut loss_report = CompactionLossReportV2 {
        source_current_heads: normalized.source_current_heads,
        live_source_heads,
        retained_records: retained_count,
        omitted_live_records: omitted_count,
        deleted_records: normalized.deleted_records,
        protected_live_records: u64::try_from(protected_live_records).unwrap_or(u64::MAX),
        protected_retained_records: u64::try_from(protected_live_records).unwrap_or(u64::MAX),
        protected_deleted_records: normalized.protected_deleted_records,
        loss_report_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    loss_report.loss_report_digest = loss_report.compute_digest();
    loss_report.validate()?;

    let mut candidate = QualifiedCompactionCandidateV2 {
        source_snapshot,
        policy_digest: policy.digest(),
        retention_manifest_digest,
        semantic_artifact,
        retained_records,
        omitted_record_digests,
        checkpoint,
        loss_report,
        candidate_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    candidate.candidate_digest = candidate.compute_candidate_digest();
    candidate.validate()?;
    Ok(candidate)
}

pub fn prove_compaction(
    candidate: &QualifiedCompactionCandidateV2,
    qualification: CompactionQualificationV2,
) -> Result<QualifiedCompactionProofV2, QualifiedCompactionError> {
    candidate.validate()?;
    for (name, digest) in [
        (
            "evaluator_implementation",
            qualification.evaluator_implementation_digest,
        ),
        ("evaluation_artifact", qualification.evaluation_artifact_digest),
        ("attestation", qualification.attestation_digest),
        ("attestation_key", qualification.attestation_key_digest),
        ("signature", qualification.signature_digest),
        (
            "retained_query_suite",
            qualification.retained_query_suite_digest,
        ),
        (
            "reconstruction_obligation",
            qualification.reconstruction_obligation_digest,
        ),
        (
            "contradiction_holdout",
            qualification.contradiction_holdout_digest,
        ),
    ] {
        ensure_digest(name, digest)?;
    }
    if !qualification.retained_queries_passed {
        return Err(QualifiedCompactionError::RetainedQueryRegression);
    }
    if !qualification.reconstruction_passed {
        return Err(QualifiedCompactionError::ReconstructionFailed);
    }
    if !qualification.contradictions_preserved {
        return Err(QualifiedCompactionError::ContradictionLoss);
    }
    if !qualification.deletion_non_resurrection_passed {
        return Err(QualifiedCompactionError::DeletionNonResurrectionFailed);
    }

    let evaluator_evidence = CompactionEvaluatorEvidenceV1::from_qualification(&qualification)?;
    let mut base_proof = CompactionProofV1 {
        checkpoint_digest: candidate.checkpoint.checkpoint_digest,
        retained_query_suite_digest: qualification.retained_query_suite_digest,
        reconstruction_obligation_digest: qualification.reconstruction_obligation_digest,
        contradiction_holdout_digest: qualification.contradiction_holdout_digest,
        deletion_cutoff: candidate.checkpoint.tombstone_cutoff,
        source_count: candidate.loss_report.live_source_heads,
        retained_count: candidate.loss_report.retained_records,
        proof_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    base_proof.proof_digest = base_proof.compute_proof_digest();
    base_proof
        .validate()
        .map_err(QualifiedCompactionError::Contract)?;

    let mut proof = QualifiedCompactionProofV2 {
        base_proof,
        evaluator_evidence,
        proof_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    proof.proof_digest = proof.compute_proof_digest();
    proof.validate()?;
    Ok(proof)
}

struct NormalizedHeads {
    live_heads: Vec<CompactionInputRecordV2>,
    source_current_heads: u64,
    deleted_records: u64,
    protected_deleted_records: u64,
}

fn normalize_current_heads(
    by_record: BTreeMap<StableId, Vec<CompactionInputRecordV2>>,
    protected: &BTreeSet<StableId>,
) -> Result<NormalizedHeads, QualifiedCompactionError> {
    let mut live_heads = Vec::new();
    let mut source_current_heads = 0_u64;
    let mut deleted_records = 0_u64;
    let mut protected_deleted_records = 0_u64;

    for (record_id, mut lineage) in by_record {
        lineage.sort_by_key(|input| input.record.revision);
        validate_lineage(&record_id, &lineage)?;
        let Some(head) = lineage.pop() else {
            return Err(QualifiedCompactionError::EmptyLineage);
        };
        source_current_heads = source_current_heads
            .checked_add(1)
            .ok_or(QualifiedCompactionError::Arithmetic)?;
        if head.record.state == RecordState::Tombstone {
            deleted_records = deleted_records
                .checked_add(1)
                .ok_or(QualifiedCompactionError::Arithmetic)?;
            if protected.contains(&record_id) {
                protected_deleted_records = protected_deleted_records
                    .checked_add(1)
                    .ok_or(QualifiedCompactionError::Arithmetic)?;
            }
        } else {
            live_heads.push(head);
        }
    }

    Ok(NormalizedHeads {
        live_heads,
        source_current_heads,
        deleted_records,
        protected_deleted_records,
    })
}

fn validate_lineage(
    record_id: &StableId,
    lineage: &[CompactionInputRecordV2],
) -> Result<(), QualifiedCompactionError> {
    let mut previous: Option<&MemoryRecord> = None;
    let mut tombstone_seen = false;
    for input in lineage {
        let record = &input.record;
        match previous {
            None => {
                if record.revision.get() != 1 || record.predecessor_digest.is_some() {
                    return Err(QualifiedCompactionError::BrokenLineage(
                        record_id.to_string(),
                    ));
                }
            }
            Some(previous) => {
                if record.revision.get() != previous.revision.get().saturating_add(1)
                    || record.predecessor_digest != Some(previous.record_digest())
                {
                    return Err(QualifiedCompactionError::BrokenLineage(
                        record_id.to_string(),
                    ));
                }
            }
        }
        if tombstone_seen && record.state == RecordState::Live {
            return Err(QualifiedCompactionError::ResurrectionDenied(
                record_id.to_string(),
            ));
        }
        tombstone_seen |= record.state == RecordState::Tombstone;
        previous = Some(record);
    }
    Ok(())
}

fn digest_record_set<'a>(
    domain: &[u8],
    records: impl IntoIterator<Item = &'a MemoryRecord>,
) -> Digest32 {
    let mut digests = records
        .into_iter()
        .map(MemoryRecord::record_digest)
        .collect::<Vec<_>>();
    digests.sort();
    digest_digests(domain, &digests)
}

fn digest_retention_manifest(inputs: &[CompactionInputRecordV2]) -> Digest32 {
    let mut inputs = inputs.iter().collect::<Vec<_>>();
    inputs.sort_by(|left, right| {
        left.record
            .record_id
            .cmp(&right.record.record_id)
            .then_with(|| left.record.revision.cmp(&right.record.revision))
    });
    let mut bytes = Vec::new();
    bytes.extend_from_slice(RETENTION_MANIFEST_DOMAIN);
    push_len(&mut bytes, inputs.len());
    for input in inputs {
        push_id(&mut bytes, &input.record.record_id);
        push_u64(&mut bytes, input.record.revision.get());
        push_digest(&mut bytes, input.record.record_digest());
        push_u64(&mut bytes, u64::from(input.retention_priority));
        push_digest(&mut bytes, input.retention_reason_digest);
    }
    Digest32::of_bytes(&bytes)
}

fn digest_digests(domain: &[u8], digests: &[Digest32]) -> Digest32 {
    let mut digests = digests.to_vec();
    digests.sort();
    let mut bytes = Vec::new();
    bytes.extend_from_slice(domain);
    push_len(&mut bytes, digests.len());
    for digest in digests {
        push_digest(&mut bytes, digest);
    }
    Digest32::of_bytes(&bytes)
}

fn ensure_unique_ids(values: &[StableId]) -> Result<(), QualifiedCompactionError> {
    let mut seen = BTreeSet::new();
    for value in values {
        if !seen.insert(value.clone()) {
            return Err(QualifiedCompactionError::DuplicateProtectedReference(
                value.to_string(),
            ));
        }
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QualifiedCompactionError {
    Contract(LaneCContractError),
    EmptyDigest(&'static str),
    DigestMismatch(&'static str),
    InvalidRetentionLimit,
    InvalidPayloadByteLimit,
    InvalidPayloadTokenLimit,
    InputLimitExceeded,
    ProtectedReferenceLimitExceeded,
    DuplicateProtectedReference(String),
    ProtectedReferenceMissing(String),
    ProtectedReferencesExceedCapacity,
    ProtectedReferenceLost,
    InvalidLossAccounting,
    InvalidRecord(String),
    EmptyLineage,
    BrokenLineage(String),
    ResurrectionDenied(String),
    TombstoneRetained(String),
    DuplicateRetainedRecord(String),
    SnapshotMismatch,
    SemanticSnapshotMismatch,
    SemanticPayloadMismatch,
    SemanticAlgorithmMismatch,
    SemanticArtifactTooLarge,
    SemanticArtifactTooManyTokens,
    SemanticFactAdmission,
    ModelMismatch,
    TokenizerMismatch,
    InvalidCheckpointIdentity,
    RetainedQueryRegression,
    ReconstructionFailed,
    ContradictionLoss,
    DeletionNonResurrectionFailed,
    AuthorityGranted,
    Arithmetic,
}

impl fmt::Display for QualifiedCompactionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for QualifiedCompactionError {}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), QualifiedCompactionError> {
    if digest.is_zero() {
        return Err(QualifiedCompactionError::EmptyDigest(name));
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

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

#[cfg(test)]
#[path = "qualified_tests.rs"]
mod tests;
