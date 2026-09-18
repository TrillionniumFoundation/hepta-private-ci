//! Loss-bounded, deletion-aware context compaction qualification.
//!
//! Compaction never rewrites or deletes source facts.  It selects provenance
//! references from one coherent Lane C snapshot, enforces record/byte/token
//! budgets, binds an immutable semantic payload generated for that exact
//! snapshot and emits the canonical Lane C checkpoint.  A checkpoint is not
//! selectable until an independently produced evaluation/attestation is bound
//! into a separate proof.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
use codex_hepta_cognitive_types::lane_c::CompactionProofV2;
use codex_hepta_cognitive_types::lane_c::LaneCContractError;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub const MAX_QUALIFIED_COMPACTION_INPUTS: usize = 65_536;
pub const MAX_PROTECTED_COMPACTION_REFS: usize = 4_096;
const POLICY_DOMAIN: &[u8] = b"hepta.compaction-policy.v2";
const CANDIDATE_DOMAIN: &[u8] = b"hepta.compaction-candidate.v2";
const SEMANTIC_PAYLOAD_DOMAIN: &[u8] = b"hepta.compaction-semantic-payload.v2";
const INPUT_DOMAIN: &[u8] = b"hepta.compaction-input.v2";
const SUPPORT_MANIFEST_DOMAIN: &[u8] = b"hepta.compaction-support-manifest.v2";
const OMITTED_DOMAIN: &[u8] = b"hepta.compaction-omitted.v2";
const LOSS_REPORT_DOMAIN: &[u8] = b"hepta.compaction-loss-report.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionPolicyV2 {
    pub policy_id: StableId,
    pub algorithm_digest: Digest32,
    pub compatibility_digest: Digest32,
    pub maximum_retained_records: u32,
    pub maximum_retained_bytes: u64,
    pub maximum_retained_tokens: u64,
    pub maximum_payload_bytes: u64,
    pub maximum_payload_tokens: u64,
    pub protected_record_ids: Vec<StableId>,
}

impl CompactionPolicyV2 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        ensure_digest("algorithm", self.algorithm_digest)?;
        ensure_digest("compatibility", self.compatibility_digest)?;
        let maximum = usize::try_from(self.maximum_retained_records).unwrap_or(usize::MAX);
        if maximum == 0 || maximum > MAX_QUALIFIED_COMPACTION_INPUTS {
            return Err(QualifiedCompactionError::InvalidRetentionLimit);
        }
        if self.maximum_retained_bytes == 0
            || self.maximum_retained_tokens == 0
            || self.maximum_payload_bytes == 0
            || self.maximum_payload_tokens == 0
        {
            return Err(QualifiedCompactionError::InvalidBudget);
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
        push_digest(&mut bytes, self.compatibility_digest);
        push_u64(&mut bytes, u64::from(self.maximum_retained_records));
        push_u64(&mut bytes, self.maximum_retained_bytes);
        push_u64(&mut bytes, self.maximum_retained_tokens);
        push_u64(&mut bytes, self.maximum_payload_bytes);
        push_u64(&mut bytes, self.maximum_payload_tokens);
        push_len(&mut bytes, protected.len());
        for record_id in protected {
            push_id(&mut bytes, record_id);
        }
        Digest32::of_bytes(&bytes)
    }
}

/// One source record plus deterministic resource accounting supplied by the
/// snapshot/tokenizer owner.  Byte/token costs are part of the support
/// manifest; callers cannot change them without changing candidate identity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionInputRecordV2 {
    pub record: MemoryRecord,
    pub retention_priority: u32,
    pub retention_reason_digest: Digest32,
    pub encoded_bytes: u64,
    pub token_count: u64,
}

impl CompactionInputRecordV2 {
    fn validate(&self) -> Result<(), QualifiedCompactionError> {
        self.record
            .validate()
            .map_err(|error| QualifiedCompactionError::InvalidRecord(error.to_string()))?;
        ensure_digest("retention_reason", self.retention_reason_digest)?;
        if self.encoded_bytes == 0 || self.token_count == 0 {
            return Err(QualifiedCompactionError::InvalidInputCost(
                self.record.record_id.to_string(),
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(INPUT_DOMAIN);
        push_digest(&mut bytes, self.record.record_digest());
        push_u64(&mut bytes, u64::from(self.retention_priority));
        push_digest(&mut bytes, self.retention_reason_digest);
        push_u64(&mut bytes, self.encoded_bytes);
        push_u64(&mut bytes, self.token_count);
        Digest32::of_bytes(&bytes)
    }
}

/// Immutable semantic context artifact produced outside this pure kernel.
///
/// The engine does not invoke a model or invent semantic content.  It requires
/// a generator receipt for the exact source snapshot, tokenizer and output
/// cost, then binds those facts into the candidate/checkpoint.  Independent
/// reconstruction/holdout evaluation is still required before proof.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionSemanticPayloadV2 {
    pub source_snapshot_digest: Digest32,
    pub payload_digest: Digest32,
    pub generator_implementation_digest: Digest32,
    pub generator_receipt_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub encoded_bytes: u64,
    pub token_count: u64,
}

impl CompactionSemanticPayloadV2 {
    pub fn validate(
        &self,
        source_snapshot: &CognitiveSnapshotKeyV1,
        policy: &CompactionPolicyV2,
    ) -> Result<(), QualifiedCompactionError> {
        for (name, digest) in [
            ("semantic_source_snapshot", self.source_snapshot_digest),
            ("semantic_payload", self.payload_digest),
            (
                "semantic_generator_implementation",
                self.generator_implementation_digest,
            ),
            ("semantic_generator_receipt", self.generator_receipt_digest),
            ("semantic_tokenizer", self.tokenizer_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.source_snapshot_digest != source_snapshot.vector_digest {
            return Err(QualifiedCompactionError::SemanticSnapshotMismatch);
        }
        if self.tokenizer_digest != source_snapshot.vector.tokenizer_digest {
            return Err(QualifiedCompactionError::TokenizerMismatch);
        }
        if self.encoded_bytes == 0 || self.token_count == 0 {
            return Err(QualifiedCompactionError::InvalidSemanticPayloadCost);
        }
        if self.encoded_bytes > policy.maximum_payload_bytes
            || self.token_count > policy.maximum_payload_tokens
        {
            return Err(QualifiedCompactionError::PayloadBudgetExceeded);
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(SEMANTIC_PAYLOAD_DOMAIN);
        push_digest(&mut bytes, self.source_snapshot_digest);
        push_digest(&mut bytes, self.payload_digest);
        push_digest(&mut bytes, self.generator_implementation_digest);
        push_digest(&mut bytes, self.generator_receipt_digest);
        push_digest(&mut bytes, self.tokenizer_digest);
        push_u64(&mut bytes, self.encoded_bytes);
        push_u64(&mut bytes, self.token_count);
        Digest32::of_bytes(&bytes)
    }
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
    pub live_source_bytes: u64,
    pub retained_bytes: u64,
    pub omitted_live_bytes: u64,
    pub live_source_tokens: u64,
    pub retained_tokens: u64,
    pub omitted_live_tokens: u64,
    pub loss_report_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CompactionLossReportV2 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        if self.live_source_heads.checked_add(self.deleted_records)
            != Some(self.source_current_heads)
        {
            return Err(QualifiedCompactionError::InvalidLossAccounting);
        }
        if self.retained_records.checked_add(self.omitted_live_records)
            != Some(self.live_source_heads)
            || self.retained_bytes.checked_add(self.omitted_live_bytes)
                != Some(self.live_source_bytes)
            || self.retained_tokens.checked_add(self.omitted_live_tokens)
                != Some(self.live_source_tokens)
        {
            return Err(QualifiedCompactionError::InvalidLossAccounting);
        }
        if self.protected_retained_records != self.protected_live_records
            || self
                .protected_live_records
                .checked_add(self.protected_deleted_records)
                .is_none_or(|value| value > self.source_current_heads)
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
            self.live_source_bytes,
            self.retained_bytes,
            self.omitted_live_bytes,
            self.live_source_tokens,
            self.retained_tokens,
            self.omitted_live_tokens,
        ] {
            push_u64(&mut bytes, value);
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedCompactionCandidateV2 {
    pub source_snapshot: CognitiveSnapshotKeyV1,
    pub policy: CompactionPolicyV2,
    pub semantic_payload: CompactionSemanticPayloadV2,
    pub retained_records: Vec<MemoryRecord>,
    pub retained_input_digests: Vec<Digest32>,
    pub omitted_input_digests: Vec<Digest32>,
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
        self.policy.validate()?;
        self.semantic_payload
            .validate(&self.source_snapshot, &self.policy)?;
        self.checkpoint
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        self.loss_report.validate()?;
        if self.checkpoint.source_snapshot != self.source_snapshot {
            return Err(QualifiedCompactionError::SnapshotMismatch);
        }
        if self.checkpoint.algorithm_digest != self.policy.algorithm_digest
            || self.checkpoint.compatibility_digest != self.policy.compatibility_digest
        {
            return Err(QualifiedCompactionError::PolicyCheckpointMismatch);
        }
        if self.checkpoint.payload_digest != self.semantic_payload.payload_digest {
            return Err(QualifiedCompactionError::SemanticPayloadMismatch);
        }
        if self.loss_report.retained_records
            != u64::try_from(self.retained_records.len()).unwrap_or(u64::MAX)
            || self.retained_records.len() != self.retained_input_digests.len()
            || self.loss_report.omitted_live_records
                != u64::try_from(self.omitted_input_digests.len()).unwrap_or(u64::MAX)
        {
            return Err(QualifiedCompactionError::InvalidLossAccounting);
        }
        if self.loss_report.retained_records > u64::from(self.policy.maximum_retained_records)
            || self.loss_report.retained_bytes > self.policy.maximum_retained_bytes
            || self.loss_report.retained_tokens > self.policy.maximum_retained_tokens
        {
            return Err(QualifiedCompactionError::RetentionBudgetExceeded);
        }

        let mut all_inputs = self.retained_input_digests.clone();
        all_inputs.extend_from_slice(&self.omitted_input_digests);
        if self.checkpoint.support_manifest_digest
            != digest_digests(SUPPORT_MANIFEST_DOMAIN, &all_inputs)
            || self.checkpoint.omitted_information_digest
                != digest_digests(OMITTED_DOMAIN, &self.omitted_input_digests)
        {
            return Err(QualifiedCompactionError::DigestMismatch("support_manifest"));
        }

        if self.authority.grants_any() {
            return Err(QualifiedCompactionError::AuthorityGranted);
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
        push_digest(&mut bytes, self.policy.digest());
        push_digest(&mut bytes, self.semantic_payload.digest());
        push_digest(&mut bytes, self.checkpoint.checkpoint_digest);
        push_digest(&mut bytes, self.loss_report.loss_report_digest);
        push_len(&mut bytes, self.retained_records.len());
        for record in &self.retained_records {
            push_digest(&mut bytes, record.record_digest());
        }
        push_len(&mut bytes, self.retained_input_digests.len());
        for digest in &self.retained_input_digests {
            push_digest(&mut bytes, *digest);
        }
        push_len(&mut bytes, self.omitted_input_digests.len());
        for digest in &self.omitted_input_digests {
            push_digest(&mut bytes, *digest);
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Independent evaluation inputs.  The proof binds both evaluator identity and
/// the cryptographic evidence produced by the evaluator boundary.  This pure
/// crate does not trust or verify a public key on its own; the
/// `signature_verification_receipt_digest` identifies the external
/// verification receipt that must already exist.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionQualificationV2 {
    pub evaluator_id: StableId,
    pub evaluator_implementation_digest: Digest32,
    pub evaluation_artifact_digest: Digest32,
    pub attestation_digest: Digest32,
    pub attestation_signature_digest: Digest32,
    pub signature_verification_receipt_digest: Digest32,
    pub retained_query_suite_digest: Digest32,
    pub reconstruction_obligation_digest: Digest32,
    pub contradiction_holdout_digest: Digest32,
    pub retained_queries_passed: bool,
    pub reconstruction_passed: bool,
    pub contradictions_preserved: bool,
    pub deletion_non_resurrection_passed: bool,
}

pub fn build_qualified_candidate(
    source_snapshot: CognitiveSnapshotKeyV1,
    generation: Generation,
    predecessor_checkpoint_digest: Option<Digest32>,
    policy: &CompactionPolicyV2,
    semantic_payload: &CompactionSemanticPayloadV2,
    inputs: Vec<CompactionInputRecordV2>,
) -> Result<QualifiedCompactionCandidateV2, QualifiedCompactionError> {
    source_snapshot
        .validate()
        .map_err(QualifiedCompactionError::Contract)?;
    policy.validate()?;
    semantic_payload.validate(&source_snapshot, policy)?;
    if inputs.len() > MAX_QUALIFIED_COMPACTION_INPUTS {
        return Err(QualifiedCompactionError::InputLimitExceeded);
    }

    let mut by_record = BTreeMap::<StableId, Vec<CompactionInputRecordV2>>::new();
    for input in inputs {
        input.validate()?;
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
    let current_ids = by_record.keys().cloned().collect::<BTreeSet<_>>();
    if let Some(missing) = protected.difference(&current_ids).next() {
        return Err(QualifiedCompactionError::ProtectedReferenceMissing(
            missing.to_string(),
        ));
    }

    let mut live_heads = Vec::<CompactionInputRecordV2>::new();
    let mut source_current_heads = 0_u64;
    let mut deleted_records = 0_u64;
    let mut protected_deleted_records = 0_u64;

    for (record_id, mut lineage) in by_record {
        lineage.sort_by_key(|input| input.record.revision);
        validate_lineage(&record_id, &lineage)?;
        let Some(head) = lineage.pop() else {
            return Err(QualifiedCompactionError::EmptyLineage);
        };
        source_current_heads = checked_add(source_current_heads, 1)?;
        if head.record.state == RecordState::Tombstone {
            deleted_records = checked_add(deleted_records, 1)?;
            if protected.contains(&record_id) {
                protected_deleted_records = checked_add(protected_deleted_records, 1)?;
            }
        } else {
            live_heads.push(head);
        }
    }

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
    let maximum_records = usize::try_from(policy.maximum_retained_records).unwrap_or(usize::MAX);

    let mut retained_inputs = Vec::new();
    let mut omitted_inputs = Vec::new();
    let mut retained_bytes = 0_u64;
    let mut retained_tokens = 0_u64;
    let mut live_source_bytes = 0_u64;
    let mut live_source_tokens = 0_u64;

    for input in live_heads {
        live_source_bytes = checked_add(live_source_bytes, input.encoded_bytes)?;
        live_source_tokens = checked_add(live_source_tokens, input.token_count)?;

        let next_bytes = retained_bytes.checked_add(input.encoded_bytes);
        let next_tokens = retained_tokens.checked_add(input.token_count);
        let fits = retained_inputs.len() < maximum_records
            && next_bytes.is_some_and(|value| value <= policy.maximum_retained_bytes)
            && next_tokens.is_some_and(|value| value <= policy.maximum_retained_tokens);

        if fits {
            retained_bytes = next_bytes.ok_or(QualifiedCompactionError::Arithmetic)?;
            retained_tokens = next_tokens.ok_or(QualifiedCompactionError::Arithmetic)?;
            retained_inputs.push(input);
        } else if protected.contains(&input.record.record_id) {
            return Err(QualifiedCompactionError::ProtectedReferencesExceedCapacity);
        } else {
            omitted_inputs.push(input);
        }
    }

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
    let retained_input_digests = retained_inputs
        .iter()
        .map(|input| input.digest())
        .collect::<Vec<_>>();
    let omitted_input_digests = omitted_inputs
        .iter()
        .map(|input| input.digest())
        .collect::<Vec<_>>();

    let retained_count = u64::try_from(retained_records.len()).unwrap_or(u64::MAX);
    let omitted_count = u64::try_from(omitted_input_digests.len()).unwrap_or(u64::MAX);
    let live_source_heads = checked_add(retained_count, omitted_count)?;
    let omitted_live_bytes = live_source_bytes
        .checked_sub(retained_bytes)
        .ok_or(QualifiedCompactionError::Arithmetic)?;
    let omitted_live_tokens = live_source_tokens
        .checked_sub(retained_tokens)
        .ok_or(QualifiedCompactionError::Arithmetic)?;

    let mut support_digests = retained_input_digests.clone();
    support_digests.extend_from_slice(&omitted_input_digests);
    let support_manifest_digest = digest_digests(SUPPORT_MANIFEST_DOMAIN, &support_digests);
    let omitted_information_digest = digest_digests(OMITTED_DOMAIN, &omitted_input_digests);

    let mut checkpoint = CompactCheckpointV1 {
        checkpoint_id: StableId::new(format!(
            "compact:{}:{}",
            generation.get(),
            source_snapshot.vector_digest
        ))
        .map_err(|_| QualifiedCompactionError::InvalidCheckpointIdentity)?,
        generation,
        source_snapshot: source_snapshot.clone(),
        support_manifest_digest,
        algorithm_digest: policy.algorithm_digest,
        payload_digest: semantic_payload.payload_digest,
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
        source_current_heads,
        live_source_heads,
        retained_records: retained_count,
        omitted_live_records: omitted_count,
        deleted_records,
        protected_live_records: u64::try_from(protected_live_records).unwrap_or(u64::MAX),
        protected_retained_records: u64::try_from(protected_live_records).unwrap_or(u64::MAX),
        protected_deleted_records,
        live_source_bytes,
        retained_bytes,
        omitted_live_bytes,
        live_source_tokens,
        retained_tokens,
        omitted_live_tokens,
        loss_report_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    loss_report.loss_report_digest = loss_report.compute_digest();
    loss_report.validate()?;

    let mut candidate = QualifiedCompactionCandidateV2 {
        source_snapshot,
        policy: policy.clone(),
        semantic_payload: semantic_payload.clone(),
        retained_records,
        retained_input_digests,
        omitted_input_digests,
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
) -> Result<CompactionProofV2, QualifiedCompactionError> {
    candidate.validate()?;
    for (name, digest) in [
        (
            "evaluator_implementation",
            qualification.evaluator_implementation_digest,
        ),
        (
            "evaluation_artifact",
            qualification.evaluation_artifact_digest,
        ),
        ("attestation", qualification.attestation_digest),
        (
            "attestation_signature",
            qualification.attestation_signature_digest,
        ),
        (
            "signature_verification_receipt",
            qualification.signature_verification_receipt_digest,
        ),
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

    let mut proof = CompactionProofV2 {
        checkpoint_digest: candidate.checkpoint.checkpoint_digest,
        candidate_digest: candidate.candidate_digest,
        evaluator_id: qualification.evaluator_id,
        evaluator_implementation_digest: qualification.evaluator_implementation_digest,
        evaluation_artifact_digest: qualification.evaluation_artifact_digest,
        attestation_digest: qualification.attestation_digest,
        attestation_signature_digest: qualification.attestation_signature_digest,
        signature_verification_receipt_digest: qualification.signature_verification_receipt_digest,
        retained_query_suite_digest: qualification.retained_query_suite_digest,
        reconstruction_obligation_digest: qualification.reconstruction_obligation_digest,
        contradiction_holdout_digest: qualification.contradiction_holdout_digest,
        deletion_cutoff: candidate.checkpoint.tombstone_cutoff,
        source_count: candidate.loss_report.live_source_heads,
        retained_count: candidate.loss_report.retained_records,
        proof_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    proof.proof_digest = proof.compute_proof_digest();
    proof
        .validate()
        .map_err(QualifiedCompactionError::Contract)?;
    Ok(proof)
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

fn checked_add(left: u64, right: u64) -> Result<u64, QualifiedCompactionError> {
    left.checked_add(right)
        .ok_or(QualifiedCompactionError::Arithmetic)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QualifiedCompactionError {
    Contract(LaneCContractError),
    EmptyDigest(&'static str),
    DigestMismatch(&'static str),
    InvalidRetentionLimit,
    InvalidBudget,
    InputLimitExceeded,
    ProtectedReferenceLimitExceeded,
    DuplicateProtectedReference(String),
    ProtectedReferenceMissing(String),
    ProtectedReferencesExceedCapacity,
    ProtectedReferenceLost,
    InvalidLossAccounting,
    InvalidRecord(String),
    InvalidInputCost(String),
    InvalidSemanticPayloadCost,
    PayloadBudgetExceeded,
    RetentionBudgetExceeded,
    EmptyLineage,
    BrokenLineage(String),
    ResurrectionDenied(String),
    TombstoneRetained(String),
    DuplicateRetainedRecord(String),
    SnapshotMismatch,
    SemanticSnapshotMismatch,
    TokenizerMismatch,
    PolicyCheckpointMismatch,
    SemanticPayloadMismatch,
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
