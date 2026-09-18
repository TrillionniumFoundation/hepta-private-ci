//! Proof-closed V2 context compilation.
//!
//! This is the public, normative V2 surface. The original V2 selection engine
//! remains private and is used only after admission/tokenization evidence has
//! been verified here. This layer binds mandatory-group provenance, exact final
//! serialization, attachment-time revocation revalidation, and transport
//! evidence without adding model/provider authority.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::v2 as legacy;

pub use legacy::ContextDeliveryDispositionV2;
pub use legacy::ContextRoleV2;
pub use legacy::MAX_CONTEXT_CANDIDATES_V2;
pub use legacy::MAX_CONTEXT_GROUPS_V2;
pub use legacy::MAX_CONTEXT_TOKENS_V2;
pub use legacy::MandatoryContextGroupV2;

const TOKENIZATION_DOMAIN: &[u8] = b"hepta.context-tokenization.proof-v2.1";
const MODEL_PROFILE_DOMAIN: &[u8] = b"hepta.context-model-profile.proof-v2.1";
const ADMISSION_SNAPSHOT_DOMAIN: &[u8] = b"hepta.context-admission-snapshot.proof-v2.1";
const ADMISSION_PROOF_DOMAIN: &[u8] = b"hepta.context-admission-proof.proof-v2.1";
const MANDATORY_GROUPS_DOMAIN: &[u8] = b"hepta.context-mandatory-groups.proof-v2.1";
const SELECTED_BINDING_DOMAIN: &[u8] = b"hepta.context-selected-binding.proof-v2.1";
const COMPILATION_RECEIPT_DOMAIN: &[u8] = b"hepta.context-compilation-receipt.proof-v2.1";
const REALIZATION_DOMAIN: &[u8] = b"hepta.context-realization.proof-v2.1";
const SERIALIZATION_DOMAIN: &[u8] = b"hepta.context-serialization.proof-v2.1";
const REVALIDATION_DOMAIN: &[u8] = b"hepta.context-revalidation.proof-v2.1";
const ATTACHMENT_DOMAIN: &[u8] = b"hepta.context-attachment.proof-v2.1";
const DELIVERY_DOMAIN: &[u8] = b"hepta.context-delivery.proof-v2.1";

/// Exact tokenizer boundary. The implementation identity must match the model
/// profile and the compiler calls it over the actual bytes being measured.
pub trait ExactContextTokenizerV2 {
    fn tokenizer_digest(&self) -> Digest32;

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, String>;
}

/// Tokenization receipt that cannot be constructed from a caller-supplied count.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TokenizationReceiptV2 {
    item_id: StableId,
    content_digest: Digest32,
    tokenizer_digest: Digest32,
    token_count: u64,
    receipt_digest: Digest32,
}

impl TokenizationReceiptV2 {
    pub fn measure(
        item_id: StableId,
        content: &[u8],
        tokenizer: &impl ExactContextTokenizerV2,
    ) -> Result<Self, ContextCompilerV2Error> {
        let tokenizer_digest = tokenizer.tokenizer_digest();
        ensure_digest("tokenizer", tokenizer_digest)?;
        let token_count = tokenizer
            .count_tokens(content)
            .map_err(ContextCompilerV2Error::TokenizerFailure)?;
        if token_count == 0 || token_count > MAX_CONTEXT_TOKENS_V2 {
            return Err(ContextCompilerV2Error::InvalidTokenCount(
                item_id.to_string(),
            ));
        }
        let mut receipt = Self {
            item_id,
            content_digest: Digest32::of_bytes(content),
            tokenizer_digest,
            token_count,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.compute_digest();
        Ok(receipt)
    }

    fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        ensure_digest("tokenized_content", self.content_digest)?;
        ensure_digest("tokenizer", self.tokenizer_digest)?;
        if self.token_count == 0 || self.token_count > MAX_CONTEXT_TOKENS_V2 {
            return Err(ContextCompilerV2Error::InvalidTokenCount(
                self.item_id.to_string(),
            ));
        }
        if self.receipt_digest != self.compute_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch(
                "tokenization_receipt",
            ));
        }
        Ok(())
    }

    fn to_legacy(&self) -> Result<legacy::TokenizationReceiptV2, ContextCompilerV2Error> {
        legacy::TokenizationReceiptV2::new(
            self.item_id.clone(),
            self.content_digest,
            self.tokenizer_digest,
            self.token_count,
        )
        .map_err(ContextCompilerV2Error::SelectionEngine)
    }

    #[must_use]
    pub fn item_id(&self) -> &StableId {
        &self.item_id
    }

    #[must_use]
    pub const fn content_digest(&self) -> Digest32 {
        self.content_digest
    }

    #[must_use]
    pub const fn tokenizer_digest(&self) -> Digest32 {
        self.tokenizer_digest
    }

    #[must_use]
    pub const fn token_count(&self) -> u64 {
        self.token_count
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(TOKENIZATION_DOMAIN);
        push_id(&mut bytes, &self.item_id);
        push_digest(&mut bytes, self.content_digest);
        push_digest(&mut bytes, self.tokenizer_digest);
        push_u64(&mut bytes, self.token_count);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextModelProfileV2 {
    pub model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub template_digest: Digest32,
    pub tool_schema_digest: Digest32,
    pub serializer_digest: Digest32,
    pub maximum_context_tokens: u64,
}

impl ContextModelProfileV2 {
    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("model", self.model_digest),
            ("tokenizer", self.tokenizer_digest),
            ("template", self.template_digest),
            ("tool_schema", self.tool_schema_digest),
            ("serializer", self.serializer_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.maximum_context_tokens == 0
            || self.maximum_context_tokens > MAX_CONTEXT_TOKENS_V2
        {
            return Err(ContextCompilerV2Error::InvalidModelContextLimit);
        }
        Ok(())
    }

    fn to_legacy(&self) -> legacy::ContextModelProfileV2 {
        legacy::ContextModelProfileV2 {
            model_digest: self.model_digest,
            tokenizer_digest: self.tokenizer_digest,
            template_digest: self.template_digest,
            tool_schema_digest: self.tool_schema_digest,
            maximum_context_tokens: self.maximum_context_tokens,
        }
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(MODEL_PROFILE_DOMAIN);
        for digest in [
            self.model_digest,
            self.tokenizer_digest,
            self.template_digest,
            self.tool_schema_digest,
            self.serializer_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.maximum_context_tokens);
        Digest32::of_bytes(&bytes)
    }
}

/// Upstream admission record bound into a coherent snapshot.
///
/// The host remains responsible for authenticating 'witness_digest' and
/// 'issuer_digest'; this module verifies item/role/source/content/freshness and
/// revocation consistency before producing a typed admission proof.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextAdmissionRecordV2 {
    pub item_id: StableId,
    pub role: ContextRoleV2,
    pub content_digest: Digest32,
    pub source_digest: Digest32,
    pub admission_digest: Digest32,
    pub admitted_at_unix_ms: u64,
    pub expires_at_unix_ms: Option<u64>,
    pub revoked_at_unix_ms: Option<u64>,
    pub revocation_digest: Option<Digest32>,
}

impl ContextAdmissionRecordV2 {
    fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        if self.role == ContextRoleV2::UntrustedEvidence {
            return Err(ContextCompilerV2Error::AdmissionRoleNotTrusted(
                self.item_id.to_string(),
            ));
        }
        for (name, digest) in [
            ("admitted_content", self.content_digest),
            ("admitted_source", self.source_digest),
            ("admission", self.admission_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.admitted_at_unix_ms == 0
            || self
                .expires_at_unix_ms
                .is_some_and(|expiry| expiry <= self.admitted_at_unix_ms)
        {
            return Err(ContextCompilerV2Error::InvalidAdmissionRecordTime(
                self.item_id.to_string(),
            ));
        }
        match (self.revoked_at_unix_ms, self.revocation_digest) {
            (Some(revoked_at), Some(revocation_digest)) => {
                if revoked_at < self.admitted_at_unix_ms {
                    return Err(ContextCompilerV2Error::InvalidAdmissionRecordTime(
                        self.item_id.to_string(),
                    ));
                }
                ensure_digest("revocation", revocation_digest)?;
            }
            (None, None) => {}
            _ => {
                return Err(ContextCompilerV2Error::InvalidRevocationMetadata(
                    self.item_id.to_string(),
                ));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextAdmissionSnapshotEvidenceV2 {
    pub issuer_digest: Digest32,
    pub source_snapshot_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub witness_digest: Digest32,
    pub observed_unix_ms: u64,
    pub records: Vec<ContextAdmissionRecordV2>,
}

/// Host authentication boundary for admission/revocation snapshots.
///
/// Implementations authenticate the upstream issuer/latest-head witness rather
/// than merely checking internal digest consistency. The returned nonzero
/// verification digest is bound into all downstream admission proofs.
pub trait ContextAdmissionVerifierV2 {
    fn verifier_digest(&self) -> Digest32;

    fn verify_snapshot(
        &self,
        evidence: &ContextAdmissionSnapshotEvidenceV2,
    ) -> Result<Digest32, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextAdmissionSnapshotV2 {
    issuer_digest: Digest32,
    source_snapshot_digest: Digest32,
    revocation_frontier_digest: Digest32,
    witness_digest: Digest32,
    verifier_digest: Digest32,
    verification_digest: Digest32,
    observed_unix_ms: u64,
    records: BTreeMap<StableId, ContextAdmissionRecordV2>,
    snapshot_digest: Digest32,
}

pub fn verify_admission_snapshot_v2(
    evidence: ContextAdmissionSnapshotEvidenceV2,
    verifier: &impl ContextAdmissionVerifierV2,
) -> Result<ContextAdmissionSnapshotV2, ContextCompilerV2Error> {
    for (name, digest) in [
        ("admission_issuer", evidence.issuer_digest),
        ("admission_source_snapshot", evidence.source_snapshot_digest),
        ("revocation_frontier", evidence.revocation_frontier_digest),
        ("admission_witness", evidence.witness_digest),
    ] {
        ensure_digest(name, digest)?;
    }
    if evidence.observed_unix_ms == 0 {
        return Err(ContextCompilerV2Error::InvalidAdmissionSnapshotTime);
    }
    let mut by_id = BTreeMap::new();
    for record in &evidence.records {
        record.validate()?;
        let item_id = record.item_id.clone();
        if by_id.insert(item_id.clone(), record.clone()).is_some() {
            return Err(ContextCompilerV2Error::DuplicateAdmissionRecord(
                item_id.to_string(),
            ));
        }
    }

    let verifier_digest = verifier.verifier_digest();
    ensure_digest("admission_verifier", verifier_digest)?;
    let verification_digest = verifier
        .verify_snapshot(&evidence)
        .map_err(ContextCompilerV2Error::AdmissionVerificationFailure)?;
    ensure_digest("admission_verification", verification_digest)?;

    let snapshot_digest = compute_admission_snapshot_digest(
        evidence.issuer_digest,
        evidence.source_snapshot_digest,
        evidence.revocation_frontier_digest,
        evidence.witness_digest,
        verifier_digest,
        verification_digest,
        evidence.observed_unix_ms,
        by_id.values(),
    );
    let snapshot = ContextAdmissionSnapshotV2 {
        issuer_digest: evidence.issuer_digest,
        source_snapshot_digest: evidence.source_snapshot_digest,
        revocation_frontier_digest: evidence.revocation_frontier_digest,
        witness_digest: evidence.witness_digest,
        verifier_digest,
        verification_digest,
        observed_unix_ms: evidence.observed_unix_ms,
        records: by_id,
        snapshot_digest,
    };
    snapshot.validate()?;
    Ok(snapshot)
}

impl ContextAdmissionSnapshotV2 {
    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("admission_issuer", self.issuer_digest),
            ("admission_source_snapshot", self.source_snapshot_digest),
            ("revocation_frontier", self.revocation_frontier_digest),
            ("admission_witness", self.witness_digest),
            ("admission_verifier", self.verifier_digest),
            ("admission_verification", self.verification_digest),
            ("admission_snapshot", self.snapshot_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.observed_unix_ms == 0 {
            return Err(ContextCompilerV2Error::InvalidAdmissionSnapshotTime);
        }
        for record in self.records.values() {
            record.validate()?;
        }
        let expected = compute_admission_snapshot_digest(
            self.issuer_digest,
            self.source_snapshot_digest,
            self.revocation_frontier_digest,
            self.witness_digest,
            self.verifier_digest,
            self.verification_digest,
            self.observed_unix_ms,
            self.records.values(),
        );
        if self.snapshot_digest != expected {
            return Err(ContextCompilerV2Error::DigestMismatch("admission_snapshot"));
        }
        Ok(())
    }

    pub fn verify_trusted_binding(
        &self,
        item_id: &StableId,
        role: ContextRoleV2,
        content_digest: Digest32,
        source_digest: Digest32,
    ) -> Result<VerifiedContextAdmissionV2, ContextCompilerV2Error> {
        self.validate()?;
        if role == ContextRoleV2::UntrustedEvidence {
            return Err(ContextCompilerV2Error::AdmissionRoleNotTrusted(
                item_id.to_string(),
            ));
        }
        let record = self
            .records
            .get(item_id)
            .ok_or_else(|| ContextCompilerV2Error::AdmissionMissing(item_id.to_string()))?;
        if record.role != role
            || record.content_digest != content_digest
            || record.source_digest != source_digest
        {
            return Err(ContextCompilerV2Error::AdmissionBindingMismatch(
                item_id.to_string(),
            ));
        }
        if record.admitted_at_unix_ms > self.observed_unix_ms {
            return Err(ContextCompilerV2Error::InvalidAdmissionRecordTime(
                item_id.to_string(),
            ));
        }
        if record.revoked_at_unix_ms.is_some() {
            return Err(ContextCompilerV2Error::AdmissionRevoked(
                item_id.to_string(),
            ));
        }
        if record
            .expires_at_unix_ms
            .is_some_and(|expiry| expiry <= self.observed_unix_ms)
        {
            return Err(ContextCompilerV2Error::AdmissionExpired(
                item_id.to_string(),
            ));
        }
        Ok(VerifiedContextAdmissionV2::from_record(record, self))
    }

    #[must_use]
    pub const fn issuer_digest(&self) -> Digest32 {
        self.issuer_digest
    }

    #[must_use]
    pub const fn revocation_frontier_digest(&self) -> Digest32 {
        self.revocation_frontier_digest
    }

    #[must_use]
    pub const fn witness_digest(&self) -> Digest32 {
        self.witness_digest
    }

    #[must_use]
    pub const fn verifier_digest(&self) -> Digest32 {
        self.verifier_digest
    }

    #[must_use]
    pub const fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }

    #[must_use]
    pub const fn observed_unix_ms(&self) -> u64 {
        self.observed_unix_ms
    }

    #[must_use]
    pub const fn snapshot_digest(&self) -> Digest32 {
        self.snapshot_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedContextAdmissionV2 {
    item_id: StableId,
    role: ContextRoleV2,
    content_digest: Digest32,
    source_digest: Digest32,
    admission_digest: Digest32,
    issuer_digest: Digest32,
    snapshot_digest: Digest32,
    revocation_frontier_digest: Digest32,
    witness_digest: Digest32,
    verifier_digest: Digest32,
    verification_digest: Digest32,
    verified_at_unix_ms: u64,
    proof_digest: Digest32,
}

impl VerifiedContextAdmissionV2 {
    fn from_record(record: &ContextAdmissionRecordV2, snapshot: &ContextAdmissionSnapshotV2) -> Self {
        let mut proof = Self {
            item_id: record.item_id.clone(),
            role: record.role,
            content_digest: record.content_digest,
            source_digest: record.source_digest,
            admission_digest: record.admission_digest,
            issuer_digest: snapshot.issuer_digest,
            snapshot_digest: snapshot.snapshot_digest,
            revocation_frontier_digest: snapshot.revocation_frontier_digest,
            witness_digest: snapshot.witness_digest,
            verifier_digest: snapshot.verifier_digest,
            verification_digest: snapshot.verification_digest,
            verified_at_unix_ms: snapshot.observed_unix_ms,
            proof_digest: Digest32::ZERO,
        };
        proof.proof_digest = proof.compute_digest();
        proof
    }

    fn validate_for(
        &self,
        candidate: &ContextCandidateV2,
        snapshot: &ContextAdmissionSnapshotV2,
    ) -> Result<(), ContextCompilerV2Error> {
        if self.item_id != candidate.item_id
            || self.role != candidate.role
            || self.content_digest != candidate.content_digest
            || self.source_digest != candidate.source_digest
        {
            return Err(ContextCompilerV2Error::AdmissionBindingMismatch(
                candidate.item_id.to_string(),
            ));
        }
        if self.issuer_digest != snapshot.issuer_digest
            || self.snapshot_digest != snapshot.snapshot_digest
            || self.revocation_frontier_digest != snapshot.revocation_frontier_digest
            || self.witness_digest != snapshot.witness_digest
            || self.verifier_digest != snapshot.verifier_digest
            || self.verification_digest != snapshot.verification_digest
            || self.verified_at_unix_ms != snapshot.observed_unix_ms
        {
            return Err(ContextCompilerV2Error::AdmissionSnapshotMismatch(
                candidate.item_id.to_string(),
            ));
        }
        if self.proof_digest != self.compute_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch("admission_proof"));
        }
        snapshot
            .verify_trusted_binding(
                &candidate.item_id,
                candidate.role,
                candidate.content_digest,
                candidate.source_digest,
            )
            .map(|_| ())
    }

    #[must_use]
    pub const fn proof_digest(&self) -> Digest32 {
        self.proof_digest
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ADMISSION_PROOF_DOMAIN);
        push_id(&mut bytes, &self.item_id);
        bytes.push(role_code(self.role));
        for digest in [
            self.content_digest,
            self.source_digest,
            self.admission_digest,
            self.issuer_digest,
            self.snapshot_digest,
            self.revocation_frontier_digest,
            self.witness_digest,
            self.verifier_digest,
            self.verification_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.verified_at_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCandidateV2 {
    item_id: StableId,
    role: ContextRoleV2,
    content_digest: Digest32,
    source_digest: Digest32,
    generation_vector_digest: Digest32,
    tokenization: TokenizationReceiptV2,
    expected_value: FixedQ32,
    trusted_admission: Option<VerifiedContextAdmissionV2>,
    contains_secret: bool,
}

impl ContextCandidateV2 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        item_id: StableId,
        role: ContextRoleV2,
        source_digest: Digest32,
        generation_vector_digest: Digest32,
        tokenization: TokenizationReceiptV2,
        expected_value: FixedQ32,
        trusted_admission: Option<VerifiedContextAdmissionV2>,
        contains_secret: bool,
    ) -> Result<Self, ContextCompilerV2Error> {
        let candidate = Self {
            content_digest: tokenization.content_digest,
            item_id,
            role,
            source_digest,
            generation_vector_digest,
            tokenization,
            expected_value,
            trusted_admission,
            contains_secret,
        };
        candidate.validate_shape()?;
        Ok(candidate)
    }

    fn validate_shape(&self) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("candidate_content", self.content_digest),
            ("candidate_source", self.source_digest),
            ("candidate_generation_vector", self.generation_vector_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        self.tokenization.validate()?;
        if self.tokenization.item_id != self.item_id
            || self.tokenization.content_digest != self.content_digest
        {
            return Err(ContextCompilerV2Error::TokenizationItemMismatch(
                self.item_id.to_string(),
            ));
        }
        if self.expected_value < FixedQ32::ZERO || self.expected_value > FixedQ32::ONE {
            return Err(ContextCompilerV2Error::ValueOutOfRange(
                self.item_id.to_string(),
            ));
        }
        if self.contains_secret {
            return Err(ContextCompilerV2Error::SecretRejected(
                self.item_id.to_string(),
            ));
        }
        match self.role {
            ContextRoleV2::TrustedInstruction | ContextRoleV2::Schema => {
                if self.trusted_admission.is_none() {
                    return Err(ContextCompilerV2Error::MissingTrustedAdmission(
                        self.item_id.to_string(),
                    ));
                }
            }
            ContextRoleV2::UntrustedEvidence => {
                if self.trusted_admission.is_some() {
                    return Err(ContextCompilerV2Error::EvidenceRoleConfusion(
                        self.item_id.to_string(),
                    ));
                }
            }
        }
        Ok(())
    }

    fn validate_for(
        &self,
        generation_vector_digest: Digest32,
        profile: &ContextModelProfileV2,
        snapshot: &ContextAdmissionSnapshotV2,
    ) -> Result<(), ContextCompilerV2Error> {
        self.validate_shape()?;
        if self.generation_vector_digest != generation_vector_digest {
            return Err(ContextCompilerV2Error::GenerationVectorMismatch(
                self.item_id.to_string(),
            ));
        }
        if self.tokenization.tokenizer_digest != profile.tokenizer_digest {
            return Err(ContextCompilerV2Error::TokenizerMismatch(
                self.item_id.to_string(),
            ));
        }
        match (&self.trusted_admission, self.role) {
            (Some(admission), ContextRoleV2::TrustedInstruction | ContextRoleV2::Schema) => {
                admission.validate_for(self, snapshot)?;
            }
            (None, ContextRoleV2::UntrustedEvidence) => {}
            (None, _) => {
                return Err(ContextCompilerV2Error::MissingTrustedAdmission(
                    self.item_id.to_string(),
                ));
            }
            (Some(_), ContextRoleV2::UntrustedEvidence) => {
                return Err(ContextCompilerV2Error::EvidenceRoleConfusion(
                    self.item_id.to_string(),
                ));
            }
        }
        Ok(())
    }

    fn to_legacy(&self) -> Result<legacy::ContextCandidateV2, ContextCompilerV2Error> {
        Ok(legacy::ContextCandidateV2 {
            item_id: self.item_id.clone(),
            role: self.role,
            content_digest: self.content_digest,
            source_digest: self.source_digest,
            generation_vector_digest: self.generation_vector_digest,
            tokenization: self.tokenization.to_legacy()?,
            expected_value: self.expected_value,
            trusted_admission_digest: self
                .trusted_admission
                .as_ref()
                .map(VerifiedContextAdmissionV2::proof_digest),
            contains_secret: self.contains_secret,
        })
    }

    #[must_use]
    pub fn item_id(&self) -> &StableId {
        &self.item_id
    }

    #[must_use]
    pub const fn role(&self) -> ContextRoleV2 {
        self.role
    }

    #[must_use]
    pub const fn content_digest(&self) -> Digest32 {
        self.content_digest
    }

    #[must_use]
    pub const fn source_digest(&self) -> Digest32 {
        self.source_digest
    }

    #[must_use]
    pub const fn token_count(&self) -> u64 {
        self.tokenization.token_count
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilationRequestV2 {
    pub compilation_id: StableId,
    pub objective_digest: Digest32,
    pub prompt_portfolio_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_profile: ContextModelProfileV2,
    pub admission_snapshot: ContextAdmissionSnapshotV2,
    pub token_budget: u64,
    pub truncation_policy_digest: Digest32,
    pub candidates: Vec<ContextCandidateV2>,
    pub mandatory_groups: Vec<MandatoryContextGroupV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilationReceiptV2 {
    pub compilation_id: StableId,
    pub objective_digest: Digest32,
    pub prompt_portfolio_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub admission_issuer_digest: Digest32,
    pub admission_snapshot_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub admission_witness_digest: Digest32,
    pub admission_verifier_digest: Digest32,
    pub admission_verification_digest: Digest32,
    pub admission_observed_unix_ms: u64,
    pub candidate_set_digest: Digest32,
    pub mandatory_groups_digest: Digest32,
    pub selected_binding_digest: Digest32,
    pub selected_item_ids: Vec<StableId>,
    pub omitted_item_ids: Vec<StableId>,
    pub used_tokens: u64,
    pub token_upper_bound: u64,
    pub truncation_policy_digest: Digest32,
    pub context_digest: Digest32,
    pub selection_engine_receipt_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl ContextCompilationReceiptV2 {
    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("objective", self.objective_digest),
            ("prompt_portfolio", self.prompt_portfolio_digest),
            ("generation_vector", self.generation_vector_digest),
            ("model_profile", self.model_profile_digest),
            ("admission_issuer", self.admission_issuer_digest),
            ("admission_snapshot", self.admission_snapshot_digest),
            ("revocation_frontier", self.revocation_frontier_digest),
            ("admission_witness", self.admission_witness_digest),
            ("admission_verifier", self.admission_verifier_digest),
            ("admission_verification", self.admission_verification_digest),
            ("candidate_set", self.candidate_set_digest),
            ("mandatory_groups", self.mandatory_groups_digest),
            ("selected_binding", self.selected_binding_digest),
            ("truncation_policy", self.truncation_policy_digest),
            ("context", self.context_digest),
            ("selection_engine_receipt", self.selection_engine_receipt_digest),
            ("compilation_receipt", self.receipt_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.admission_observed_unix_ms == 0 {
            return Err(ContextCompilerV2Error::InvalidAdmissionSnapshotTime);
        }
        if self.used_tokens > self.token_upper_bound
            || self.token_upper_bound > MAX_CONTEXT_TOKENS_V2
        {
            return Err(ContextCompilerV2Error::TokenBudgetExceeded);
        }
        if self.authority.grants_any() {
            return Err(ContextCompilerV2Error::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch(
                "compilation_receipt",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(COMPILATION_RECEIPT_DOMAIN);
        push_id(&mut bytes, &self.compilation_id);
        for digest in [
            self.objective_digest,
            self.prompt_portfolio_digest,
            self.generation_vector_digest,
            self.model_profile_digest,
            self.admission_issuer_digest,
            self.admission_snapshot_digest,
            self.revocation_frontier_digest,
            self.admission_witness_digest,
            self.admission_verifier_digest,
            self.admission_verification_digest,
            self.candidate_set_digest,
            self.mandatory_groups_digest,
            self.selected_binding_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.admission_observed_unix_ms);
        push_ids(&mut bytes, &self.selected_item_ids);
        push_ids(&mut bytes, &self.omitted_item_ids);
        push_u64(&mut bytes, self.used_tokens);
        push_u64(&mut bytes, self.token_upper_bound);
        push_digest(&mut bytes, self.truncation_policy_digest);
        push_digest(&mut bytes, self.context_digest);
        push_digest(&mut bytes, self.selection_engine_receipt_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompiledContextV2 {
    pub receipt: ContextCompilationReceiptV2,
    pub selected_candidates: Vec<ContextCandidateV2>,
    pub model_profile: ContextModelProfileV2,
}

impl CompiledContextV2 {
    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        self.receipt.validate()?;
        self.model_profile.validate()?;
        if self.model_profile.digest() != self.receipt.model_profile_digest {
            return Err(ContextCompilerV2Error::DigestMismatch("model_profile"));
        }
        let selected_ids = self
            .selected_candidates
            .iter()
            .map(|candidate| candidate.item_id.clone())
            .collect::<Vec<_>>();
        if selected_ids != self.receipt.selected_item_ids
            || compute_selected_binding_digest(&self.selected_candidates)
                != self.receipt.selected_binding_digest
        {
            return Err(ContextCompilerV2Error::SelectedSetMismatch);
        }
        Ok(())
    }
}

/// Normative V2 compilation. Selection semantics are delegated to the existing
/// deterministic engine only after typed admission and exact candidate
/// tokenization evidence has passed.
pub fn compile_v2(
    mut request: ContextCompilationRequestV2,
) -> Result<CompiledContextV2, ContextCompilerV2Error> {
    request.model_profile.validate()?;
    request.admission_snapshot.validate()?;
    for (name, digest) in [
        ("objective", request.objective_digest),
        ("prompt_portfolio", request.prompt_portfolio_digest),
        ("generation_vector", request.generation_vector_digest),
        ("truncation_policy", request.truncation_policy_digest),
    ] {
        ensure_digest(name, digest)?;
    }
    if request.candidates.len() > MAX_CONTEXT_CANDIDATES_V2 {
        return Err(ContextCompilerV2Error::CandidateLimitExceeded);
    }
    if request.mandatory_groups.len() > MAX_CONTEXT_GROUPS_V2 {
        return Err(ContextCompilerV2Error::GroupLimitExceeded);
    }
    if request.token_budget == 0
        || request.token_budget > request.model_profile.maximum_context_tokens
    {
        return Err(ContextCompilerV2Error::InvalidTokenBudget);
    }

    let mut by_id = BTreeMap::new();
    for candidate in request.candidates {
        candidate.validate_for(
            request.generation_vector_digest,
            &request.model_profile,
            &request.admission_snapshot,
        )?;
        let item_id = candidate.item_id.clone();
        if by_id.insert(item_id.clone(), candidate).is_some() {
            return Err(ContextCompilerV2Error::DuplicateCandidate(
                item_id.to_string(),
            ));
        }
    }

    normalize_mandatory_groups(&mut request.mandatory_groups, &by_id)?;
    let mandatory_groups_digest = compute_mandatory_groups_digest(&request.mandatory_groups);
    let legacy_candidates = by_id
        .values()
        .map(ContextCandidateV2::to_legacy)
        .collect::<Result<Vec<_>, _>>()?;
    let legacy_request = legacy::ContextCompilationRequestV2 {
        compilation_id: request.compilation_id.clone(),
        objective_digest: request.objective_digest,
        prompt_portfolio_digest: request.prompt_portfolio_digest,
        generation_vector_digest: request.generation_vector_digest,
        model_profile: request.model_profile.to_legacy(),
        token_budget: request.token_budget,
        truncation_policy_digest: request.truncation_policy_digest,
        candidates: legacy_candidates,
        mandatory_groups: request.mandatory_groups,
    };
    let selection =
        legacy::compile_v2(legacy_request).map_err(ContextCompilerV2Error::SelectionEngine)?;

    let mut selected_candidates = Vec::with_capacity(selection.receipt.selected_item_ids.len());
    for item_id in &selection.receipt.selected_item_ids {
        selected_candidates.push(
            by_id
                .get(item_id)
                .cloned()
                .ok_or(ContextCompilerV2Error::SelectedSetMismatch)?,
        );
    }
    let selected_binding_digest = compute_selected_binding_digest(&selected_candidates);
    let model_profile_digest = request.model_profile.digest();
    let mut receipt = ContextCompilationReceiptV2 {
        compilation_id: request.compilation_id,
        objective_digest: request.objective_digest,
        prompt_portfolio_digest: request.prompt_portfolio_digest,
        generation_vector_digest: request.generation_vector_digest,
        model_profile_digest,
        admission_issuer_digest: request.admission_snapshot.issuer_digest,
        admission_snapshot_digest: request.admission_snapshot.snapshot_digest,
        revocation_frontier_digest: request.admission_snapshot.revocation_frontier_digest,
        admission_witness_digest: request.admission_snapshot.witness_digest,
        admission_verifier_digest: request.admission_snapshot.verifier_digest,
        admission_verification_digest: request.admission_snapshot.verification_digest,
        admission_observed_unix_ms: request.admission_snapshot.observed_unix_ms,
        candidate_set_digest: selection.receipt.candidate_set_digest,
        mandatory_groups_digest,
        selected_binding_digest,
        selected_item_ids: selection.receipt.selected_item_ids,
        omitted_item_ids: selection.receipt.omitted_item_ids,
        used_tokens: selection.receipt.used_tokens,
        token_upper_bound: selection.receipt.token_upper_bound,
        truncation_policy_digest: selection.receipt.truncation_policy_digest,
        context_digest: selection.receipt.context_digest,
        selection_engine_receipt_digest: selection.receipt.receipt_digest,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    let compiled = CompiledContextV2 {
        receipt,
        selected_candidates,
        model_profile: request.model_profile,
    };
    compiled.validate()?;
    Ok(compiled)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextPayloadItemV2 {
    item_id: StableId,
    content: Vec<u8>,
}

impl ContextPayloadItemV2 {
    #[must_use]
    pub fn new(item_id: StableId, content: Vec<u8>) -> Self {
        Self { item_id, content }
    }

    #[must_use]
    pub fn item_id(&self) -> &StableId {
        &self.item_id
    }

    #[must_use]
    pub fn content(&self) -> &[u8] {
        &self.content
    }
}

pub trait ContextSerializerV2 {
    fn serializer_digest(&self) -> Digest32;

    fn serialize(
        &self,
        profile: &ContextModelProfileV2,
        ordered_items: &[ContextPayloadItemV2],
    ) -> Result<Vec<u8>, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextSerializationReceiptV2 {
    pub serialization_id: StableId,
    pub compilation_receipt_digest: Digest32,
    pub selected_binding_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub serializer_digest: Digest32,
    pub selected_item_ids: Vec<StableId>,
    pub realization_digest: Digest32,
    pub payload_digest: Digest32,
    pub serialized_token_count: u64,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl ContextSerializationReceiptV2 {
    fn validate_for(
        &self,
        compiled: &CompiledContextV2,
        payload: &[u8],
    ) -> Result<(), ContextCompilerV2Error> {
        compiled.validate()?;
        for (name, digest) in [
            ("compilation_receipt", self.compilation_receipt_digest),
            ("selected_binding", self.selected_binding_digest),
            ("model_profile", self.model_profile_digest),
            ("serializer", self.serializer_digest),
            ("realization", self.realization_digest),
            ("payload", self.payload_digest),
            ("serialization_receipt", self.receipt_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.compilation_receipt_digest != compiled.receipt.receipt_digest
            || self.selected_binding_digest != compiled.receipt.selected_binding_digest
            || self.model_profile_digest != compiled.receipt.model_profile_digest
            || self.serializer_digest != compiled.model_profile.serializer_digest
            || self.selected_item_ids != compiled.receipt.selected_item_ids
            || self.realization_digest
                != compute_realization_digest(
                    &compiled.selected_candidates,
                    self.serializer_digest,
                )
            || self.payload_digest != Digest32::of_bytes(payload)
        {
            return Err(ContextCompilerV2Error::SerializationMismatch);
        }
        if self.serialized_token_count == 0
            || self.serialized_token_count > compiled.receipt.token_upper_bound
            || self.serialized_token_count > compiled.model_profile.maximum_context_tokens
        {
            return Err(ContextCompilerV2Error::SerializedTokenBudgetExceeded {
                actual_tokens: self.serialized_token_count,
                token_budget: compiled.receipt.token_upper_bound,
            });
        }
        if self.authority.grants_any() {
            return Err(ContextCompilerV2Error::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch(
                "serialization_receipt",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(SERIALIZATION_DOMAIN);
        push_id(&mut bytes, &self.serialization_id);
        for digest in [
            self.compilation_receipt_digest,
            self.selected_binding_digest,
            self.model_profile_digest,
            self.serializer_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_ids(&mut bytes, &self.selected_item_ids);
        push_digest(&mut bytes, self.realization_digest);
        push_digest(&mut bytes, self.payload_digest);
        push_u64(&mut bytes, self.serialized_token_count);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SerializedContextV2 {
    receipt: ContextSerializationReceiptV2,
    payload: Vec<u8>,
}

impl SerializedContextV2 {
    pub fn validate_for(&self, compiled: &CompiledContextV2) -> Result<(), ContextCompilerV2Error> {
        self.receipt.validate_for(compiled, &self.payload)
    }

    #[must_use]
    pub const fn receipt(&self) -> &ContextSerializationReceiptV2 {
        &self.receipt
    }

    #[must_use]
    pub fn payload(&self) -> &[u8] {
        &self.payload
    }
}

/// Serialize actual selected bytes and measure the final payload with the exact
/// tokenizer. The final token count, not the selection estimate, enforces the
/// provider-facing budget.
pub fn serialize_context_v2(
    compiled: &CompiledContextV2,
    serialization_id: StableId,
    payload_items: Vec<ContextPayloadItemV2>,
    serializer: &impl ContextSerializerV2,
    tokenizer: &impl ExactContextTokenizerV2,
) -> Result<SerializedContextV2, ContextCompilerV2Error> {
    compiled.validate()?;
    let serializer_digest = serializer.serializer_digest();
    ensure_digest("serializer", serializer_digest)?;
    if serializer_digest != compiled.model_profile.serializer_digest {
        return Err(ContextCompilerV2Error::SerializerIdentityMismatch);
    }
    let tokenizer_digest = tokenizer.tokenizer_digest();
    ensure_digest("tokenizer", tokenizer_digest)?;
    if tokenizer_digest != compiled.model_profile.tokenizer_digest {
        return Err(ContextCompilerV2Error::TokenizerIdentityMismatch);
    }

    let ordered_items = bind_payload_items(compiled, payload_items)?;
    let payload = serializer
        .serialize(&compiled.model_profile, &ordered_items)
        .map_err(ContextCompilerV2Error::SerializationFailure)?;
    if payload.is_empty() {
        return Err(ContextCompilerV2Error::EmptySerializedPayload);
    }
    let serialized_token_count = tokenizer
        .count_tokens(&payload)
        .map_err(ContextCompilerV2Error::TokenizerFailure)?;
    if serialized_token_count == 0
        || serialized_token_count > compiled.receipt.token_upper_bound
        || serialized_token_count > compiled.model_profile.maximum_context_tokens
    {
        return Err(ContextCompilerV2Error::SerializedTokenBudgetExceeded {
            actual_tokens: serialized_token_count,
            token_budget: compiled.receipt.token_upper_bound,
        });
    }

    let mut receipt = ContextSerializationReceiptV2 {
        serialization_id,
        compilation_receipt_digest: compiled.receipt.receipt_digest,
        selected_binding_digest: compiled.receipt.selected_binding_digest,
        model_profile_digest: compiled.receipt.model_profile_digest,
        serializer_digest,
        selected_item_ids: compiled.receipt.selected_item_ids.clone(),
        realization_digest: compute_realization_digest(
            &compiled.selected_candidates,
            serializer_digest,
        ),
        payload_digest: Digest32::of_bytes(&payload),
        serialized_token_count,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    let serialized = SerializedContextV2 { receipt, payload };
    serialized.validate_for(compiled)?;
    Ok(serialized)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextAttachmentV2 {
    attachment_id: StableId,
    compilation_receipt_digest: Digest32,
    serialization_receipt_digest: Digest32,
    generation_vector_digest: Digest32,
    model_profile_digest: Digest32,
    admission_issuer_digest: Digest32,
    admission_snapshot_digest: Digest32,
    revocation_frontier_digest: Digest32,
    admission_witness_digest: Digest32,
    admission_verifier_digest: Digest32,
    admission_verification_digest: Digest32,
    revalidated_at_unix_ms: u64,
    revalidation_digest: Digest32,
    payload_digest: Digest32,
    serialized_token_count: u64,
    selected_item_ids: Vec<StableId>,
    payload: Vec<u8>,
    attachment_digest: Digest32,
    authority: AuthorityPosture,
}

impl ContextAttachmentV2 {
    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("compilation_receipt", self.compilation_receipt_digest),
            ("serialization_receipt", self.serialization_receipt_digest),
            ("generation_vector", self.generation_vector_digest),
            ("model_profile", self.model_profile_digest),
            ("admission_issuer", self.admission_issuer_digest),
            ("admission_snapshot", self.admission_snapshot_digest),
            ("revocation_frontier", self.revocation_frontier_digest),
            ("admission_witness", self.admission_witness_digest),
            ("admission_verifier", self.admission_verifier_digest),
            ("admission_verification", self.admission_verification_digest),
            ("revalidation", self.revalidation_digest),
            ("payload", self.payload_digest),
            ("attachment", self.attachment_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.revalidated_at_unix_ms == 0 {
            return Err(ContextCompilerV2Error::InvalidAdmissionSnapshotTime);
        }
        if self.payload_digest != Digest32::of_bytes(&self.payload) {
            return Err(ContextCompilerV2Error::AttachmentMismatch);
        }
        if self.serialized_token_count == 0 || self.serialized_token_count > MAX_CONTEXT_TOKENS_V2 {
            return Err(ContextCompilerV2Error::TokenBudgetExceeded);
        }
        if self.authority.grants_any() {
            return Err(ContextCompilerV2Error::AuthorityGranted);
        }
        if self.attachment_digest != self.compute_attachment_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch("attachment"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_attachment_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ATTACHMENT_DOMAIN);
        push_id(&mut bytes, &self.attachment_id);
        for digest in [
            self.compilation_receipt_digest,
            self.serialization_receipt_digest,
            self.generation_vector_digest,
            self.model_profile_digest,
            self.admission_issuer_digest,
            self.admission_snapshot_digest,
            self.revocation_frontier_digest,
            self.admission_witness_digest,
            self.admission_verifier_digest,
            self.admission_verification_digest,
            self.revalidation_digest,
            self.payload_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.revalidated_at_unix_ms);
        push_u64(&mut bytes, self.serialized_token_count);
        push_ids(&mut bytes, &self.selected_item_ids);
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn attachment_id(&self) -> &StableId {
        &self.attachment_id
    }

    #[must_use]
    pub const fn attachment_digest(&self) -> Digest32 {
        self.attachment_digest
    }

    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub const fn model_profile_digest(&self) -> Digest32 {
        self.model_profile_digest
    }

    #[must_use]
    pub fn payload(&self) -> &[u8] {
        &self.payload
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

/// Revalidate every selected trusted instruction/schema against a current
/// snapshot immediately before attachment. A newer revocation invalidates a
/// previously successful compilation.
pub fn build_attachment(
    compiled: &CompiledContextV2,
    serialized: SerializedContextV2,
    current_admission_snapshot: &ContextAdmissionSnapshotV2,
    attachment_id: StableId,
) -> Result<ContextAttachmentV2, ContextCompilerV2Error> {
    compiled.validate()?;
    serialized.validate_for(compiled)?;
    current_admission_snapshot.validate()?;
    if current_admission_snapshot.issuer_digest != compiled.receipt.admission_issuer_digest {
        return Err(ContextCompilerV2Error::AdmissionIssuerMismatch);
    }
    if current_admission_snapshot.observed_unix_ms < compiled.receipt.admission_observed_unix_ms {
        return Err(ContextCompilerV2Error::StaleAdmissionSnapshot);
    }

    let mut current_proofs = Vec::new();
    for candidate in &compiled.selected_candidates {
        if matches!(
            candidate.role,
            ContextRoleV2::TrustedInstruction | ContextRoleV2::Schema
        ) {
            current_proofs.push(current_admission_snapshot.verify_trusted_binding(
                &candidate.item_id,
                candidate.role,
                candidate.content_digest,
                candidate.source_digest,
            )?);
        }
    }

    let receipt = serialized.receipt;
    let payload = serialized.payload;
    let mut attachment = ContextAttachmentV2 {
        attachment_id,
        compilation_receipt_digest: compiled.receipt.receipt_digest,
        serialization_receipt_digest: receipt.receipt_digest,
        generation_vector_digest: compiled.receipt.generation_vector_digest,
        model_profile_digest: compiled.receipt.model_profile_digest,
        admission_issuer_digest: current_admission_snapshot.issuer_digest,
        admission_snapshot_digest: current_admission_snapshot.snapshot_digest,
        revocation_frontier_digest: current_admission_snapshot.revocation_frontier_digest,
        admission_witness_digest: current_admission_snapshot.witness_digest,
        admission_verifier_digest: current_admission_snapshot.verifier_digest,
        admission_verification_digest: current_admission_snapshot.verification_digest,
        revalidated_at_unix_ms: current_admission_snapshot.observed_unix_ms,
        revalidation_digest: compute_revalidation_digest(&current_proofs),
        payload_digest: receipt.payload_digest,
        serialized_token_count: receipt.serialized_token_count,
        selected_item_ids: compiled.receipt.selected_item_ids.clone(),
        payload,
        attachment_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    attachment.attachment_digest = attachment.compute_attachment_digest();
    attachment.validate()?;
    Ok(attachment)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextTransportEvidenceV2 {
    pub attempt_id: StableId,
    pub payload_digest: Digest32,
    pub provider_request_id: Option<StableId>,
    pub provider_ack_digest: Option<Digest32>,
    pub terminal_observed: bool,
    pub disposition: ContextDeliveryDispositionV2,
    pub observed_unix_ms: u64,
}

/// Transport boundary. The compiler passes the exact attachment payload bytes
/// to this adapter and only records Delivered when provider-attempt identity and
/// acknowledgement evidence are present.
pub trait ContextDeliveryAdapterV2 {
    fn adapter_digest(&self) -> Digest32;

    fn deliver(
        &self,
        attachment: &ContextAttachmentV2,
        payload: &[u8],
    ) -> Result<ContextTransportEvidenceV2, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextDeliveryReceiptV2 {
    attempt_id: StableId,
    attachment_digest: Digest32,
    adapter_digest: Digest32,
    payload_digest: Digest32,
    provider_request_id: Option<StableId>,
    provider_ack_digest: Option<Digest32>,
    terminal_observed: bool,
    disposition: ContextDeliveryDispositionV2,
    observed_unix_ms: u64,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl ContextDeliveryReceiptV2 {
    pub fn validate_for(
        &self,
        attachment: &ContextAttachmentV2,
    ) -> Result<(), ContextCompilerV2Error> {
        attachment.validate()?;
        for (name, digest) in [
            ("attachment", self.attachment_digest),
            ("delivery_adapter", self.adapter_digest),
            ("payload", self.payload_digest),
            ("delivery_receipt", self.receipt_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.attachment_digest != attachment.attachment_digest
            || self.payload_digest != attachment.payload_digest
        {
            return Err(ContextCompilerV2Error::DeliveryMismatch);
        }
        if let Some(provider_ack_digest) = self.provider_ack_digest {
            ensure_digest("provider_ack", provider_ack_digest)?;
        }
        match self.disposition {
            ContextDeliveryDispositionV2::Delivered => {
                if !self.terminal_observed
                    || self.provider_request_id.is_none()
                    || self.provider_ack_digest.is_none()
                {
                    return Err(ContextCompilerV2Error::MissingProviderAcknowledgement);
                }
            }
            ContextDeliveryDispositionV2::Rejected => {
                if !self.terminal_observed {
                    return Err(ContextCompilerV2Error::MissingTerminalObservation);
                }
            }
            ContextDeliveryDispositionV2::Indeterminate => {
                if self.terminal_observed {
                    return Err(ContextCompilerV2Error::InvalidDeliveryDisposition);
                }
            }
        }
        if self.observed_unix_ms == 0 {
            return Err(ContextCompilerV2Error::InvalidObservationTime);
        }
        if self.authority.grants_any() {
            return Err(ContextCompilerV2Error::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch("delivery_receipt"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(DELIVERY_DOMAIN);
        push_id(&mut bytes, &self.attempt_id);
        for digest in [self.attachment_digest, self.adapter_digest, self.payload_digest] {
            push_digest(&mut bytes, digest);
        }
        push_optional_id(&mut bytes, self.provider_request_id.as_ref());
        push_optional_digest(&mut bytes, self.provider_ack_digest);
        bytes.push(u8::from(self.terminal_observed));
        bytes.push(delivery_disposition_code(self.disposition));
        push_u64(&mut bytes, self.observed_unix_ms);
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub const fn disposition(&self) -> ContextDeliveryDispositionV2 {
        self.disposition
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

pub fn deliver_attachment(
    attachment: &ContextAttachmentV2,
    adapter: &impl ContextDeliveryAdapterV2,
) -> Result<ContextDeliveryReceiptV2, ContextCompilerV2Error> {
    attachment.validate()?;
    let adapter_digest = adapter.adapter_digest();
    ensure_digest("delivery_adapter", adapter_digest)?;
    let evidence = adapter
        .deliver(attachment, attachment.payload())
        .map_err(ContextCompilerV2Error::DeliveryAdapterFailure)?;
    ensure_digest("transport_payload", evidence.payload_digest)?;
    if evidence.payload_digest != attachment.payload_digest {
        return Err(ContextCompilerV2Error::DeliveryMismatch);
    }
    if let Some(provider_ack_digest) = evidence.provider_ack_digest {
        ensure_digest("provider_ack", provider_ack_digest)?;
    }

    let mut receipt = ContextDeliveryReceiptV2 {
        attempt_id: evidence.attempt_id,
        attachment_digest: attachment.attachment_digest,
        adapter_digest,
        payload_digest: evidence.payload_digest,
        provider_request_id: evidence.provider_request_id,
        provider_ack_digest: evidence.provider_ack_digest,
        terminal_observed: evidence.terminal_observed,
        disposition: evidence.disposition,
        observed_unix_ms: evidence.observed_unix_ms,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    receipt.validate_for(attachment)?;
    Ok(receipt)
}

fn normalize_mandatory_groups(
    groups: &mut [MandatoryContextGroupV2],
    candidates: &BTreeMap<StableId, ContextCandidateV2>,
) -> Result<(), ContextCompilerV2Error> {
    for group in groups.iter_mut() {
        ensure_digest("mandatory_group_reason", group.reason_digest)?;
        if group.item_ids.is_empty() {
            return Err(ContextCompilerV2Error::EmptyMandatoryGroup(
                group.group_id.to_string(),
            ));
        }
        group.item_ids.sort();
        let mut local_ids = BTreeSet::new();
        for item_id in &group.item_ids {
            if !local_ids.insert(item_id.clone()) {
                return Err(ContextCompilerV2Error::DuplicateMandatoryItem(
                    item_id.to_string(),
                ));
            }
            if !candidates.contains_key(item_id) {
                return Err(ContextCompilerV2Error::UnknownMandatoryItem(
                    item_id.to_string(),
                ));
            }
        }
    }
    groups.sort_by(|left, right| left.group_id.cmp(&right.group_id));
    let mut group_ids = BTreeSet::new();
    for group in groups {
        if !group_ids.insert(group.group_id.clone()) {
            return Err(ContextCompilerV2Error::DuplicateMandatoryGroup(
                group.group_id.to_string(),
            ));
        }
    }
    Ok(())
}

fn bind_payload_items(
    compiled: &CompiledContextV2,
    payload_items: Vec<ContextPayloadItemV2>,
) -> Result<Vec<ContextPayloadItemV2>, ContextCompilerV2Error> {
    if payload_items.len() != compiled.selected_candidates.len() {
        return Err(ContextCompilerV2Error::PayloadItemSetMismatch);
    }
    let mut by_id = BTreeMap::new();
    for item in payload_items {
        let item_id = item.item_id.clone();
        if by_id.insert(item_id.clone(), item).is_some() {
            return Err(ContextCompilerV2Error::DuplicatePayloadItem(
                item_id.to_string(),
            ));
        }
    }
    let mut ordered = Vec::with_capacity(compiled.selected_candidates.len());
    for candidate in &compiled.selected_candidates {
        let item = by_id
            .remove(&candidate.item_id)
            .ok_or_else(|| ContextCompilerV2Error::MissingPayloadItem(candidate.item_id.to_string()))?;
        if Digest32::of_bytes(&item.content) != candidate.content_digest {
            return Err(ContextCompilerV2Error::PayloadContentMismatch(
                candidate.item_id.to_string(),
            ));
        }
        ordered.push(item);
    }
    if let Some(unexpected) = by_id.keys().next() {
        return Err(ContextCompilerV2Error::UnexpectedPayloadItem(
            unexpected.to_string(),
        ));
    }
    Ok(ordered)
}

fn compute_admission_snapshot_digest<'a>(
    issuer_digest: Digest32,
    source_snapshot_digest: Digest32,
    revocation_frontier_digest: Digest32,
    witness_digest: Digest32,
    verifier_digest: Digest32,
    verification_digest: Digest32,
    observed_unix_ms: u64,
    records: impl IntoIterator<Item = &'a ContextAdmissionRecordV2>,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(ADMISSION_SNAPSHOT_DOMAIN);
    for digest in [
        issuer_digest,
        source_snapshot_digest,
        revocation_frontier_digest,
        witness_digest,
        verifier_digest,
        verification_digest,
    ] {
        push_digest(&mut bytes, digest);
    }
    push_u64(&mut bytes, observed_unix_ms);
    for record in records {
        push_id(&mut bytes, &record.item_id);
        bytes.push(role_code(record.role));
        for digest in [
            record.content_digest,
            record.source_digest,
            record.admission_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, record.admitted_at_unix_ms);
        push_optional_u64(&mut bytes, record.expires_at_unix_ms);
        push_optional_u64(&mut bytes, record.revoked_at_unix_ms);
        push_optional_digest(&mut bytes, record.revocation_digest);
    }
    Digest32::of_bytes(&bytes)
}

fn compute_mandatory_groups_digest(groups: &[MandatoryContextGroupV2]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(MANDATORY_GROUPS_DOMAIN);
    push_len(&mut bytes, groups.len());
    for group in groups {
        push_id(&mut bytes, &group.group_id);
        push_ids(&mut bytes, &group.item_ids);
        push_digest(&mut bytes, group.reason_digest);
    }
    Digest32::of_bytes(&bytes)
}

fn compute_selected_binding_digest(candidates: &[ContextCandidateV2]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(SELECTED_BINDING_DOMAIN);
    push_len(&mut bytes, candidates.len());
    for candidate in candidates {
        push_id(&mut bytes, &candidate.item_id);
        bytes.push(role_code(candidate.role));
        push_digest(&mut bytes, candidate.content_digest);
        push_digest(&mut bytes, candidate.source_digest);
        push_digest(&mut bytes, candidate.tokenization.receipt_digest);
        push_optional_digest(
            &mut bytes,
            candidate
                .trusted_admission
                .as_ref()
                .map(VerifiedContextAdmissionV2::proof_digest),
        );
    }
    Digest32::of_bytes(&bytes)
}

fn compute_realization_digest(
    candidates: &[ContextCandidateV2],
    serializer_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(REALIZATION_DOMAIN);
    push_digest(&mut bytes, serializer_digest);
    push_len(&mut bytes, candidates.len());
    for candidate in candidates {
        push_id(&mut bytes, &candidate.item_id);
        push_digest(&mut bytes, candidate.content_digest);
    }
    Digest32::of_bytes(&bytes)
}

fn compute_revalidation_digest(proofs: &[VerifiedContextAdmissionV2]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(REVALIDATION_DOMAIN);
    push_len(&mut bytes, proofs.len());
    for proof in proofs {
        push_id(&mut bytes, &proof.item_id);
        push_digest(&mut bytes, proof.proof_digest);
    }
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ContextCompilerV2Error {
    SelectionEngine(legacy::ContextCompilerV2Error),
    EmptyDigest(&'static str),
    DigestMismatch(&'static str),
    CandidateLimitExceeded,
    GroupLimitExceeded,
    InvalidModelContextLimit,
    InvalidTokenBudget,
    InvalidTokenCount(String),
    TokenizerFailure(String),
    TokenizerIdentityMismatch,
    SerializerIdentityMismatch,
    SerializationFailure(String),
    EmptySerializedPayload,
    DuplicateCandidate(String),
    DuplicateMandatoryGroup(String),
    EmptyMandatoryGroup(String),
    DuplicateMandatoryItem(String),
    UnknownMandatoryItem(String),
    GenerationVectorMismatch(String),
    TokenizationItemMismatch(String),
    TokenizerMismatch(String),
    ValueOutOfRange(String),
    SecretRejected(String),
    MissingTrustedAdmission(String),
    EvidenceRoleConfusion(String),
    DuplicateAdmissionRecord(String),
    AdmissionVerificationFailure(String),
    AdmissionRoleNotTrusted(String),
    AdmissionMissing(String),
    AdmissionBindingMismatch(String),
    AdmissionRevoked(String),
    AdmissionExpired(String),
    AdmissionSnapshotMismatch(String),
    AdmissionIssuerMismatch,
    InvalidAdmissionSnapshotTime,
    InvalidAdmissionRecordTime(String),
    InvalidRevocationMetadata(String),
    StaleAdmissionSnapshot,
    TokenBudgetExceeded,
    SelectedSetMismatch,
    PayloadItemSetMismatch,
    DuplicatePayloadItem(String),
    MissingPayloadItem(String),
    UnexpectedPayloadItem(String),
    PayloadContentMismatch(String),
    SerializedTokenBudgetExceeded {
        actual_tokens: u64,
        token_budget: u64,
    },
    SerializationMismatch,
    AttachmentMismatch,
    DeliveryMismatch,
    DeliveryAdapterFailure(String),
    MissingProviderAcknowledgement,
    MissingTerminalObservation,
    InvalidDeliveryDisposition,
    InvalidObservationTime,
    AuthorityGranted,
}

impl fmt::Display for ContextCompilerV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ContextCompilerV2Error {}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), ContextCompilerV2Error> {
    if digest.is_zero() {
        return Err(ContextCompilerV2Error::EmptyDigest(name));
    }
    Ok(())
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, value);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_optional_id(bytes: &mut Vec<u8>, value: Option<&StableId>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_id(bytes, value);
        }
        None => bytes.push(0),
    }
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

fn push_optional_u64(bytes: &mut Vec<u8>, value: Option<u64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_u64(bytes, value);
        }
        None => bytes.push(0),
    }
}

const fn role_code(role: ContextRoleV2) -> u8 {
    match role {
        ContextRoleV2::TrustedInstruction => 0,
        ContextRoleV2::Schema => 1,
        ContextRoleV2::UntrustedEvidence => 2,
    }
}

const fn delivery_disposition_code(disposition: ContextDeliveryDispositionV2) -> u8 {
    match disposition {
        ContextDeliveryDispositionV2::Delivered => 0,
        ContextDeliveryDispositionV2::Rejected => 1,
        ContextDeliveryDispositionV2::Indeterminate => 2,
    }
}

#[cfg(test)]
#[path = "proof_v2_tests.rs"]
mod tests;
