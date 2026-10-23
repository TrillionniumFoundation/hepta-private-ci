//! Versioned, signed trust admission for canonical compaction.
//!
//! The pure selection/proof kernel remains authority-free. This module is the
//! only public construction boundary and requires independently enrolled
//! selector, semantic-generator, tokenizer and evaluator identities. Receipts
//! bind key id, trust epoch, validity, anti-replay nonce and exact subject
//! digests before the lower-level kernel can be reached.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::CompactionProofV2;
use codex_hepta_cognitive_types::lane_c::CompactionProofWitnessV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::qualified;
use crate::qualified::CompactionInputRecordV2;
use crate::qualified::CompactionPolicyV2;
use crate::qualified::CompactionQualificationV2;
use crate::qualified::CompactionSemanticPayloadV2;
use crate::qualified::QualifiedCompactionCandidateV2;
use crate::qualified::QualifiedCompactionError;

pub const COMPACTION_TRUST_SCHEMA_VERSION: u32 = 1;
const TRUST_ENROLLMENT_DOMAIN: &[u8] = b"hepta.compaction.trust-enrollment.v1";
const SELECTION_RECEIPT_DOMAIN: &[u8] = b"hepta.compaction.selection-receipt.v1";
const GENERATION_RECEIPT_DOMAIN: &[u8] = b"hepta.compaction.generation-receipt.v1";
const EVALUATION_RECEIPT_DOMAIN: &[u8] = b"hepta.compaction.evaluation-receipt.v1";
const INPUT_MANIFEST_DOMAIN: &[u8] = b"hepta.compaction.input-manifest.v1";
const QUALIFICATION_DIGEST_DOMAIN: &[u8] = b"hepta.compaction.qualification-digest.v1";

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CompactionTrustRoleV1 {
    RetentionSelector,
    SemanticGenerator,
    Tokenizer,
    Evaluator,
}

impl CompactionTrustRoleV1 {
    fn tag(self) -> &'static [u8] {
        match self {
            Self::RetentionSelector => b"retention-selector",
            Self::SemanticGenerator => b"semantic-generator",
            Self::Tokenizer => b"tokenizer",
            Self::Evaluator => b"evaluator",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustEnrollmentV1 {
    pub schema_version: u32,
    pub role: CompactionTrustRoleV1,
    pub key_id: StableId,
    pub trust_epoch: u64,
    pub valid_from_unix_seconds: u64,
    pub valid_until_unix_seconds: u64,
    pub revoked_at_unix_seconds: Option<u64>,
    pub predecessor_key_digest: Option<Digest32>,
    pub implementation_digest: Digest32,
    pub attestation_digest: Digest32,
    pub verifying_key: [u8; 32],
}

impl TrustEnrollmentV1 {
    pub fn validate(&self) -> Result<(), TrustedCompactionError> {
        if self.schema_version != COMPACTION_TRUST_SCHEMA_VERSION {
            return Err(TrustedCompactionError::InvalidSchemaVersion);
        }
        if self.trust_epoch == 0
            || self.valid_until_unix_seconds <= self.valid_from_unix_seconds
        {
            return Err(TrustedCompactionError::InvalidTrustInterval);
        }
        ensure_digest("trust implementation", self.implementation_digest)?;
        ensure_digest("trust attestation", self.attestation_digest)?;
        if let Some(predecessor) = self.predecessor_key_digest {
            ensure_digest("predecessor key", predecessor)?;
        }
        if self
            .revoked_at_unix_seconds
            .is_some_and(|value| value < self.valid_from_unix_seconds)
        {
            return Err(TrustedCompactionError::InvalidTrustInterval);
        }
        let key = VerifyingKey::from_bytes(&self.verifying_key)
            .map_err(|_| TrustedCompactionError::InvalidTrustKey)?;
        if key.is_weak() {
            return Err(TrustedCompactionError::InvalidTrustKey);
        }
        Ok(())
    }

    #[must_use]
    pub fn key_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.verifying_key)
    }

    #[must_use]
    pub fn identity_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(TRUST_ENROLLMENT_DOMAIN);
        push_u32(&mut bytes, self.schema_version);
        bytes.extend_from_slice(self.role.tag());
        push_id(&mut bytes, &self.key_id);
        push_u64(&mut bytes, self.trust_epoch);
        push_u64(&mut bytes, self.valid_from_unix_seconds);
        push_u64(&mut bytes, self.valid_until_unix_seconds);
        match self.revoked_at_unix_seconds {
            Some(value) => {
                bytes.push(1);
                push_u64(&mut bytes, value);
            }
            None => bytes.push(0),
        }
        match self.predecessor_key_digest {
            Some(value) => {
                bytes.push(1);
                push_digest(&mut bytes, value);
            }
            None => bytes.push(0),
        }
        push_digest(&mut bytes, self.implementation_digest);
        push_digest(&mut bytes, self.attestation_digest);
        bytes.extend_from_slice(&self.verifying_key);
        Digest32::of_bytes(&bytes)
    }

    pub fn validate_current_at(&self, now: u64) -> Result<(), TrustedCompactionError> {
        self.validate()?;
        if now < self.valid_from_unix_seconds {
            return Err(TrustedCompactionError::TrustNotYetValid);
        }
        if now >= self.valid_until_unix_seconds {
            return Err(TrustedCompactionError::TrustExpired);
        }
        if self
            .revoked_at_unix_seconds
            .is_some_and(|revoked_at| revoked_at <= now)
        {
            return Err(TrustedCompactionError::TrustRevoked);
        }
        Ok(())
    }

    pub fn validate_historical_at(
        &self,
        accepted_at: u64,
    ) -> Result<(), TrustedCompactionError> {
        self.validate_current_at(accepted_at)
    }

    pub fn validate_rotation_from(
        &self,
        predecessor: &Self,
    ) -> Result<(), TrustedCompactionError> {
        self.validate()?;
        predecessor.validate()?;
        if self.role != predecessor.role
            || self.trust_epoch <= predecessor.trust_epoch
            || self.predecessor_key_digest != Some(predecessor.key_digest())
            || self.key_digest() == predecessor.key_digest()
        {
            return Err(TrustedCompactionError::InvalidTrustRotation);
        }
        Ok(())
    }

    fn validate_role(
        &self,
        expected: CompactionTrustRoleV1,
    ) -> Result<(), TrustedCompactionError> {
        self.validate()?;
        if self.role != expected {
            return Err(TrustedCompactionError::WrongTrustRole);
        }
        Ok(())
    }

    fn validate_current_receipt(
        &self,
        issued_at: u64,
        expires_at: u64,
        verification_time: u64,
    ) -> Result<(), TrustedCompactionError> {
        self.validate()?;
        if issued_at < self.valid_from_unix_seconds
            || issued_at >= self.valid_until_unix_seconds
            || expires_at <= issued_at
            || expires_at > self.valid_until_unix_seconds
            || verification_time < issued_at
        {
            return Err(TrustedCompactionError::InvalidReceiptInterval);
        }
        if verification_time >= expires_at {
            return Err(TrustedCompactionError::ReceiptExpired);
        }
        if self
            .revoked_at_unix_seconds
            .is_some_and(|revoked_at| revoked_at <= verification_time)
        {
            return Err(TrustedCompactionError::TrustRevoked);
        }
        Ok(())
    }

    fn validate_historical_receipt(
        &self,
        issued_at: u64,
        expires_at: u64,
        accepted_at: u64,
    ) -> Result<(), TrustedCompactionError> {
        self.validate()?;
        if issued_at < self.valid_from_unix_seconds
            || issued_at >= self.valid_until_unix_seconds
            || expires_at <= issued_at
            || expires_at > self.valid_until_unix_seconds
            || accepted_at < issued_at
            || accepted_at >= expires_at
        {
            return Err(TrustedCompactionError::InvalidReceiptInterval);
        }
        if self
            .revoked_at_unix_seconds
            .is_some_and(|revoked_at| revoked_at <= accepted_at)
        {
            return Err(TrustedCompactionError::TrustRevoked);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedRetentionSelectorV1 {
    pub enrollment: TrustEnrollmentV1,
}

impl TrustedRetentionSelectorV1 {
    pub fn validate(&self) -> Result<(), TrustedCompactionError> {
        self.enrollment
            .validate_role(CompactionTrustRoleV1::RetentionSelector)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedSemanticGeneratorV1 {
    pub enrollment: TrustEnrollmentV1,
}

impl TrustedSemanticGeneratorV1 {
    pub fn validate(&self) -> Result<(), TrustedCompactionError> {
        self.enrollment
            .validate_role(CompactionTrustRoleV1::SemanticGenerator)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedTokenizerV1 {
    pub enrollment: TrustEnrollmentV1,
    pub tokenizer_digest: Digest32,
}

impl TrustedTokenizerV1 {
    pub fn validate(&self) -> Result<(), TrustedCompactionError> {
        self.enrollment
            .validate_role(CompactionTrustRoleV1::Tokenizer)?;
        ensure_digest("trusted tokenizer", self.tokenizer_digest)
    }

    pub fn validate_current_at(&self, now: u64) -> Result<(), TrustedCompactionError> {
        self.validate()?;
        self.enrollment.validate_current_at(now)
    }

    pub fn validate_historical_at(
        &self,
        accepted_at: u64,
    ) -> Result<(), TrustedCompactionError> {
        self.validate()?;
        self.enrollment.validate_historical_at(accepted_at)
    }

    fn kernel(&self) -> qualified::TrustedTokenizerV1 {
        qualified::TrustedTokenizerV1 {
            tokenizer_digest: self.tokenizer_digest,
            implementation_digest: self.enrollment.implementation_digest,
            attestation_digest: self.enrollment.attestation_digest,
            verifying_key: self.enrollment.verifying_key,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedCompactionEvaluatorV1 {
    pub enrollment: TrustEnrollmentV1,
    pub evaluator_id: StableId,
}

impl TrustedCompactionEvaluatorV1 {
    pub fn validate(&self) -> Result<(), TrustedCompactionError> {
        self.enrollment
            .validate_role(CompactionTrustRoleV1::Evaluator)
    }

    fn kernel(&self) -> qualified::TrustedCompactionEvaluatorV1 {
        qualified::TrustedCompactionEvaluatorV1 {
            evaluator_id: self.evaluator_id.clone(),
            implementation_digest: self.enrollment.implementation_digest,
            attestation_digest: self.enrollment.attestation_digest,
            verifying_key: self.enrollment.verifying_key,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedRetentionSelectionReceiptV1 {
    pub schema_version: u32,
    pub key_id: StableId,
    pub trust_epoch: u64,
    pub issued_at_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    pub nonce: Digest32,
    pub source_snapshot_digest: Digest32,
    pub source_memory_snapshot_digest: Digest32,
    pub policy_digest: Digest32,
    pub input_manifest_digest: Digest32,
    pub tokenizer_key_id: StableId,
    pub tokenizer_trust_epoch: u64,
    pub tokenizer_key_digest: Digest32,
    pub signature: [u8; 64],
}

impl SignedRetentionSelectionReceiptV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(SELECTION_RECEIPT_DOMAIN);
        push_u32(&mut bytes, self.schema_version);
        push_id(&mut bytes, &self.key_id);
        push_u64(&mut bytes, self.trust_epoch);
        push_u64(&mut bytes, self.issued_at_unix_seconds);
        push_u64(&mut bytes, self.expires_at_unix_seconds);
        for digest in [
            self.nonce,
            self.source_snapshot_digest,
            self.source_memory_snapshot_digest,
            self.policy_digest,
            self.input_manifest_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_id(&mut bytes, &self.tokenizer_key_id);
        push_u64(&mut bytes, self.tokenizer_trust_epoch);
        push_digest(&mut bytes, self.tokenizer_key_digest);
        bytes
    }

    #[must_use]
    pub fn receipt_digest(&self) -> Digest32 {
        signed_digest(&self.signing_bytes(), &self.signature)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn verify_current(
        &self,
        selector: &TrustedRetentionSelectorV1,
        tokenizer: &TrustedTokenizerV1,
        source_snapshot: &CognitiveSnapshotKeyV1,
        source_memory_snapshot: &CognitiveSnapshot,
        policy: &CompactionPolicyV2,
        inputs: &[CompactionInputRecordV2],
        verification_time: u64,
    ) -> Result<(), TrustedCompactionError> {
        selector.validate()?;
        tokenizer.validate_current_at(verification_time)?;
        verify_receipt_header(
            &selector.enrollment,
            self.schema_version,
            &self.key_id,
            self.trust_epoch,
            self.issued_at_unix_seconds,
            self.expires_at_unix_seconds,
            self.nonce,
            verification_time,
            false,
        )?;
        self.verify_subject(
            tokenizer,
            source_snapshot,
            source_memory_snapshot,
            policy,
            inputs,
        )?;
        verify_signature(
            &selector.enrollment,
            &self.signing_bytes(),
            &self.signature,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub fn verify_historical(
        &self,
        selector: &TrustedRetentionSelectorV1,
        tokenizer: &TrustedTokenizerV1,
        source_snapshot: &CognitiveSnapshotKeyV1,
        source_memory_snapshot: &CognitiveSnapshot,
        policy: &CompactionPolicyV2,
        inputs: &[CompactionInputRecordV2],
        accepted_at: u64,
    ) -> Result<(), TrustedCompactionError> {
        selector.validate()?;
        tokenizer.validate_historical_at(accepted_at)?;
        verify_receipt_header(
            &selector.enrollment,
            self.schema_version,
            &self.key_id,
            self.trust_epoch,
            self.issued_at_unix_seconds,
            self.expires_at_unix_seconds,
            self.nonce,
            accepted_at,
            true,
        )?;
        self.verify_subject(
            tokenizer,
            source_snapshot,
            source_memory_snapshot,
            policy,
            inputs,
        )?;
        verify_signature(
            &selector.enrollment,
            &self.signing_bytes(),
            &self.signature,
        )
    }

    fn verify_subject(
        &self,
        tokenizer: &TrustedTokenizerV1,
        source_snapshot: &CognitiveSnapshotKeyV1,
        source_memory_snapshot: &CognitiveSnapshot,
        policy: &CompactionPolicyV2,
        inputs: &[CompactionInputRecordV2],
    ) -> Result<(), TrustedCompactionError> {
        if self.source_snapshot_digest != source_snapshot.vector_digest
            || self.source_memory_snapshot_digest != source_memory_snapshot.snapshot_digest
            || self.policy_digest != policy.digest()
            || self.input_manifest_digest != compaction_input_manifest_digest(inputs)
            || self.tokenizer_key_id != tokenizer.enrollment.key_id
            || self.tokenizer_trust_epoch != tokenizer.enrollment.trust_epoch
            || self.tokenizer_key_digest != tokenizer.enrollment.key_digest()
        {
            return Err(TrustedCompactionError::BindingMismatch(
                "retention selection",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedSemanticGenerationReceiptV1 {
    pub schema_version: u32,
    pub key_id: StableId,
    pub trust_epoch: u64,
    pub issued_at_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    pub nonce: Digest32,
    pub source_snapshot_digest: Digest32,
    pub source_memory_snapshot_digest: Digest32,
    pub policy_digest: Digest32,
    pub selection_receipt_digest: Digest32,
    pub payload_digest: Digest32,
    pub tokenizer_key_id: StableId,
    pub tokenizer_trust_epoch: u64,
    pub tokenizer_key_digest: Digest32,
    pub tokenization_receipt_digest: Digest32,
    pub signature: [u8; 64],
}

impl SignedSemanticGenerationReceiptV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(GENERATION_RECEIPT_DOMAIN);
        push_u32(&mut bytes, self.schema_version);
        push_id(&mut bytes, &self.key_id);
        push_u64(&mut bytes, self.trust_epoch);
        push_u64(&mut bytes, self.issued_at_unix_seconds);
        push_u64(&mut bytes, self.expires_at_unix_seconds);
        for digest in [
            self.nonce,
            self.source_snapshot_digest,
            self.source_memory_snapshot_digest,
            self.policy_digest,
            self.selection_receipt_digest,
            self.payload_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_id(&mut bytes, &self.tokenizer_key_id);
        push_u64(&mut bytes, self.tokenizer_trust_epoch);
        push_digest(&mut bytes, self.tokenizer_key_digest);
        push_digest(&mut bytes, self.tokenization_receipt_digest);
        bytes
    }

    #[must_use]
    pub fn receipt_digest(&self) -> Digest32 {
        signed_digest(&self.signing_bytes(), &self.signature)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn verify_current(
        &self,
        generator: &TrustedSemanticGeneratorV1,
        tokenizer: &TrustedTokenizerV1,
        selection_receipt: &SignedRetentionSelectionReceiptV1,
        source_snapshot: &CognitiveSnapshotKeyV1,
        source_memory_snapshot: &CognitiveSnapshot,
        policy: &CompactionPolicyV2,
        semantic_payload: &CompactionSemanticPayloadV2,
        verification_time: u64,
    ) -> Result<(), TrustedCompactionError> {
        generator.validate()?;
        tokenizer.validate_current_at(verification_time)?;
        verify_receipt_header(
            &generator.enrollment,
            self.schema_version,
            &self.key_id,
            self.trust_epoch,
            self.issued_at_unix_seconds,
            self.expires_at_unix_seconds,
            self.nonce,
            verification_time,
            false,
        )?;
        self.verify_subject(
            generator,
            tokenizer,
            selection_receipt,
            source_snapshot,
            source_memory_snapshot,
            policy,
            semantic_payload,
        )?;
        verify_signature(
            &generator.enrollment,
            &self.signing_bytes(),
            &self.signature,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub fn verify_historical(
        &self,
        generator: &TrustedSemanticGeneratorV1,
        tokenizer: &TrustedTokenizerV1,
        selection_receipt: &SignedRetentionSelectionReceiptV1,
        source_snapshot: &CognitiveSnapshotKeyV1,
        source_memory_snapshot: &CognitiveSnapshot,
        policy: &CompactionPolicyV2,
        semantic_payload: &CompactionSemanticPayloadV2,
        accepted_at: u64,
    ) -> Result<(), TrustedCompactionError> {
        generator.validate()?;
        tokenizer.validate_historical_at(accepted_at)?;
        verify_receipt_header(
            &generator.enrollment,
            self.schema_version,
            &self.key_id,
            self.trust_epoch,
            self.issued_at_unix_seconds,
            self.expires_at_unix_seconds,
            self.nonce,
            accepted_at,
            true,
        )?;
        self.verify_subject(
            generator,
            tokenizer,
            selection_receipt,
            source_snapshot,
            source_memory_snapshot,
            policy,
            semantic_payload,
        )?;
        verify_signature(
            &generator.enrollment,
            &self.signing_bytes(),
            &self.signature,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn verify_subject(
        &self,
        generator: &TrustedSemanticGeneratorV1,
        tokenizer: &TrustedTokenizerV1,
        selection_receipt: &SignedRetentionSelectionReceiptV1,
        source_snapshot: &CognitiveSnapshotKeyV1,
        source_memory_snapshot: &CognitiveSnapshot,
        policy: &CompactionPolicyV2,
        semantic_payload: &CompactionSemanticPayloadV2,
    ) -> Result<(), TrustedCompactionError> {
        if self.source_snapshot_digest != source_snapshot.vector_digest
            || self.source_memory_snapshot_digest != source_memory_snapshot.snapshot_digest
            || self.policy_digest != policy.digest()
            || self.selection_receipt_digest != selection_receipt.receipt_digest()
            || self.payload_digest != semantic_payload.payload_digest
            || self.tokenizer_key_id != tokenizer.enrollment.key_id
            || self.tokenizer_trust_epoch != tokenizer.enrollment.trust_epoch
            || self.tokenizer_key_digest != tokenizer.enrollment.key_digest()
            || self.tokenization_receipt_digest
                != semantic_payload.tokenization_receipt.receipt_digest()
            || semantic_payload.generator_implementation_digest
                != generator.enrollment.implementation_digest
            || semantic_payload.generator_receipt_digest != self.receipt_digest()
        {
            return Err(TrustedCompactionError::BindingMismatch(
                "semantic generation",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedCompactionEvaluationReceiptV1 {
    pub schema_version: u32,
    pub key_id: StableId,
    pub trust_epoch: u64,
    pub issued_at_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
    pub nonce: Digest32,
    pub candidate_digest: Digest32,
    pub qualification_digest: Digest32,
    pub signature: [u8; 64],
}

impl SignedCompactionEvaluationReceiptV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(EVALUATION_RECEIPT_DOMAIN);
        push_u32(&mut bytes, self.schema_version);
        push_id(&mut bytes, &self.key_id);
        push_u64(&mut bytes, self.trust_epoch);
        push_u64(&mut bytes, self.issued_at_unix_seconds);
        push_u64(&mut bytes, self.expires_at_unix_seconds);
        push_digest(&mut bytes, self.nonce);
        push_digest(&mut bytes, self.candidate_digest);
        push_digest(&mut bytes, self.qualification_digest);
        bytes
    }

    #[must_use]
    pub fn receipt_digest(&self) -> Digest32 {
        signed_digest(&self.signing_bytes(), &self.signature)
    }

    pub fn verify_current(
        &self,
        evaluator: &TrustedCompactionEvaluatorV1,
        candidate: &QualifiedCompactionCandidateV2,
        qualification: &CompactionQualificationV2,
        verification_time: u64,
    ) -> Result<(), TrustedCompactionError> {
        evaluator.validate()?;
        verify_receipt_header(
            &evaluator.enrollment,
            self.schema_version,
            &self.key_id,
            self.trust_epoch,
            self.issued_at_unix_seconds,
            self.expires_at_unix_seconds,
            self.nonce,
            verification_time,
            false,
        )?;
        self.verify_subject(candidate, qualification)?;
        verify_signature(
            &evaluator.enrollment,
            &self.signing_bytes(),
            &self.signature,
        )
    }

    pub fn verify_historical(
        &self,
        evaluator: &TrustedCompactionEvaluatorV1,
        candidate: &QualifiedCompactionCandidateV2,
        qualification: &CompactionQualificationV2,
        accepted_at: u64,
    ) -> Result<(), TrustedCompactionError> {
        evaluator.validate()?;
        verify_receipt_header(
            &evaluator.enrollment,
            self.schema_version,
            &self.key_id,
            self.trust_epoch,
            self.issued_at_unix_seconds,
            self.expires_at_unix_seconds,
            self.nonce,
            accepted_at,
            true,
        )?;
        self.verify_subject(candidate, qualification)?;
        verify_signature(
            &evaluator.enrollment,
            &self.signing_bytes(),
            &self.signature,
        )
    }

    fn verify_subject(
        &self,
        candidate: &QualifiedCompactionCandidateV2,
        qualification: &CompactionQualificationV2,
    ) -> Result<(), TrustedCompactionError> {
        if self.candidate_digest != candidate.candidate_digest()
            || self.qualification_digest
                != compaction_qualification_digest(candidate.candidate_digest(), qualification)
        {
            return Err(TrustedCompactionError::BindingMismatch(
                "compaction evaluation",
            ));
        }
        Ok(())
    }
}

pub struct QualifiedCandidateBuildRequestV1<'a> {
    pub source_snapshot: CognitiveSnapshotKeyV1,
    pub source_memory_snapshot: &'a CognitiveSnapshot,
    pub generation: Generation,
    pub predecessor_checkpoint_digest: Option<Digest32>,
    pub policy: &'a CompactionPolicyV2,
    pub semantic_payload: &'a CompactionSemanticPayloadV2,
    pub selector: &'a TrustedRetentionSelectorV1,
    pub selection_receipt: &'a SignedRetentionSelectionReceiptV1,
    pub generator: &'a TrustedSemanticGeneratorV1,
    pub generation_receipt: &'a SignedSemanticGenerationReceiptV1,
    pub tokenizer: &'a TrustedTokenizerV1,
    pub inputs: Vec<CompactionInputRecordV2>,
    pub verification_time_unix_seconds: u64,
}

pub fn build_qualified_candidate(
    request: QualifiedCandidateBuildRequestV1<'_>,
) -> Result<QualifiedCompactionCandidateV2, TrustedCompactionError> {
    request.selection_receipt.verify_current(
        request.selector,
        request.tokenizer,
        &request.source_snapshot,
        request.source_memory_snapshot,
        request.policy,
        &request.inputs,
        request.verification_time_unix_seconds,
    )?;
    request.generation_receipt.verify_current(
        request.generator,
        request.tokenizer,
        request.selection_receipt,
        &request.source_snapshot,
        request.source_memory_snapshot,
        request.policy,
        request.semantic_payload,
        request.verification_time_unix_seconds,
    )?;
    let tokenizer = request.tokenizer.kernel();
    qualified::build_qualified_candidate(
        request.source_snapshot,
        request.source_memory_snapshot,
        request.generation,
        request.predecessor_checkpoint_digest,
        request.policy,
        request.semantic_payload,
        &tokenizer,
        request.inputs,
    )
    .map_err(TrustedCompactionError::Kernel)
}

pub struct TrustedCompactionProofRequestV1<'a> {
    pub candidate: &'a QualifiedCompactionCandidateV2,
    pub evaluator: &'a TrustedCompactionEvaluatorV1,
    pub qualification: CompactionQualificationV2,
    pub evaluation_receipt: &'a SignedCompactionEvaluationReceiptV1,
    pub verification_time_unix_seconds: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedCompactionProofV1 {
    pub proof: CompactionProofV2,
    pub witness: CompactionProofWitnessV1,
    pub evaluation_receipt_digest: Digest32,
    pub evaluator_key_id: StableId,
    pub evaluator_trust_epoch: u64,
    pub accepted_at_unix_seconds: u64,
}

pub fn prove_compaction(
    request: TrustedCompactionProofRequestV1<'_>,
) -> Result<TrustedCompactionProofV1, TrustedCompactionError> {
    request.evaluation_receipt.verify_current(
        request.evaluator,
        request.candidate,
        &request.qualification,
        request.verification_time_unix_seconds,
    )?;
    let witness = CompactionProofWitnessV1 {
        evaluator_verifying_key: request.evaluator.enrollment.verifying_key,
        qualification_signature: request.qualification.signature,
    };
    let evaluator = request.evaluator.kernel();
    let proof = qualified::prove_compaction(
        request.candidate,
        &evaluator,
        request.qualification,
    )
    .map_err(TrustedCompactionError::Kernel)?;
    witness
        .verify_proof(&proof)
        .map_err(|_| TrustedCompactionError::BindingMismatch("proof witness"))?;
    Ok(TrustedCompactionProofV1 {
        proof,
        witness,
        evaluation_receipt_digest: request.evaluation_receipt.receipt_digest(),
        evaluator_key_id: request.evaluator.enrollment.key_id.clone(),
        evaluator_trust_epoch: request.evaluator.enrollment.trust_epoch,
        accepted_at_unix_seconds: request.verification_time_unix_seconds,
    })
}

#[must_use]
pub fn compaction_input_manifest_digest(inputs: &[CompactionInputRecordV2]) -> Digest32 {
    let mut digests = inputs
        .iter()
        .map(CompactionInputRecordV2::digest)
        .collect::<Vec<_>>();
    digests.sort();
    let mut bytes = Vec::new();
    bytes.extend_from_slice(INPUT_MANIFEST_DOMAIN);
    push_len(&mut bytes, digests.len());
    for digest in digests {
        push_digest(&mut bytes, digest);
    }
    Digest32::of_bytes(&bytes)
}

#[must_use]
pub fn compaction_qualification_digest(
    candidate_digest: Digest32,
    qualification: &CompactionQualificationV2,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(QUALIFICATION_DIGEST_DOMAIN);
    bytes.extend_from_slice(&qualification.signing_bytes(candidate_digest));
    bytes.extend_from_slice(&qualification.signature);
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TrustedCompactionError {
    InvalidSchemaVersion,
    WrongTrustRole,
    InvalidTrustInterval,
    InvalidTrustRotation,
    InvalidTrustKey,
    TrustNotYetValid,
    TrustExpired,
    TrustRevoked,
    InvalidReceiptInterval,
    ReceiptExpired,
    EmptyDigest(&'static str),
    InvalidReplayNonce,
    InvalidSignature,
    BindingMismatch(&'static str),
    Kernel(QualifiedCompactionError),
}

impl fmt::Display for TrustedCompactionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for TrustedCompactionError {}

impl From<QualifiedCompactionError> for TrustedCompactionError {
    fn from(error: QualifiedCompactionError) -> Self {
        Self::Kernel(error)
    }
}

#[allow(clippy::too_many_arguments)]
fn verify_receipt_header(
    enrollment: &TrustEnrollmentV1,
    schema_version: u32,
    key_id: &StableId,
    trust_epoch: u64,
    issued_at: u64,
    expires_at: u64,
    nonce: Digest32,
    verification_or_acceptance_time: u64,
    historical: bool,
) -> Result<(), TrustedCompactionError> {
    if schema_version != COMPACTION_TRUST_SCHEMA_VERSION {
        return Err(TrustedCompactionError::InvalidSchemaVersion);
    }
    if key_id != &enrollment.key_id || trust_epoch != enrollment.trust_epoch {
        return Err(TrustedCompactionError::BindingMismatch("trust identity"));
    }
    if nonce.is_zero() {
        return Err(TrustedCompactionError::InvalidReplayNonce);
    }
    if historical {
        enrollment.validate_historical_receipt(
            issued_at,
            expires_at,
            verification_or_acceptance_time,
        )
    } else {
        enrollment.validate_current_receipt(
            issued_at,
            expires_at,
            verification_or_acceptance_time,
        )
    }
}

fn verify_signature(
    enrollment: &TrustEnrollmentV1,
    message: &[u8],
    signature: &[u8; 64],
) -> Result<(), TrustedCompactionError> {
    VerifyingKey::from_bytes(&enrollment.verifying_key)
        .map_err(|_| TrustedCompactionError::InvalidTrustKey)?
        .verify_strict(message, &Signature::from_bytes(signature))
        .map_err(|_| TrustedCompactionError::InvalidSignature)
}

fn signed_digest(message: &[u8], signature: &[u8; 64]) -> Digest32 {
    let mut bytes = Vec::with_capacity(message.len().saturating_add(signature.len()));
    bytes.extend_from_slice(message);
    bytes.extend_from_slice(signature);
    Digest32::of_bytes(&bytes)
}

fn ensure_digest(
    label: &'static str,
    digest: Digest32,
) -> Result<(), TrustedCompactionError> {
    if digest.is_zero() {
        return Err(TrustedCompactionError::EmptyDigest(label));
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

fn push_u32(bytes: &mut Vec<u8>, value: u32) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

#[cfg(test)]
#[path = "trust_tests.rs"]
mod tests;
