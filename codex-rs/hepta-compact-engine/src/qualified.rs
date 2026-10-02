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

use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
use codex_hepta_cognitive_types::lane_c::CompactionProofV2;
use codex_hepta_cognitive_types::lane_c::CompactionProofWitnessV1;
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
const POLICY_DOMAIN: &[u8] = b"hepta.compaction-policy.v2";
const CANDIDATE_DOMAIN: &[u8] = b"hepta.compaction-candidate.v2";
const SEMANTIC_PAYLOAD_DOMAIN: &[u8] = b"hepta.compaction-semantic-payload.v2";
const INPUT_DOMAIN: &[u8] = b"hepta.compaction-input.v2";
const SUPPORT_MANIFEST_DOMAIN: &[u8] = b"hepta.compaction-support-manifest.v2";
const OMITTED_DOMAIN: &[u8] = b"hepta.compaction-omitted.v2";
const LOSS_REPORT_DOMAIN: &[u8] = b"hepta.compaction-loss-report.v2";
const TOKENIZATION_RECEIPT_DOMAIN: &[u8] = b"hepta.compaction-tokenization-receipt.v1";
const QUALIFICATION_DOMAIN: &[u8] = b"hepta.compaction-qualification.v3";
const VERIFICATION_RECEIPT_DOMAIN: &[u8] = b"hepta.compaction-signature-verification.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionPolicyV2 {
    pub policy_id: StableId,
    pub algorithm_digest: Digest32,
    pub compatibility_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub tokenizer_implementation_digest: Digest32,
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
        ensure_digest("tokenizer", self.tokenizer_digest)?;
        ensure_digest(
            "tokenizer_implementation",
            self.tokenizer_implementation_digest,
        )?;
        let maximum = usize::try_from(self.maximum_retained_records).unwrap_or(usize::MAX);
        if maximum == 0 || maximum > MAX_QUALIFIED_COMPACTION_INPUTS {
            return Err(QualifiedCompactionError::InvalidRetentionLimit);
        }
        if self.maximum_retained_bytes == 0
            || self.maximum_retained_bytes > MAX_QUALIFIED_COMPACTION_BYTES
            || self.maximum_retained_tokens == 0
            || self.maximum_retained_tokens > MAX_QUALIFIED_COMPACTION_TOKENS
            || self.maximum_payload_bytes == 0
            || self.maximum_payload_bytes > MAX_QUALIFIED_COMPACTION_BYTES
            || self.maximum_payload_tokens == 0
            || self.maximum_payload_tokens > MAX_QUALIFIED_COMPACTION_TOKENS
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
        push_digest(&mut bytes, self.tokenizer_digest);
        push_digest(&mut bytes, self.tokenizer_implementation_digest);
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedTokenizerV1 {
    pub tokenizer_digest: Digest32,
    pub implementation_digest: Digest32,
    pub attestation_digest: Digest32,
    pub verifying_key: [u8; 32],
}

impl TrustedTokenizerV1 {
    pub fn validate(
        &self,
        source_snapshot: &CognitiveSnapshotKeyV1,
        policy: &CompactionPolicyV2,
    ) -> Result<(), QualifiedCompactionError> {
        for (name, digest) in [
            ("trusted_tokenizer", self.tokenizer_digest),
            (
                "trusted_tokenizer_implementation",
                self.implementation_digest,
            ),
            ("trusted_tokenizer_attestation", self.attestation_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.tokenizer_digest != source_snapshot.vector.tokenizer_digest
            || self.tokenizer_digest != policy.tokenizer_digest
            || self.implementation_digest != policy.tokenizer_implementation_digest
        {
            return Err(QualifiedCompactionError::TokenizerMismatch);
        }
        let key = VerifyingKey::from_bytes(&self.verifying_key)
            .map_err(|_| QualifiedCompactionError::InvalidTokenizerKey)?;
        if key.is_weak() {
            return Err(QualifiedCompactionError::InvalidTokenizerKey);
        }
        Ok(())
    }

    #[must_use]
    pub fn key_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.verifying_key)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TokenizationReceiptV1 {
    pub subject_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub tokenizer_implementation_digest: Digest32,
    pub encoded_bytes: u64,
    pub token_count: u64,
    pub signature: [u8; 64],
}

impl TokenizationReceiptV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(TOKENIZATION_RECEIPT_DOMAIN);
        push_digest(&mut bytes, self.subject_digest);
        push_digest(&mut bytes, self.tokenizer_digest);
        push_digest(&mut bytes, self.tokenizer_implementation_digest);
        push_u64(&mut bytes, self.encoded_bytes);
        push_u64(&mut bytes, self.token_count);
        bytes
    }

    #[must_use]
    pub fn receipt_digest(&self) -> Digest32 {
        let mut bytes = self.signing_bytes();
        bytes.extend_from_slice(&self.signature);
        Digest32::of_bytes(&bytes)
    }

    fn verify(
        &self,
        trusted: &TrustedTokenizerV1,
        expected_subject: Digest32,
    ) -> Result<(), QualifiedCompactionError> {
        for (name, digest) in [
            ("tokenization_subject", self.subject_digest),
            ("tokenization_tokenizer", self.tokenizer_digest),
            (
                "tokenization_tokenizer_implementation",
                self.tokenizer_implementation_digest,
            ),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.subject_digest != expected_subject {
            return Err(QualifiedCompactionError::TokenizationSubjectMismatch);
        }
        if self.tokenizer_digest != trusted.tokenizer_digest
            || self.tokenizer_implementation_digest != trusted.implementation_digest
        {
            return Err(QualifiedCompactionError::TokenizerMismatch);
        }
        if self.encoded_bytes == 0
            || self.encoded_bytes > MAX_QUALIFIED_COMPACTION_BYTES
            || self.token_count == 0
            || self.token_count > MAX_QUALIFIED_COMPACTION_TOKENS
        {
            return Err(QualifiedCompactionError::InvalidTokenizationCost);
        }
        VerifyingKey::from_bytes(&trusted.verifying_key)
            .map_err(|_| QualifiedCompactionError::InvalidTokenizerKey)?
            .verify_strict(
                &self.signing_bytes(),
                &Signature::from_bytes(&self.signature),
            )
            .map_err(|_| QualifiedCompactionError::InvalidTokenizerSignature)
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
    pub tokenization_receipt: TokenizationReceiptV1,
}

impl CompactionInputRecordV2 {
    fn validate(&self, tokenizer: &TrustedTokenizerV1) -> Result<(), QualifiedCompactionError> {
        self.record
            .validate()
            .map_err(|error| QualifiedCompactionError::InvalidRecord(error.to_string()))?;
        ensure_digest("retention_reason", self.retention_reason_digest)?;
        if self.encoded_bytes == 0
            || self.encoded_bytes > MAX_QUALIFIED_COMPACTION_BYTES
            || self.token_count == 0
            || self.token_count > MAX_QUALIFIED_COMPACTION_TOKENS
        {
            return Err(QualifiedCompactionError::InvalidInputCost(
                self.record.record_id.to_string(),
            ));
        }
        self.tokenization_receipt
            .verify(tokenizer, self.record.record_digest())?;
        if self.tokenization_receipt.encoded_bytes != self.encoded_bytes
            || self.tokenization_receipt.token_count != self.token_count
        {
            return Err(QualifiedCompactionError::TokenizationCostMismatch);
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
        push_digest(&mut bytes, self.tokenization_receipt.receipt_digest());
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
    pub source_memory_snapshot_digest: Digest32,
    pub payload_digest: Digest32,
    pub payload: Vec<u8>,
    pub generator_implementation_digest: Digest32,
    pub generator_receipt_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub encoded_bytes: u64,
    pub token_count: u64,
    pub tokenization_receipt: TokenizationReceiptV1,
}

impl CompactionSemanticPayloadV2 {
    pub fn validate_shape(
        &self,
        source_snapshot: &CognitiveSnapshotKeyV1,
        source_memory_snapshot_digest: Digest32,
        policy: &CompactionPolicyV2,
    ) -> Result<(), QualifiedCompactionError> {
        for (name, digest) in [
            ("semantic_source_snapshot", self.source_snapshot_digest),
            (
                "semantic_source_memory_snapshot",
                self.source_memory_snapshot_digest,
            ),
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
        if self.source_memory_snapshot_digest != source_memory_snapshot_digest {
            return Err(QualifiedCompactionError::SemanticMemorySnapshotMismatch);
        }
        if self.tokenizer_digest != source_snapshot.vector.tokenizer_digest
            || self.tokenizer_digest != policy.tokenizer_digest
        {
            return Err(QualifiedCompactionError::TokenizerMismatch);
        }
        if Digest32::of_bytes(&self.payload) != self.payload_digest
            || u64::try_from(self.payload.len()).unwrap_or(u64::MAX) != self.encoded_bytes
        {
            return Err(QualifiedCompactionError::SemanticPayloadDigestMismatch);
        }
        if self.encoded_bytes == 0 || self.token_count == 0 {
            return Err(QualifiedCompactionError::InvalidSemanticPayloadCost);
        }
        if self.tokenization_receipt.subject_digest != self.payload_digest
            || self.tokenization_receipt.tokenizer_digest != self.tokenizer_digest
            || self.tokenization_receipt.encoded_bytes != self.encoded_bytes
            || self.tokenization_receipt.token_count != self.token_count
        {
            return Err(QualifiedCompactionError::TokenizationCostMismatch);
        }
        if self.encoded_bytes > policy.maximum_payload_bytes
            || self.token_count > policy.maximum_payload_tokens
        {
            return Err(QualifiedCompactionError::PayloadBudgetExceeded);
        }
        Ok(())
    }

    pub fn verify_tokenization(
        &self,
        trusted_tokenizer: &TrustedTokenizerV1,
    ) -> Result<(), QualifiedCompactionError> {
        self.tokenization_receipt
            .verify(trusted_tokenizer, self.payload_digest)
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(SEMANTIC_PAYLOAD_DOMAIN);
        push_digest(&mut bytes, self.source_snapshot_digest);
        push_digest(&mut bytes, self.source_memory_snapshot_digest);
        push_digest(&mut bytes, self.payload_digest);
        push_digest(&mut bytes, self.generator_implementation_digest);
        push_digest(&mut bytes, self.generator_receipt_digest);
        push_digest(&mut bytes, self.tokenizer_digest);
        push_u64(&mut bytes, self.encoded_bytes);
        push_u64(&mut bytes, self.token_count);
        push_digest(&mut bytes, self.tokenization_receipt.receipt_digest());
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
    source_snapshot: CognitiveSnapshotKeyV1,
    source_memory_snapshot_digest: Digest32,
    policy: CompactionPolicyV2,
    semantic_payload: CompactionSemanticPayloadV2,
    tokenizer_attestation_digest: Digest32,
    tokenizer_key_digest: Digest32,
    retained_records: Vec<MemoryRecord>,
    retained_input_digests: Vec<Digest32>,
    omitted_input_digests: Vec<Digest32>,
    deleted_input_digests: Vec<Digest32>,
    checkpoint: CompactCheckpointV1,
    loss_report: CompactionLossReportV2,
    candidate_digest: Digest32,
    authority: AuthorityPosture,
}

impl QualifiedCompactionCandidateV2 {
    #[must_use]
    pub fn source_snapshot(&self) -> &CognitiveSnapshotKeyV1 {
        &self.source_snapshot
    }

    #[must_use]
    pub fn source_memory_snapshot_digest(&self) -> Digest32 {
        self.source_memory_snapshot_digest
    }

    #[must_use]
    pub fn policy(&self) -> &CompactionPolicyV2 {
        &self.policy
    }

    #[must_use]
    pub fn semantic_payload(&self) -> &CompactionSemanticPayloadV2 {
        &self.semantic_payload
    }

    #[must_use]
    pub fn retained_records(&self) -> &[MemoryRecord] {
        &self.retained_records
    }

    #[must_use]
    pub fn checkpoint(&self) -> &CompactCheckpointV1 {
        &self.checkpoint
    }

    #[must_use]
    pub fn loss_report(&self) -> &CompactionLossReportV2 {
        &self.loss_report
    }

    #[must_use]
    pub fn candidate_digest(&self) -> Digest32 {
        self.candidate_digest
    }

    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        self.source_snapshot
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        self.policy.validate()?;
        ensure_digest("source_memory_snapshot", self.source_memory_snapshot_digest)?;
        ensure_digest(
            "candidate_tokenizer_attestation",
            self.tokenizer_attestation_digest,
        )?;
        ensure_digest("candidate_tokenizer_key", self.tokenizer_key_digest)?;
        // Signature verification occurs during construction against the host-trusted
        // tokenizer. Candidate revalidation remains structural/digest-only.
        self.semantic_payload.validate_shape(
            &self.source_snapshot,
            self.source_memory_snapshot_digest,
            &self.policy,
        )?;
        self.checkpoint
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        self.loss_report.validate()?;
        if self.checkpoint.source_snapshot != self.source_snapshot {
            return Err(QualifiedCompactionError::SnapshotMismatch);
        }
        if self.checkpoint.source_memory_snapshot_digest != self.source_memory_snapshot_digest {
            return Err(QualifiedCompactionError::SourceMemorySnapshotMismatch);
        }
        if self
            .source_snapshot
            .vector
            .compact_checkpoint_generation
            .next()
            .ok()
            != Some(self.checkpoint.generation)
        {
            return Err(QualifiedCompactionError::CheckpointGenerationMismatch);
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
            || self.loss_report.deleted_records
                != u64::try_from(self.deleted_input_digests.len()).unwrap_or(u64::MAX)
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
        all_inputs.extend_from_slice(&self.deleted_input_digests);
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
        push_digest(&mut bytes, self.source_memory_snapshot_digest);
        push_digest(&mut bytes, self.policy.digest());
        push_digest(&mut bytes, self.semantic_payload.digest());
        push_digest(&mut bytes, self.tokenizer_attestation_digest);
        push_digest(&mut bytes, self.tokenizer_key_digest);
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
        push_len(&mut bytes, self.deleted_input_digests.len());
        for digest in &self.deleted_input_digests {
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
pub struct CompactionQualificationV2 {
    pub tokenizer_implementation_digest: Digest32,
    pub tokenizer_attestation_digest: Digest32,
    pub tokenizer_key_digest: Digest32,
    pub evaluator_id: StableId,
    pub evaluator_implementation_digest: Digest32,
    pub evaluation_artifact_digest: Digest32,
    pub attestation_digest: Digest32,
    pub retained_query_suite_digest: Digest32,
    pub reconstruction_obligation_digest: Digest32,
    pub contradiction_holdout_digest: Digest32,
    pub retained_queries_passed: bool,
    pub reconstruction_passed: bool,
    pub contradictions_preserved: bool,
    pub deletion_non_resurrection_passed: bool,
    pub signature: [u8; 64],
}

impl CompactionQualificationV2 {
    #[must_use]
    pub fn signing_bytes(&self, candidate_digest: Digest32) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(QUALIFICATION_DOMAIN);
        push_digest(&mut bytes, candidate_digest);
        push_digest(&mut bytes, self.tokenizer_implementation_digest);
        push_digest(&mut bytes, self.tokenizer_attestation_digest);
        push_digest(&mut bytes, self.tokenizer_key_digest);
        push_id(&mut bytes, &self.evaluator_id);
        for digest in [
            self.evaluator_implementation_digest,
            self.evaluation_artifact_digest,
            self.attestation_digest,
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
                "qualification_tokenizer_implementation",
                self.tokenizer_implementation_digest,
            ),
            (
                "qualification_tokenizer_attestation",
                self.tokenizer_attestation_digest,
            ),
            ("qualification_tokenizer_key", self.tokenizer_key_digest),
            (
                "evaluator_implementation",
                self.evaluator_implementation_digest,
            ),
            ("evaluation_artifact", self.evaluation_artifact_digest),
            ("attestation", self.attestation_digest),
            ("retained_query_suite", self.retained_query_suite_digest),
            (
                "reconstruction_obligation",
                self.reconstruction_obligation_digest,
            ),
            ("contradiction_holdout", self.contradiction_holdout_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        Ok(())
    }
}

pub fn build_qualified_candidate(
    source_snapshot: CognitiveSnapshotKeyV1,
    source_memory_snapshot: &CognitiveSnapshot,
    generation: Generation,
    predecessor_checkpoint_digest: Option<Digest32>,
    policy: &CompactionPolicyV2,
    semantic_payload: &CompactionSemanticPayloadV2,
    trusted_tokenizer: &TrustedTokenizerV1,
    inputs: Vec<CompactionInputRecordV2>,
) -> Result<QualifiedCompactionCandidateV2, QualifiedCompactionError> {
    source_snapshot
        .validate()
        .map_err(QualifiedCompactionError::Contract)?;
    source_memory_snapshot
        .validate_integrity()
        .map_err(|error| QualifiedCompactionError::InvalidSourceSnapshot(error.to_string()))?;
    policy.validate()?;
    trusted_tokenizer.validate(&source_snapshot, policy)?;
    semantic_payload.validate_shape(
        &source_snapshot,
        source_memory_snapshot.snapshot_digest,
        policy,
    )?;
    semantic_payload.verify_tokenization(trusted_tokenizer)?;
    if inputs.len() > MAX_QUALIFIED_COMPACTION_INPUTS {
        return Err(QualifiedCompactionError::InputLimitExceeded);
    }

    let mut snapshot_heads = BTreeMap::<StableId, MemoryRecord>::new();
    for record in &source_memory_snapshot.records {
        if snapshot_heads
            .insert(record.record_id.clone(), record.clone())
            .is_some()
        {
            return Err(QualifiedCompactionError::SourceSnapshotNotHeadOnly(
                record.record_id.to_string(),
            ));
        }
    }

    let mut by_record = BTreeMap::<StableId, Vec<CompactionInputRecordV2>>::new();
    for input in inputs {
        input.validate(trusted_tokenizer)?;
        by_record
            .entry(input.record.record_id.clone())
            .or_default()
            .push(input);
    }

    if by_record.len() != snapshot_heads.len()
        || by_record
            .keys()
            .any(|record_id| !snapshot_heads.contains_key(record_id))
    {
        return Err(QualifiedCompactionError::SourceSnapshotCoverageMismatch);
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
    let mut deleted_input_digests = Vec::<Digest32>::new();
    let mut source_current_heads = 0_u64;
    let mut deleted_records = 0_u64;
    let mut protected_deleted_records = 0_u64;

    for (record_id, mut lineage) in by_record {
        lineage.sort_by_key(|input| input.record.revision);
        validate_lineage(&record_id, &lineage)?;
        let Some(head) = lineage.pop() else {
            return Err(QualifiedCompactionError::EmptyLineage);
        };
        if snapshot_heads.get(&record_id) != Some(&head.record) {
            return Err(QualifiedCompactionError::SourceSnapshotRecordMismatch(
                record_id.to_string(),
            ));
        }
        source_current_heads = checked_add(source_current_heads, 1)?;
        if head.record.state == RecordState::Tombstone {
            deleted_input_digests.push(head.digest());
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
    support_digests.extend_from_slice(&deleted_input_digests);
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
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
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
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
        policy: policy.clone(),
        semantic_payload: semantic_payload.clone(),
        tokenizer_attestation_digest: trusted_tokenizer.attestation_digest,
        tokenizer_key_digest: trusted_tokenizer.key_digest(),
        retained_records,
        retained_input_digests,
        omitted_input_digests,
        deleted_input_digests,
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
    evaluator: &TrustedCompactionEvaluatorV1,
    qualification: CompactionQualificationV2,
) -> Result<CompactionProofV2, QualifiedCompactionError> {
    candidate.validate()?;
    evaluator.validate()?;
    qualification.validate_digests()?;
    if qualification.tokenizer_implementation_digest
        != candidate.policy.tokenizer_implementation_digest
        || qualification.tokenizer_attestation_digest != candidate.tokenizer_attestation_digest
        || qualification.tokenizer_key_digest != candidate.tokenizer_key_digest
    {
        return Err(QualifiedCompactionError::TokenizerMismatch);
    }
    if qualification.evaluator_id != evaluator.evaluator_id
        || qualification.evaluator_implementation_digest != evaluator.implementation_digest
        || qualification.attestation_digest != evaluator.attestation_digest
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

    let proof_witness = CompactionProofWitnessV1 {
        evaluator_verifying_key: evaluator.verifying_key,
        qualification_signature: qualification.signature,
    };
    let attestation_signature_digest = Digest32::of_bytes(&proof_witness.qualification_signature);
    let signature_verification_receipt_digest = proof_witness.verification_receipt_digest(
        candidate.candidate_digest,
        evaluator.implementation_digest,
        evaluator.attestation_digest,
    );

    let mut proof = CompactionProofV2 {
        checkpoint_digest: candidate.checkpoint.checkpoint_digest,
        candidate_digest: candidate.candidate_digest,
        tokenizer_implementation_digest: qualification.tokenizer_implementation_digest,
        tokenizer_attestation_digest: qualification.tokenizer_attestation_digest,
        tokenizer_key_digest: qualification.tokenizer_key_digest,
        evaluator_id: qualification.evaluator_id,
        evaluator_implementation_digest: qualification.evaluator_implementation_digest,
        evaluation_artifact_digest: qualification.evaluation_artifact_digest,
        attestation_digest: qualification.attestation_digest,
        attestation_signature_digest,
        signature_verification_receipt_digest,
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
    proof_witness
        .verify_proof(&proof)
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
    InvalidSourceSnapshot(String),
    SourceSnapshotNotHeadOnly(String),
    SourceSnapshotCoverageMismatch,
    SourceSnapshotRecordMismatch(String),
    InvalidInputCost(String),
    InvalidTokenizationCost,
    InvalidTokenizerKey,
    InvalidTokenizerSignature,
    TokenizationSubjectMismatch,
    TokenizationCostMismatch,
    InvalidSemanticPayloadCost,
    SemanticPayloadDigestMismatch,
    PayloadBudgetExceeded,
    RetentionBudgetExceeded,
    EmptyLineage,
    BrokenLineage(String),
    ResurrectionDenied(String),
    TombstoneRetained(String),
    DuplicateRetainedRecord(String),
    SnapshotMismatch,
    CheckpointGenerationMismatch,
    SemanticSnapshotMismatch,
    SemanticMemorySnapshotMismatch,
    SourceMemorySnapshotMismatch,
    TokenizerMismatch,
    PolicyCheckpointMismatch,
    SemanticPayloadMismatch,
    InvalidCheckpointIdentity,
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
