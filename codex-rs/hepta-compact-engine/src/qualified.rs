//! Canonical loss-bounded, deletion-aware compaction planning and proof.
//!
//! Planning chooses current live heads from one coherent Lane C snapshot,
//! preserves protected references, and accounts for record, byte, and token
//! budgets. Semantic compression is performed by a separately identified
//! compactor and is admitted only through a digest-bound receipt. Qualification
//! must be signed by a host-trusted evaluator; self-asserted pass booleans are
//! not sufficient to construct a proof.

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
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

pub const MAX_QUALIFIED_COMPACTION_INPUTS: usize = 65_536;
pub const MAX_PROTECTED_COMPACTION_REFS: usize = 4_096;
pub const MAX_QUALIFIED_COMPACTION_BYTES: u64 = 64 * 1024 * 1024;
pub const MAX_QUALIFIED_COMPACTION_TOKENS: u64 = 8_000_000;

const POLICY_DOMAIN: &[u8] = b"hepta.compaction-policy.v3";
const INPUT_DOMAIN: &[u8] = b"hepta.compaction-input.v3";
const PLAN_DOMAIN: &[u8] = b"hepta.compaction-plan.v3";
const CANDIDATE_DOMAIN: &[u8] = b"hepta.compaction-candidate.v3";
const SUPPORT_MANIFEST_DOMAIN: &[u8] = b"hepta.compaction-support-manifest.v3";
const OMITTED_DOMAIN: &[u8] = b"hepta.compaction-omitted.v3";
const LOSS_REPORT_DOMAIN: &[u8] = b"hepta.compaction-loss-report.v3";
const SEMANTIC_RECEIPT_DOMAIN: &[u8] = b"hepta.semantic-compaction-receipt.v1";
const QUALIFICATION_DOMAIN: &[u8] = b"hepta.compaction-qualification.v3";
const PROOF_V2_DOMAIN: &[u8] = b"hepta.compaction-proof.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionPolicyV3 {
    pub policy_id: StableId,
    pub algorithm_digest: Digest32,
    pub compatibility_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub semantic_compactor_id: StableId,
    pub semantic_compactor_implementation_digest: Digest32,
    pub maximum_retained_records: u32,
    pub maximum_retained_bytes: u64,
    pub maximum_retained_tokens: u64,
    pub protected_record_ids: Vec<StableId>,
}

impl CompactionPolicyV3 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        for (name, digest) in [
            ("algorithm", self.algorithm_digest),
            ("compatibility", self.compatibility_digest),
            ("tokenizer", self.tokenizer_digest),
            (
                "semantic_compactor_implementation",
                self.semantic_compactor_implementation_digest,
            ),
        ] {
            ensure_digest(name, digest)?;
        }
        let maximum = usize::try_from(self.maximum_retained_records).unwrap_or(usize::MAX);
        if maximum == 0 || maximum > MAX_QUALIFIED_COMPACTION_INPUTS {
            return Err(QualifiedCompactionError::InvalidRetentionLimit);
        }
        if self.maximum_retained_bytes == 0
            || self.maximum_retained_bytes > MAX_QUALIFIED_COMPACTION_BYTES
        {
            return Err(QualifiedCompactionError::InvalidByteLimit);
        }
        if self.maximum_retained_tokens == 0
            || self.maximum_retained_tokens > MAX_QUALIFIED_COMPACTION_TOKENS
        {
            return Err(QualifiedCompactionError::InvalidTokenLimit);
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
        push_digest(&mut bytes, self.tokenizer_digest);
        push_id(&mut bytes, &self.semantic_compactor_id);
        push_digest(
            &mut bytes,
            self.semantic_compactor_implementation_digest,
        );
        push_u64(&mut bytes, u64::from(self.maximum_retained_records));
        push_u64(&mut bytes, self.maximum_retained_bytes);
        push_u64(&mut bytes, self.maximum_retained_tokens);
        push_len(&mut bytes, protected.len());
        for record_id in protected {
            push_id(&mut bytes, record_id);
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionInputRecordV3 {
    pub record: MemoryRecord,
    pub retention_priority: u32,
    pub retention_reason_digest: Digest32,
    pub encoded_bytes: u64,
    pub token_count: u64,
    pub tokenization_receipt_digest: Digest32,
}

impl CompactionInputRecordV3 {
    fn validate(&self) -> Result<(), QualifiedCompactionError> {
        self.record
            .validate()
            .map_err(|error| QualifiedCompactionError::InvalidRecord(error.to_string()))?;
        ensure_digest("retention_reason", self.retention_reason_digest)?;
        ensure_digest(
            "tokenization_receipt",
            self.tokenization_receipt_digest,
        )?;
        if self.encoded_bytes == 0
            || self.encoded_bytes > MAX_QUALIFIED_COMPACTION_BYTES
            || self.token_count == 0
            || self.token_count > MAX_QUALIFIED_COMPACTION_TOKENS
        {
            return Err(QualifiedCompactionError::InvalidRecordFootprint(
                self.record.record_id.to_string(),
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn semantic_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(INPUT_DOMAIN);
        push_digest(&mut bytes, self.record.record_digest());
        push_u64(&mut bytes, u64::from(self.retention_priority));
        push_digest(&mut bytes, self.retention_reason_digest);
        push_u64(&mut bytes, self.encoded_bytes);
        push_u64(&mut bytes, self.token_count);
        push_digest(&mut bytes, self.tokenization_receipt_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionLossReportV3 {
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

impl CompactionLossReportV3 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        if checked_sum(self.live_source_heads, self.deleted_records)?
            != self.source_current_heads
            || checked_sum(self.retained_records, self.omitted_live_records)?
                != self.live_source_heads
            || checked_sum(self.retained_bytes, self.omitted_live_bytes)?
                != self.live_source_bytes
            || checked_sum(self.retained_tokens, self.omitted_live_tokens)?
                != self.live_source_tokens
        {
            return Err(QualifiedCompactionError::InvalidLossAccounting);
        }
        if self.protected_retained_records != self.protected_live_records
            || checked_sum(
                self.protected_live_records,
                self.protected_deleted_records,
            )? > self.source_current_heads
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
pub struct CompactionPlanV3 {
    pub source_snapshot: CognitiveSnapshotKeyV1,
    pub generation: Generation,
    pub predecessor_checkpoint_digest: Option<Digest32>,
    pub policy: CompactionPolicyV3,
    pub retained_inputs: Vec<CompactionInputRecordV3>,
    pub omitted_inputs: Vec<CompactionInputRecordV3>,
    pub support_manifest_digest: Digest32,
    pub loss_report: CompactionLossReportV3,
    pub plan_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CompactionPlanV3 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        self.source_snapshot
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        self.policy.validate()?;
        self.loss_report.validate()?;
        ensure_digest("support_manifest", self.support_manifest_digest)?;
        if self.authority.grants_any() {
            return Err(QualifiedCompactionError::AuthorityGranted);
        }

        let total = self
            .retained_inputs
            .len()
            .checked_add(self.omitted_inputs.len())
            .ok_or(QualifiedCompactionError::Arithmetic)?;
        if total > MAX_QUALIFIED_COMPACTION_INPUTS {
            return Err(QualifiedCompactionError::InputLimitExceeded);
        }
        let mut all = Vec::with_capacity(total);
        let mut ids = BTreeSet::new();
        for input in self
            .retained_inputs
            .iter()
            .chain(self.omitted_inputs.iter())
        {
            input.validate()?;
            if input.record.state != RecordState::Live {
                return Err(QualifiedCompactionError::TombstoneRetained(
                    input.record.record_id.to_string(),
                ));
            }
            if !ids.insert(input.record.record_id.clone()) {
                return Err(QualifiedCompactionError::DuplicateRetainedRecord(
                    input.record.record_id.to_string(),
                ));
            }
            all.push(input);
        }
        if digest_input_set(SUPPORT_MANIFEST_DOMAIN, all.into_iter())
            != self.support_manifest_digest
        {
            return Err(QualifiedCompactionError::DigestMismatch(
                "support_manifest",
            ));
        }

        let retained_records =
            u64::try_from(self.retained_inputs.len()).map_err(|_| QualifiedCompactionError::Arithmetic)?;
        let omitted_records =
            u64::try_from(self.omitted_inputs.len()).map_err(|_| QualifiedCompactionError::Arithmetic)?;
        let (retained_bytes, retained_tokens) = footprint(&self.retained_inputs)?;
        let (omitted_bytes, omitted_tokens) = footprint(&self.omitted_inputs)?;
        if retained_records != self.loss_report.retained_records
            || omitted_records != self.loss_report.omitted_live_records
            || retained_bytes != self.loss_report.retained_bytes
            || omitted_bytes != self.loss_report.omitted_live_bytes
            || retained_tokens != self.loss_report.retained_tokens
            || omitted_tokens != self.loss_report.omitted_live_tokens
        {
            return Err(QualifiedCompactionError::InvalidLossAccounting);
        }
        if retained_records > u64::from(self.policy.maximum_retained_records)
            || retained_bytes > self.policy.maximum_retained_bytes
            || retained_tokens > self.policy.maximum_retained_tokens
        {
            return Err(QualifiedCompactionError::RetentionBudgetExceeded);
        }
        if self.plan_digest != self.compute_plan_digest() {
            return Err(QualifiedCompactionError::DigestMismatch("plan"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_plan_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(PLAN_DOMAIN);
        push_digest(&mut bytes, self.source_snapshot.vector_digest);
        push_u64(&mut bytes, self.generation.get());
        push_optional_digest(&mut bytes, self.predecessor_checkpoint_digest);
        push_digest(&mut bytes, self.policy.digest());
        push_digest(&mut bytes, self.support_manifest_digest);
        push_digest(&mut bytes, self.loss_report.loss_report_digest);
        push_input_sequence(&mut bytes, &self.retained_inputs);
        push_input_sequence(&mut bytes, &self.omitted_inputs);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticCompactionReceiptV1 {
    pub compactor_id: StableId,
    pub implementation_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub source_manifest_digest: Digest32,
    pub output_digest: Digest32,
    pub output_bytes: u64,
    pub output_tokens: u64,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl SemanticCompactionReceiptV1 {
    pub fn new(
        compactor_id: StableId,
        implementation_digest: Digest32,
        tokenizer_digest: Digest32,
        source_manifest_digest: Digest32,
        output_digest: Digest32,
        output_bytes: u64,
        output_tokens: u64,
    ) -> Result<Self, QualifiedCompactionError> {
        let mut value = Self {
            compactor_id,
            implementation_digest,
            tokenizer_digest,
            source_manifest_digest,
            output_digest,
            output_bytes,
            output_tokens,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.receipt_digest = value.compute_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        for (name, digest) in [
            ("semantic_implementation", self.implementation_digest),
            ("semantic_tokenizer", self.tokenizer_digest),
            ("semantic_source_manifest", self.source_manifest_digest),
            ("semantic_output", self.output_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.output_bytes == 0
            || self.output_bytes > MAX_QUALIFIED_COMPACTION_BYTES
            || self.output_tokens == 0
            || self.output_tokens > MAX_QUALIFIED_COMPACTION_TOKENS
        {
            return Err(QualifiedCompactionError::InvalidSemanticOutputSize);
        }
        if self.authority.grants_any() {
            return Err(QualifiedCompactionError::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_digest() {
            return Err(QualifiedCompactionError::DigestMismatch(
                "semantic_receipt",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(SEMANTIC_RECEIPT_DOMAIN);
        push_id(&mut bytes, &self.compactor_id);
        push_digest(&mut bytes, self.implementation_digest);
        push_digest(&mut bytes, self.tokenizer_digest);
        push_digest(&mut bytes, self.source_manifest_digest);
        push_digest(&mut bytes, self.output_digest);
        push_u64(&mut bytes, self.output_bytes);
        push_u64(&mut bytes, self.output_tokens);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedCompactionCandidateV3 {
    pub source_snapshot: CognitiveSnapshotKeyV1,
    pub plan_digest: Digest32,
    pub policy_digest: Digest32,
    pub retained_records: Vec<MemoryRecord>,
    pub omitted_record_digests: Vec<Digest32>,
    pub semantic_receipt: SemanticCompactionReceiptV1,
    pub checkpoint: CompactCheckpointV1,
    pub loss_report: CompactionLossReportV3,
    pub candidate_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl QualifiedCompactionCandidateV3 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        self.source_snapshot
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        ensure_digest("plan", self.plan_digest)?;
        ensure_digest("policy", self.policy_digest)?;
        self.semantic_receipt.validate()?;
        self.checkpoint
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        self.loss_report.validate()?;
        if self.checkpoint.source_snapshot != self.source_snapshot {
            return Err(QualifiedCompactionError::SnapshotMismatch);
        }
        if self.checkpoint.support_manifest_digest
            != self.semantic_receipt.source_manifest_digest
            || self.checkpoint.payload_digest != self.semantic_receipt.output_digest
        {
            return Err(QualifiedCompactionError::SemanticReceiptMismatch);
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
        push_digest(&mut bytes, self.plan_digest);
        push_digest(&mut bytes, self.policy_digest);
        push_digest(&mut bytes, self.semantic_receipt.receipt_digest);
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
pub struct TrustedCompactionEvaluatorV1 {
    pub evaluator_id: StableId,
    pub implementation_digest: Digest32,
    pub attestation_digest: Digest32,
    pub verifying_key: [u8; 32],
}

impl TrustedCompactionEvaluatorV1 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        ensure_digest("evaluator_implementation", self.implementation_digest)?;
        ensure_digest("evaluator_attestation", self.attestation_digest)?;
        let key = VerifyingKey::from_bytes(&self.verifying_key)
            .map_err(|_| QualifiedCompactionError::InvalidEvaluatorKey)?;
        if key.is_weak() {
            return Err(QualifiedCompactionError::InvalidEvaluatorKey);
        }
        Ok(())
    }

    #[must_use]
    pub fn key_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.verifying_key)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionQualificationV3 {
    pub evaluator_id: StableId,
    pub evaluator_implementation_digest: Digest32,
    pub evaluator_attestation_digest: Digest32,
    pub evaluation_artifact_digest: Digest32,
    pub retained_query_suite_digest: Digest32,
    pub reconstruction_obligation_digest: Digest32,
    pub contradiction_holdout_digest: Digest32,
    pub retained_queries_passed: bool,
    pub reconstruction_passed: bool,
    pub contradictions_preserved: bool,
    pub deletion_non_resurrection_passed: bool,
    pub signature: [u8; 64],
}

impl CompactionQualificationV3 {
    #[must_use]
    pub fn signing_bytes(&self, candidate_digest: Digest32) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(QUALIFICATION_DOMAIN);
        push_digest(&mut bytes, candidate_digest);
        push_id(&mut bytes, &self.evaluator_id);
        for digest in [
            self.evaluator_implementation_digest,
            self.evaluator_attestation_digest,
            self.evaluation_artifact_digest,
            self.retained_query_suite_digest,
            self.reconstruction_obligation_digest,
            self.contradiction_holdout_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        bytes.push(u8::from(self.retained_queries_passed));
        bytes.push(u8::from(self.reconstruction_passed));
        bytes.push(u8::from(self.contradictions_preserved));
        bytes.push(u8::from(self.deletion_non_resurrection_passed));
        bytes
    }

    fn validate_digests(&self) -> Result<(), QualifiedCompactionError> {
        for (name, digest) in [
            (
                "evaluator_implementation",
                self.evaluator_implementation_digest,
            ),
            ("evaluator_attestation", self.evaluator_attestation_digest),
            ("evaluation_artifact", self.evaluation_artifact_digest),
            (
                "retained_query_suite",
                self.retained_query_suite_digest,
            ),
            (
                "reconstruction_obligation",
                self.reconstruction_obligation_digest,
            ),
            (
                "contradiction_holdout",
                self.contradiction_holdout_digest,
            ),
        ] {
            ensure_digest(name, digest)?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionProofV2 {
    pub base_proof: CompactionProofV1,
    pub candidate_digest: Digest32,
    pub evaluator_id: StableId,
    pub evaluator_implementation_digest: Digest32,
    pub evaluator_attestation_digest: Digest32,
    pub evaluation_artifact_digest: Digest32,
    pub evaluator_key_digest: Digest32,
    pub qualification_digest: Digest32,
    pub proof_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CompactionProofV2 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        self.base_proof
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        for (name, digest) in [
            ("proof_candidate", self.candidate_digest),
            (
                "proof_evaluator_implementation",
                self.evaluator_implementation_digest,
            ),
            (
                "proof_evaluator_attestation",
                self.evaluator_attestation_digest,
            ),
            (
                "proof_evaluation_artifact",
                self.evaluation_artifact_digest,
            ),
            ("proof_evaluator_key", self.evaluator_key_digest),
            ("proof_qualification", self.qualification_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.authority.grants_any() {
            return Err(QualifiedCompactionError::AuthorityGranted);
        }
        if self.proof_digest != self.compute_digest() {
            return Err(QualifiedCompactionError::DigestMismatch("proof_v2"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(PROOF_V2_DOMAIN);
        push_digest(&mut bytes, self.base_proof.proof_digest);
        push_digest(&mut bytes, self.candidate_digest);
        push_id(&mut bytes, &self.evaluator_id);
        push_digest(&mut bytes, self.evaluator_implementation_digest);
        push_digest(&mut bytes, self.evaluator_attestation_digest);
        push_digest(&mut bytes, self.evaluation_artifact_digest);
        push_digest(&mut bytes, self.evaluator_key_digest);
        push_digest(&mut bytes, self.qualification_digest);
        Digest32::of_bytes(&bytes)
    }
}

pub fn plan_compaction(
    source_snapshot: CognitiveSnapshotKeyV1,
    generation: Generation,
    predecessor_checkpoint_digest: Option<Digest32>,
    policy: &CompactionPolicyV3,
    inputs: Vec<CompactionInputRecordV3>,
) -> Result<CompactionPlanV3, QualifiedCompactionError> {
    source_snapshot
        .validate()
        .map_err(QualifiedCompactionError::Contract)?;
    policy.validate()?;
    if inputs.len() > MAX_QUALIFIED_COMPACTION_INPUTS {
        return Err(QualifiedCompactionError::InputLimitExceeded);
    }

    let protected = policy
        .protected_record_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    let mut by_record = BTreeMap::<StableId, Vec<CompactionInputRecordV3>>::new();
    for input in inputs {
        input.validate()?;
        by_record
            .entry(input.record.record_id.clone())
            .or_default()
            .push(input);
    }

    let present = by_record.keys().cloned().collect::<BTreeSet<_>>();
    for record_id in &protected {
        if !present.contains(record_id) {
            return Err(QualifiedCompactionError::MissingProtectedReference(
                record_id.to_string(),
            ));
        }
    }

    let mut live_heads = Vec::<CompactionInputRecordV3>::new();
    let mut source_current_heads = 0_u64;
    let mut deleted_records = 0_u64;
    let mut protected_deleted_records = 0_u64;

    for (record_id, mut lineage) in by_record {
        lineage.sort_by_key(|input| input.record.revision);
        validate_lineage(&record_id, &lineage)?;
        let Some(head) = lineage.pop() else {
            return Err(QualifiedCompactionError::EmptyLineage);
        };
        source_current_heads = checked_sum(source_current_heads, 1)?;
        if head.record.state == RecordState::Tombstone {
            deleted_records = checked_sum(deleted_records, 1)?;
            if protected.contains(&record_id) {
                protected_deleted_records =
                    checked_sum(protected_deleted_records, 1)?;
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
    let maximum_records =
        usize::try_from(policy.maximum_retained_records).unwrap_or(usize::MAX);
    if protected_live_records > maximum_records {
        return Err(QualifiedCompactionError::ProtectedReferencesExceedCapacity);
    }

    let mut retained_inputs = Vec::new();
    let mut omitted_inputs = Vec::new();
    let mut retained_bytes = 0_u64;
    let mut retained_tokens = 0_u64;

    for input in live_heads {
        let must_retain = protected.contains(&input.record.record_id);
        let next_records = retained_inputs
            .len()
            .checked_add(1)
            .ok_or(QualifiedCompactionError::Arithmetic)?;
        let next_bytes = checked_sum(retained_bytes, input.encoded_bytes)?;
        let next_tokens = checked_sum(retained_tokens, input.token_count)?;
        let fits = next_records <= maximum_records
            && next_bytes <= policy.maximum_retained_bytes
            && next_tokens <= policy.maximum_retained_tokens;
        if must_retain && !fits {
            return Err(QualifiedCompactionError::ProtectedReferencesExceedBudget);
        }
        if fits {
            retained_bytes = next_bytes;
            retained_tokens = next_tokens;
            retained_inputs.push(input);
        } else {
            omitted_inputs.push(input);
        }
    }

    let mut all_live = retained_inputs.iter().collect::<Vec<_>>();
    all_live.extend(omitted_inputs.iter());
    let support_manifest_digest =
        digest_input_set(SUPPORT_MANIFEST_DOMAIN, all_live.into_iter());

    let live_source_heads =
        u64::try_from(retained_inputs.len() + omitted_inputs.len())
            .map_err(|_| QualifiedCompactionError::Arithmetic)?;
    let retained_count =
        u64::try_from(retained_inputs.len()).map_err(|_| QualifiedCompactionError::Arithmetic)?;
    let omitted_count =
        u64::try_from(omitted_inputs.len()).map_err(|_| QualifiedCompactionError::Arithmetic)?;
    let (omitted_bytes, omitted_tokens) = footprint(&omitted_inputs)?;
    let live_source_bytes = checked_sum(retained_bytes, omitted_bytes)?;
    let live_source_tokens = checked_sum(retained_tokens, omitted_tokens)?;

    let mut loss_report = CompactionLossReportV3 {
        source_current_heads,
        live_source_heads,
        retained_records: retained_count,
        omitted_live_records: omitted_count,
        deleted_records,
        protected_live_records: u64::try_from(protected_live_records)
            .map_err(|_| QualifiedCompactionError::Arithmetic)?,
        protected_retained_records: u64::try_from(protected_live_records)
            .map_err(|_| QualifiedCompactionError::Arithmetic)?,
        protected_deleted_records,
        live_source_bytes,
        retained_bytes,
        omitted_live_bytes: omitted_bytes,
        live_source_tokens,
        retained_tokens,
        omitted_live_tokens: omitted_tokens,
        loss_report_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    loss_report.loss_report_digest = loss_report.compute_digest();
    loss_report.validate()?;

    let mut plan = CompactionPlanV3 {
        source_snapshot,
        generation,
        predecessor_checkpoint_digest,
        policy: policy.clone(),
        retained_inputs,
        omitted_inputs,
        support_manifest_digest,
        loss_report,
        plan_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    plan.plan_digest = plan.compute_plan_digest();
    plan.validate()?;
    Ok(plan)
}

pub fn build_qualified_candidate(
    plan: CompactionPlanV3,
    semantic_receipt: SemanticCompactionReceiptV1,
) -> Result<QualifiedCompactionCandidateV3, QualifiedCompactionError> {
    plan.validate()?;
    semantic_receipt.validate()?;

    if semantic_receipt.compactor_id != plan.policy.semantic_compactor_id
        || semantic_receipt.implementation_digest
            != plan.policy.semantic_compactor_implementation_digest
        || semantic_receipt.tokenizer_digest != plan.policy.tokenizer_digest
        || semantic_receipt.source_manifest_digest != plan.support_manifest_digest
    {
        return Err(QualifiedCompactionError::SemanticReceiptMismatch);
    }
    if semantic_receipt.output_bytes > plan.policy.maximum_retained_bytes
        || semantic_receipt.output_tokens > plan.policy.maximum_retained_tokens
    {
        return Err(QualifiedCompactionError::SemanticOutputBudgetExceeded);
    }

    let retained_records = plan
        .retained_inputs
        .iter()
        .map(|input| input.record.clone())
        .collect::<Vec<_>>();
    let omitted_record_digests = plan
        .omitted_inputs
        .iter()
        .map(|input| input.record.record_digest())
        .collect::<Vec<_>>();
    let omitted_information_digest =
        digest_digests(OMITTED_DOMAIN, &omitted_record_digests);

    let mut checkpoint = CompactCheckpointV1 {
        checkpoint_id: StableId::new(format!("compact:{}", plan.generation.get()))
            .map_err(|_| QualifiedCompactionError::InvalidCheckpointIdentity)?,
        generation: plan.generation,
        source_snapshot: plan.source_snapshot.clone(),
        support_manifest_digest: plan.support_manifest_digest,
        algorithm_digest: plan.policy.algorithm_digest,
        payload_digest: semantic_receipt.output_digest,
        omitted_information_digest,
        tombstone_cutoff: plan.source_snapshot.vector.tombstone_frontier,
        predecessor_digest: plan.predecessor_checkpoint_digest,
        compatibility_digest: plan.policy.compatibility_digest,
        checkpoint_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    checkpoint.checkpoint_digest = checkpoint.compute_checkpoint_digest();
    checkpoint
        .validate()
        .map_err(QualifiedCompactionError::Contract)?;

    let mut candidate = QualifiedCompactionCandidateV3 {
        source_snapshot: plan.source_snapshot,
        plan_digest: plan.plan_digest,
        policy_digest: plan.policy.digest(),
        retained_records,
        omitted_record_digests,
        semantic_receipt,
        checkpoint,
        loss_report: plan.loss_report,
        candidate_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    candidate.candidate_digest = candidate.compute_candidate_digest();
    candidate.validate()?;
    Ok(candidate)
}

pub fn prove_compaction(
    candidate: &QualifiedCompactionCandidateV3,
    evaluator: &TrustedCompactionEvaluatorV1,
    qualification: CompactionQualificationV3,
) -> Result<CompactionProofV2, QualifiedCompactionError> {
    candidate.validate()?;
    evaluator.validate()?;
    qualification.validate_digests()?;

    if qualification.evaluator_id != evaluator.evaluator_id
        || qualification.evaluator_implementation_digest
            != evaluator.implementation_digest
        || qualification.evaluator_attestation_digest != evaluator.attestation_digest
    {
        return Err(QualifiedCompactionError::EvaluatorMismatch);
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

    VerifyingKey::from_bytes(&evaluator.verifying_key)
        .map_err(|_| QualifiedCompactionError::InvalidEvaluatorKey)?
        .verify_strict(
            &qualification.signing_bytes(candidate.candidate_digest),
            &Signature::from_bytes(&qualification.signature),
        )
        .map_err(|_| QualifiedCompactionError::InvalidEvaluatorSignature)?;

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

    let mut qualification_bytes =
        qualification.signing_bytes(candidate.candidate_digest);
    qualification_bytes.extend_from_slice(&qualification.signature);
    let qualification_digest = Digest32::of_bytes(&qualification_bytes);

    let mut proof = CompactionProofV2 {
        base_proof,
        candidate_digest: candidate.candidate_digest,
        evaluator_id: qualification.evaluator_id,
        evaluator_implementation_digest: qualification
            .evaluator_implementation_digest,
        evaluator_attestation_digest: qualification.evaluator_attestation_digest,
        evaluation_artifact_digest: qualification.evaluation_artifact_digest,
        evaluator_key_digest: evaluator.key_digest(),
        qualification_digest,
        proof_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    proof.proof_digest = proof.compute_digest();
    proof.validate()?;
    Ok(proof)
}

fn validate_lineage(
    record_id: &StableId,
    lineage: &[CompactionInputRecordV3],
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
                if record.revision.get()
                    != previous.revision.get().saturating_add(1)
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

fn footprint(
    inputs: &[CompactionInputRecordV3],
) -> Result<(u64, u64), QualifiedCompactionError> {
    let mut bytes = 0_u64;
    let mut tokens = 0_u64;
    for input in inputs {
        bytes = checked_sum(bytes, input.encoded_bytes)?;
        tokens = checked_sum(tokens, input.token_count)?;
    }
    Ok((bytes, tokens))
}

fn digest_input_set<'a>(
    domain: &[u8],
    inputs: impl IntoIterator<Item = &'a CompactionInputRecordV3>,
) -> Digest32 {
    let mut digests = inputs
        .into_iter()
        .map(CompactionInputRecordV3::semantic_digest)
        .collect::<Vec<_>>();
    digests.sort();
    digest_digests(domain, &digests)
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

fn push_input_sequence(bytes: &mut Vec<u8>, values: &[CompactionInputRecordV3]) {
    push_len(bytes, values.len());
    for value in values {
        push_digest(bytes, value.semantic_digest());
    }
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

fn checked_sum(left: u64, right: u64) -> Result<u64, QualifiedCompactionError> {
    left.checked_add(right)
        .ok_or(QualifiedCompactionError::Arithmetic)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QualifiedCompactionError {
    Contract(LaneCContractError),
    EmptyDigest(&'static str),
    DigestMismatch(&'static str),
    InvalidRetentionLimit,
    InvalidByteLimit,
    InvalidTokenLimit,
    InputLimitExceeded,
    ProtectedReferenceLimitExceeded,
    DuplicateProtectedReference(String),
    MissingProtectedReference(String),
    ProtectedReferencesExceedCapacity,
    ProtectedReferencesExceedBudget,
    ProtectedReferenceLost,
    RetentionBudgetExceeded,
    InvalidLossAccounting,
    InvalidRecord(String),
    InvalidRecordFootprint(String),
    EmptyLineage,
    BrokenLineage(String),
    ResurrectionDenied(String),
    TombstoneRetained(String),
    DuplicateRetainedRecord(String),
    SnapshotMismatch,
    InvalidCheckpointIdentity,
    InvalidSemanticOutputSize,
    SemanticOutputBudgetExceeded,
    SemanticReceiptMismatch,
    InvalidEvaluatorKey,
    InvalidEvaluatorSignature,
    EvaluatorMismatch,
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

fn ensure_digest(
    name: &'static str,
    digest: Digest32,
) -> Result<(), QualifiedCompactionError> {
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

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_digest(bytes, value);
        }
        None => bytes.push(0),
    }
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
