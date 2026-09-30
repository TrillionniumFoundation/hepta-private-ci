//! Verified-admission, exact-tokenizer context compilation and provider evidence.
//!
//! V2 is the normative context path. It accepts only admission evidence verified
//! by an explicit admission verifier, binds mandatory-group provenance, verifies
//! actual selected item bytes before serialization, tokenizes the final payload
//! bytes with the exact model-profile tokenizer, and revalidates current
//! admission/revocation state at attachment and immediately before dispatch.
//!
//! This crate never performs a model/provider/network effect. Instead it emits an
//! opaque pre-dispatch safety witness whose linkage to the exact provider attempt
//! must be authenticated by the existing provider invocation evidence. Delivery
//! receipts are created only from a validated ProviderInvocationReceipt plus an
//! independent delivery verifier that receives the current preparation.
//! Admission verifiers, serializers, tokenizers and evidence verifiers remain
//! explicit trusted adapter seams that require product-host qualification.

use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

pub const MAX_CONTEXT_CANDIDATES_V2: usize = 4_096;
pub const MAX_CONTEXT_GROUPS_V2: usize = 256;
pub const MAX_MANDATORY_REFERENCES_V2: usize = 4_096;
pub const MAX_REVOKED_ADMISSIONS_V2: usize = 4_096;
pub const MAX_CONTEXT_ITEM_BYTES_V2: usize = 1024 * 1024;
pub const MAX_REALIZATION_BYTES_V2: usize = 16 * 1024 * 1024;
pub const MAX_CONTEXT_TOKENS_V2: u64 = 1_000_000;
pub const MAX_SERIALIZED_PAYLOAD_BYTES_V2: usize = 16 * 1024 * 1024;

const TOKENIZATION_DOMAIN: &[u8] = b"hepta.context-tokenization.v2";
const MODEL_PROFILE_DOMAIN: &[u8] = b"hepta.context-model-profile.v2";
const ADMISSION_RECORD_DOMAIN: &[u8] = b"hepta.context-admission-record.v2";
const ADMISSION_SNAPSHOT_DOMAIN: &[u8] = b"hepta.context-admission-snapshot.v2";
const VERIFIED_SNAPSHOT_DOMAIN: &[u8] = b"hepta.context-verified-admission-snapshot.v2";
const VERIFIED_ADMISSION_DOMAIN: &[u8] = b"hepta.context-verified-admission.v2";
const CANDIDATE_SET_DOMAIN: &[u8] = b"hepta.context-candidate-set.v2";
const MANDATORY_GROUPS_DOMAIN: &[u8] = b"hepta.context-mandatory-groups.v2";
const CONTEXT_DOMAIN: &[u8] = b"hepta.context-compilation.v2";
const COMPILATION_RECEIPT_DOMAIN: &[u8] = b"hepta.context-compilation-receipt.v2";
const REALIZATION_MANIFEST_DOMAIN: &[u8] = b"hepta.context-realization-manifest.v2";
const SERIALIZATION_DOMAIN: &[u8] = b"hepta.context-serialization.v2";
const ATTACHMENT_DOMAIN: &[u8] = b"hepta.context-attachment.v2";
const DELIVERY_PREPARATION_DOMAIN: &[u8] = b"hepta.context-delivery-preparation.v2";
const DELIVERY_DOMAIN: &[u8] = b"hepta.context-delivery-receipt.v2";

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ContextRoleV2 {
    TrustedInstruction,
    Schema,
    UntrustedEvidence,
}

pub trait ExactTokenizerV2 {
    fn tokenizer_digest(&self) -> Digest32;

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error>;
}

pub trait ContextAdmissionVerifierV2 {
    fn verifier_digest(&self) -> Digest32;

    fn verify_record(&self, record: &ContextAdmissionRecordV2) -> bool;

    fn verify_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool;
}

pub trait ContextSerializerV2 {
    fn serializer_digest(&self) -> Digest32;

    fn template_digest(&self) -> Digest32;

    fn tool_schema_digest(&self) -> Digest32;

    fn serialize(&self, items: &[ContextRealizedItemV2])
    -> Result<Vec<u8>, ContextCompilerV2Error>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextProviderDeliveryDecisionV2 {
    pub evidence_digest: Digest32,
    pub recorded_at_unix_ms: u64,
}

pub trait ContextProviderDeliveryVerifierV2 {
    fn verifier_digest(&self) -> Digest32;

    /// Authenticate provider-owned attempt evidence against this exact
    /// pre-dispatch preparation. The provider witness remains provider-owned;
    /// context.compiler does not reinterpret it as a raw preparation digest.
    fn verify_delivery(
        &self,
        receipt: &ProviderInvocationReceipt,
        preparation: &ContextDeliveryPreparationV2,
    ) -> Result<ContextProviderDeliveryDecisionV2, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TokenizationReceiptV2 {
    item_id: StableId,
    content_digest: Digest32,
    tokenizer_digest: Digest32,
    token_count: u64,
    receipt_digest: Digest32,
}

impl TokenizationReceiptV2 {
    pub fn from_exact_bytes(
        item_id: StableId,
        content: &[u8],
        tokenizer: &impl ExactTokenizerV2,
    ) -> Result<Self, ContextCompilerV2Error> {
        if content.len() > MAX_CONTEXT_ITEM_BYTES_V2 {
            return Err(ContextCompilerV2Error::CandidateContentTooLarge(
                item_id.to_string(),
            ));
        }
        let tokenizer_digest = tokenizer.tokenizer_digest();
        ensure_digest("tokenizer", tokenizer_digest)?;
        let token_count = tokenizer.count_tokens(content)?;
        let mut receipt = Self {
            item_id,
            content_digest: Digest32::of_bytes(content),
            tokenizer_digest,
            token_count,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.compute_digest();
        receipt.validate()?;
        Ok(receipt)
    }

    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
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
pub struct ContextAdmissionBindingV2 {
    pub item_id: StableId,
    pub role: ContextRoleV2,
    pub content_digest: Digest32,
    pub source_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub scope_digest: Digest32,
    pub authority_domain_digest: Digest32,
    pub contains_secret: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextAdmissionRecordV2 {
    pub admission_id: StableId,
    pub item_id: StableId,
    pub role: ContextRoleV2,
    pub content_digest: Digest32,
    pub source_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub scope_digest: Digest32,
    pub authority_domain_digest: Digest32,
    pub contains_secret: bool,
    pub issued_unix_ms: u64,
    pub expires_unix_ms: u64,
    pub record_digest: Digest32,
}

impl ContextAdmissionRecordV2 {
    pub fn new(
        admission_id: StableId,
        binding: ContextAdmissionBindingV2,
        issued_unix_ms: u64,
        expires_unix_ms: u64,
    ) -> Result<Self, ContextCompilerV2Error> {
        let mut record = Self {
            admission_id,
            item_id: binding.item_id,
            role: binding.role,
            content_digest: binding.content_digest,
            source_digest: binding.source_digest,
            generation_vector_digest: binding.generation_vector_digest,
            scope_digest: binding.scope_digest,
            authority_domain_digest: binding.authority_domain_digest,
            contains_secret: binding.contains_secret,
            issued_unix_ms,
            expires_unix_ms,
            record_digest: Digest32::ZERO,
        };
        record.record_digest = record.compute_digest();
        record.validate_shape()?;
        Ok(record)
    }

    pub fn validate_shape(&self) -> Result<(), ContextCompilerV2Error> {
        ensure_digest("admission_content", self.content_digest)?;
        ensure_digest("admission_source", self.source_digest)?;
        ensure_digest("admission_generation_vector", self.generation_vector_digest)?;
        ensure_digest("admission_scope", self.scope_digest)?;
        ensure_digest("admission_authority_domain", self.authority_domain_digest)?;
        if self.issued_unix_ms == 0 || self.expires_unix_ms <= self.issued_unix_ms {
            return Err(ContextCompilerV2Error::InvalidAdmissionTime(
                self.admission_id.to_string(),
            ));
        }
        if self.record_digest != self.compute_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch("admission_record"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ADMISSION_RECORD_DOMAIN);
        push_id(&mut bytes, &self.admission_id);
        push_id(&mut bytes, &self.item_id);
        bytes.push(role_code(self.role));
        push_digest(&mut bytes, self.content_digest);
        push_digest(&mut bytes, self.source_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_digest(&mut bytes, self.scope_digest);
        push_digest(&mut bytes, self.authority_domain_digest);
        bytes.push(u8::from(self.contains_secret));
        push_u64(&mut bytes, self.issued_unix_ms);
        push_u64(&mut bytes, self.expires_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextAdmissionSnapshotV2 {
    pub snapshot_id: StableId,
    pub scope_digest: Digest32,
    pub authority_domain_digest: Digest32,
    pub observed_unix_ms: u64,
    pub revocation_epoch: u64,
    pub revoked_admission_ids: Vec<StableId>,
    pub revocation_set_complete: bool,
    pub predecessor_snapshot_digest: Option<Digest32>,
    pub snapshot_digest: Digest32,
}

impl ContextAdmissionSnapshotV2 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        snapshot_id: StableId,
        scope_digest: Digest32,
        authority_domain_digest: Digest32,
        observed_unix_ms: u64,
        revocation_epoch: u64,
        mut revoked_admission_ids: Vec<StableId>,
        revocation_set_complete: bool,
        predecessor_snapshot_digest: Option<Digest32>,
    ) -> Result<Self, ContextCompilerV2Error> {
        if revoked_admission_ids.len() > MAX_REVOKED_ADMISSIONS_V2 {
            return Err(ContextCompilerV2Error::RevocationLimitExceeded);
        }
        revoked_admission_ids.sort();
        for pair in revoked_admission_ids.windows(2) {
            if pair[0] == pair[1] {
                return Err(ContextCompilerV2Error::DuplicateRevocation(
                    pair[0].to_string(),
                ));
            }
        }
        let mut snapshot = Self {
            snapshot_id,
            scope_digest,
            authority_domain_digest,
            observed_unix_ms,
            revocation_epoch,
            revoked_admission_ids,
            revocation_set_complete,
            predecessor_snapshot_digest,
            snapshot_digest: Digest32::ZERO,
        };
        snapshot.snapshot_digest = snapshot.compute_digest();
        snapshot.validate_shape()?;
        Ok(snapshot)
    }

    pub fn validate_shape(&self) -> Result<(), ContextCompilerV2Error> {
        ensure_digest("admission_snapshot_scope", self.scope_digest)?;
        ensure_digest(
            "admission_snapshot_authority_domain",
            self.authority_domain_digest,
        )?;
        if self.observed_unix_ms == 0 {
            return Err(ContextCompilerV2Error::InvalidAdmissionSnapshotTime);
        }
        if self.revoked_admission_ids.len() > MAX_REVOKED_ADMISSIONS_V2 {
            return Err(ContextCompilerV2Error::RevocationLimitExceeded);
        }
        if !self.revocation_set_complete {
            return Err(ContextCompilerV2Error::IncompleteRevocationSnapshot);
        }
        if let Some(predecessor) = self.predecessor_snapshot_digest {
            ensure_digest("admission_snapshot_predecessor", predecessor)?;
        }
        for pair in self.revoked_admission_ids.windows(2) {
            if pair[0] >= pair[1] {
                return Err(ContextCompilerV2Error::NonCanonicalRevocationList);
            }
        }
        if self.snapshot_digest != self.compute_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch("admission_snapshot"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ADMISSION_SNAPSHOT_DOMAIN);
        push_id(&mut bytes, &self.snapshot_id);
        push_digest(&mut bytes, self.scope_digest);
        push_digest(&mut bytes, self.authority_domain_digest);
        push_u64(&mut bytes, self.observed_unix_ms);
        push_u64(&mut bytes, self.revocation_epoch);
        push_ids(&mut bytes, &self.revoked_admission_ids);
        bytes.push(u8::from(self.revocation_set_complete));
        match self.predecessor_snapshot_digest {
            Some(predecessor) => {
                bytes.push(1);
                push_digest(&mut bytes, predecessor);
            }
            None => bytes.push(0),
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedAdmissionSnapshotV2 {
    snapshot: ContextAdmissionSnapshotV2,
    verifier_digest: Digest32,
    verification_digest: Digest32,
}

impl VerifiedAdmissionSnapshotV2 {
    #[must_use]
    pub fn snapshot_digest(&self) -> Digest32 {
        self.snapshot.snapshot_digest
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
    pub const fn scope_digest(&self) -> Digest32 {
        self.snapshot.scope_digest
    }

    #[must_use]
    pub const fn authority_domain_digest(&self) -> Digest32 {
        self.snapshot.authority_domain_digest
    }

    #[must_use]
    pub const fn observed_unix_ms(&self) -> u64 {
        self.snapshot.observed_unix_ms
    }

    #[must_use]
    pub const fn revocation_epoch(&self) -> u64 {
        self.snapshot.revocation_epoch
    }

    fn contains_revocation(&self, admission_id: &StableId) -> bool {
        self.snapshot
            .revoked_admission_ids
            .binary_search(admission_id)
            .is_ok()
    }
}

fn finish_verified_snapshot(
    snapshot: ContextAdmissionSnapshotV2,
    verifier_digest: Digest32,
) -> VerifiedAdmissionSnapshotV2 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(VERIFIED_SNAPSHOT_DOMAIN);
    push_digest(&mut bytes, snapshot.snapshot_digest);
    push_digest(&mut bytes, verifier_digest);
    VerifiedAdmissionSnapshotV2 {
        snapshot,
        verifier_digest,
        verification_digest: Digest32::of_bytes(&bytes),
    }
}

pub fn verify_admission_snapshot_v2(
    snapshot: ContextAdmissionSnapshotV2,
    verifier: &impl ContextAdmissionVerifierV2,
) -> Result<VerifiedAdmissionSnapshotV2, ContextCompilerV2Error> {
    snapshot.validate_shape()?;
    if snapshot.predecessor_snapshot_digest.is_some() {
        return Err(ContextCompilerV2Error::UnexpectedSnapshotPredecessor);
    }
    let verifier_digest = verifier.verifier_digest();
    ensure_digest("admission_verifier", verifier_digest)?;
    if !verifier.verify_snapshot(&snapshot) {
        return Err(ContextCompilerV2Error::AdmissionSnapshotUnverified);
    }
    Ok(finish_verified_snapshot(snapshot, verifier_digest))
}

pub fn verify_admission_snapshot_successor_v2(
    snapshot: ContextAdmissionSnapshotV2,
    predecessor: &VerifiedAdmissionSnapshotV2,
    verifier: &impl ContextAdmissionVerifierV2,
) -> Result<VerifiedAdmissionSnapshotV2, ContextCompilerV2Error> {
    snapshot.validate_shape()?;
    let verifier_digest = verifier.verifier_digest();
    ensure_digest("admission_verifier", verifier_digest)?;
    if verifier_digest != predecessor.verifier_digest() {
        return Err(ContextCompilerV2Error::AdmissionVerifierMismatch(
            "snapshot".to_string(),
        ));
    }
    if !verifier.verify_snapshot(&snapshot) {
        return Err(ContextCompilerV2Error::AdmissionSnapshotUnverified);
    }
    if snapshot.predecessor_snapshot_digest != Some(predecessor.snapshot_digest()) {
        return Err(ContextCompilerV2Error::SnapshotPredecessorMismatch);
    }
    if snapshot.scope_digest != predecessor.scope_digest()
        || snapshot.authority_domain_digest != predecessor.authority_domain_digest()
    {
        return Err(ContextCompilerV2Error::SnapshotDomainMismatch);
    }
    if snapshot.observed_unix_ms < predecessor.observed_unix_ms()
        || snapshot.revocation_epoch < predecessor.revocation_epoch()
    {
        return Err(ContextCompilerV2Error::StaleAdmissionSnapshot);
    }
    if snapshot.revocation_epoch == predecessor.revocation_epoch()
        && snapshot.revoked_admission_ids != predecessor.snapshot.revoked_admission_ids
    {
        return Err(ContextCompilerV2Error::RevocationFrontierMismatch);
    }
    for admission_id in &predecessor.snapshot.revoked_admission_ids {
        if snapshot
            .revoked_admission_ids
            .binary_search(admission_id)
            .is_err()
        {
            return Err(ContextCompilerV2Error::RevocationResurrection(
                admission_id.to_string(),
            ));
        }
    }
    Ok(finish_verified_snapshot(snapshot, verifier_digest))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedAdmissionV2 {
    admission_id: StableId,
    item_id: StableId,
    role: ContextRoleV2,
    content_digest: Digest32,
    source_digest: Digest32,
    generation_vector_digest: Digest32,
    scope_digest: Digest32,
    authority_domain_digest: Digest32,
    contains_secret: bool,
    expires_unix_ms: u64,
    verifier_digest: Digest32,
    verified_snapshot_digest: Digest32,
    verified_snapshot_verification_digest: Digest32,
    verified_revocation_epoch: u64,
    verified_at_unix_ms: u64,
    record_digest: Digest32,
    verification_digest: Digest32,
}

impl VerifiedAdmissionV2 {
    #[must_use]
    pub fn admission_id(&self) -> &StableId {
        &self.admission_id
    }

    #[must_use]
    pub const fn verifier_digest(&self) -> Digest32 {
        self.verifier_digest
    }

    #[must_use]
    pub const fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }

    fn validate_for_candidate(
        &self,
        candidate: &ContextCandidateV2,
        expected_scope_digest: Digest32,
        expected_authority_domain_digest: Digest32,
        expected_verifier_digest: Digest32,
    ) -> Result<(), ContextCompilerV2Error> {
        if self.item_id != candidate.item_id
            || self.role != candidate.role
            || self.content_digest != candidate.content_digest
            || self.source_digest != candidate.source_digest
            || self.generation_vector_digest != candidate.generation_vector_digest
            || self.scope_digest != expected_scope_digest
            || self.authority_domain_digest != expected_authority_domain_digest
        {
            return Err(ContextCompilerV2Error::AdmissionBindingMismatch(
                candidate.item_id.to_string(),
            ));
        }
        if self.verifier_digest != expected_verifier_digest {
            return Err(ContextCompilerV2Error::AdmissionVerifierMismatch(
                candidate.item_id.to_string(),
            ));
        }
        if self.contains_secret {
            return Err(ContextCompilerV2Error::SecretRejected(
                candidate.item_id.to_string(),
            ));
        }
        if self.verification_digest != self.compute_verification_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch("verified_admission"));
        }
        Ok(())
    }

    fn revalidate(
        &self,
        current_snapshot: &VerifiedAdmissionSnapshotV2,
    ) -> Result<(), ContextCompilerV2Error> {
        if self.scope_digest != current_snapshot.scope_digest()
            || self.authority_domain_digest != current_snapshot.authority_domain_digest()
        {
            return Err(ContextCompilerV2Error::AdmissionSnapshotDomainMismatch(
                self.item_id.to_string(),
            ));
        }
        if self.verifier_digest != current_snapshot.verifier_digest {
            return Err(ContextCompilerV2Error::AdmissionVerifierMismatch(
                self.item_id.to_string(),
            ));
        }
        if current_snapshot.revocation_epoch() < self.verified_revocation_epoch
            || current_snapshot.observed_unix_ms() < self.verified_at_unix_ms
        {
            return Err(ContextCompilerV2Error::StaleAdmissionSnapshot);
        }
        if current_snapshot.observed_unix_ms() >= self.expires_unix_ms {
            return Err(ContextCompilerV2Error::AdmissionExpired(
                self.admission_id.to_string(),
            ));
        }
        if current_snapshot.contains_revocation(&self.admission_id) {
            return Err(ContextCompilerV2Error::AdmissionRevoked(
                self.admission_id.to_string(),
            ));
        }
        Ok(())
    }

    fn compute_verification_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(VERIFIED_ADMISSION_DOMAIN);
        push_id(&mut bytes, &self.admission_id);
        push_id(&mut bytes, &self.item_id);
        bytes.push(role_code(self.role));
        push_digest(&mut bytes, self.content_digest);
        push_digest(&mut bytes, self.source_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_digest(&mut bytes, self.scope_digest);
        push_digest(&mut bytes, self.authority_domain_digest);
        bytes.push(u8::from(self.contains_secret));
        push_u64(&mut bytes, self.expires_unix_ms);
        push_digest(&mut bytes, self.verifier_digest);
        push_digest(&mut bytes, self.verified_snapshot_digest);
        push_digest(&mut bytes, self.verified_snapshot_verification_digest);
        push_u64(&mut bytes, self.verified_revocation_epoch);
        push_u64(&mut bytes, self.verified_at_unix_ms);
        push_digest(&mut bytes, self.record_digest);
        Digest32::of_bytes(&bytes)
    }
}

pub fn verify_admission_v2(
    record: ContextAdmissionRecordV2,
    snapshot: &VerifiedAdmissionSnapshotV2,
    verifier: &impl ContextAdmissionVerifierV2,
) -> Result<VerifiedAdmissionV2, ContextCompilerV2Error> {
    record.validate_shape()?;
    let verifier_digest = verifier.verifier_digest();
    ensure_digest("admission_verifier", verifier_digest)?;
    if verifier_digest != snapshot.verifier_digest {
        return Err(ContextCompilerV2Error::AdmissionVerifierMismatch(
            record.item_id.to_string(),
        ));
    }
    if record.scope_digest != snapshot.scope_digest()
        || record.authority_domain_digest != snapshot.authority_domain_digest()
    {
        return Err(ContextCompilerV2Error::AdmissionSnapshotDomainMismatch(
            record.item_id.to_string(),
        ));
    }
    if !verifier.verify_record(&record) {
        return Err(ContextCompilerV2Error::AdmissionRecordUnverified(
            record.admission_id.to_string(),
        ));
    }
    if record.issued_unix_ms > snapshot.observed_unix_ms() {
        return Err(ContextCompilerV2Error::AdmissionNotYetValid(
            record.admission_id.to_string(),
        ));
    }
    if snapshot.observed_unix_ms() >= record.expires_unix_ms {
        return Err(ContextCompilerV2Error::AdmissionExpired(
            record.admission_id.to_string(),
        ));
    }
    if snapshot.contains_revocation(&record.admission_id) {
        return Err(ContextCompilerV2Error::AdmissionRevoked(
            record.admission_id.to_string(),
        ));
    }
    if record.contains_secret {
        return Err(ContextCompilerV2Error::SecretRejected(
            record.item_id.to_string(),
        ));
    }
    let mut verified = VerifiedAdmissionV2 {
        admission_id: record.admission_id,
        item_id: record.item_id,
        role: record.role,
        content_digest: record.content_digest,
        source_digest: record.source_digest,
        generation_vector_digest: record.generation_vector_digest,
        scope_digest: record.scope_digest,
        authority_domain_digest: record.authority_domain_digest,
        contains_secret: record.contains_secret,
        expires_unix_ms: record.expires_unix_ms,
        verifier_digest,
        verified_snapshot_digest: snapshot.snapshot_digest(),
        verified_snapshot_verification_digest: snapshot.verification_digest(),
        verified_revocation_epoch: snapshot.revocation_epoch(),
        verified_at_unix_ms: snapshot.observed_unix_ms(),
        record_digest: record.record_digest,
        verification_digest: Digest32::ZERO,
    };
    verified.verification_digest = verified.compute_verification_digest();
    Ok(verified)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextModelProfileV2 {
    pub model_digest: Digest32,
    pub provider_id_digest: Digest32,
    pub provider_model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub serializer_digest: Digest32,
    pub template_digest: Digest32,
    pub tool_schema_digest: Digest32,
    pub maximum_context_tokens: u64,
}

impl ContextModelProfileV2 {
    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("model", self.model_digest),
            ("provider_id", self.provider_id_digest),
            ("provider_model", self.provider_model_digest),
            ("tokenizer", self.tokenizer_digest),
            ("serializer", self.serializer_digest),
            ("template", self.template_digest),
            ("tool_schema", self.tool_schema_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.maximum_context_tokens == 0 || self.maximum_context_tokens > MAX_CONTEXT_TOKENS_V2 {
            return Err(ContextCompilerV2Error::InvalidModelContextLimit);
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(MODEL_PROFILE_DOMAIN);
        for digest in [
            self.model_digest,
            self.provider_id_digest,
            self.provider_model_digest,
            self.tokenizer_digest,
            self.serializer_digest,
            self.template_digest,
            self.tool_schema_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.maximum_context_tokens);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCandidateV2 {
    pub item_id: StableId,
    pub role: ContextRoleV2,
    pub content_digest: Digest32,
    pub source_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub tokenization: TokenizationReceiptV2,
    pub expected_value: FixedQ32,
    pub admission: VerifiedAdmissionV2,
}

impl ContextCandidateV2 {
    fn validate(
        &self,
        expected_generation_vector_digest: Digest32,
        expected_scope_digest: Digest32,
        expected_authority_domain_digest: Digest32,
        expected_admission_verifier_digest: Digest32,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ContextCompilerV2Error> {
        ensure_digest("candidate_content", self.content_digest)?;
        ensure_digest("candidate_source", self.source_digest)?;
        ensure_digest("candidate_generation_vector", self.generation_vector_digest)?;
        if self.generation_vector_digest != expected_generation_vector_digest {
            return Err(ContextCompilerV2Error::GenerationVectorMismatch(
                self.item_id.to_string(),
            ));
        }
        self.tokenization.validate()?;
        if self.tokenization.item_id() != &self.item_id
            || self.tokenization.content_digest() != self.content_digest
        {
            return Err(ContextCompilerV2Error::TokenizationItemMismatch(
                self.item_id.to_string(),
            ));
        }
        if self.tokenization.tokenizer_digest() != profile.tokenizer_digest {
            return Err(ContextCompilerV2Error::TokenizerMismatch(
                self.item_id.to_string(),
            ));
        }
        if self.expected_value < FixedQ32::ZERO || self.expected_value > FixedQ32::ONE {
            return Err(ContextCompilerV2Error::ValueOutOfRange(
                self.item_id.to_string(),
            ));
        }
        self.admission.validate_for_candidate(
            self,
            expected_scope_digest,
            expected_authority_domain_digest,
            expected_admission_verifier_digest,
        )?;
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MandatoryContextGroupV2 {
    pub group_id: StableId,
    pub item_ids: Vec<StableId>,
    pub reason_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilationRequestV2 {
    pub compilation_id: StableId,
    pub objective_digest: Digest32,
    pub prompt_portfolio_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub scope_digest: Digest32,
    pub authority_domain_digest: Digest32,
    pub admission_verifier_digest: Digest32,
    pub model_profile: ContextModelProfileV2,
    pub token_budget: u64,
    pub truncation_policy_digest: Digest32,
    pub candidates: Vec<ContextCandidateV2>,
    pub mandatory_groups: Vec<MandatoryContextGroupV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilationReceiptV2 {
    compilation_id: StableId,
    objective_digest: Digest32,
    prompt_portfolio_digest: Digest32,
    generation_vector_digest: Digest32,
    scope_digest: Digest32,
    authority_domain_digest: Digest32,
    admission_verifier_digest: Digest32,
    model_profile_digest: Digest32,
    candidate_set_digest: Digest32,
    mandatory_groups_digest: Digest32,
    selected_item_ids: Vec<StableId>,
    omitted_item_ids: Vec<StableId>,
    used_tokens: u64,
    token_upper_bound: u64,
    truncation_policy_digest: Digest32,
    context_digest: Digest32,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl ContextCompilationReceiptV2 {
    #[must_use]
    pub const fn compilation_id(&self) -> &StableId {
        &self.compilation_id
    }

    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub const fn prompt_portfolio_digest(&self) -> Digest32 {
        self.prompt_portfolio_digest
    }

    #[must_use]
    pub const fn generation_vector_digest(&self) -> Digest32 {
        self.generation_vector_digest
    }

    #[must_use]
    pub const fn admission_verifier_digest(&self) -> Digest32 {
        self.admission_verifier_digest
    }

    #[must_use]
    pub const fn model_profile_digest(&self) -> Digest32 {
        self.model_profile_digest
    }

    #[must_use]
    pub fn selected_item_ids(&self) -> &[StableId] {
        &self.selected_item_ids
    }

    #[must_use]
    pub fn omitted_item_ids(&self) -> &[StableId] {
        &self.omitted_item_ids
    }

    #[must_use]
    pub const fn used_tokens(&self) -> u64 {
        self.used_tokens
    }

    #[must_use]
    pub const fn token_upper_bound(&self) -> u64 {
        self.token_upper_bound
    }

    #[must_use]
    pub const fn mandatory_groups_digest(&self) -> Digest32 {
        self.mandatory_groups_digest
    }

    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    #[must_use]
    pub const fn authority_domain_digest(&self) -> Digest32 {
        self.authority_domain_digest
    }

    #[must_use]
    pub const fn context_digest(&self) -> Digest32 {
        self.context_digest
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("objective", self.objective_digest),
            ("prompt_portfolio", self.prompt_portfolio_digest),
            ("generation_vector", self.generation_vector_digest),
            ("scope", self.scope_digest),
            ("authority_domain", self.authority_domain_digest),
            ("admission_verifier", self.admission_verifier_digest),
            ("model_profile", self.model_profile_digest),
            ("candidate_set", self.candidate_set_digest),
            ("mandatory_groups", self.mandatory_groups_digest),
            ("truncation_policy", self.truncation_policy_digest),
            ("context", self.context_digest),
            ("compilation_receipt", self.receipt_digest),
        ] {
            ensure_digest(name, digest)?;
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
    fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(COMPILATION_RECEIPT_DOMAIN);
        push_id(&mut bytes, &self.compilation_id);
        for digest in [
            self.objective_digest,
            self.prompt_portfolio_digest,
            self.generation_vector_digest,
            self.scope_digest,
            self.authority_domain_digest,
            self.admission_verifier_digest,
            self.model_profile_digest,
            self.candidate_set_digest,
            self.mandatory_groups_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_ids(&mut bytes, &self.selected_item_ids);
        push_ids(&mut bytes, &self.omitted_item_ids);
        push_u64(&mut bytes, self.used_tokens);
        push_u64(&mut bytes, self.token_upper_bound);
        push_digest(&mut bytes, self.truncation_policy_digest);
        push_digest(&mut bytes, self.context_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompiledContextV2 {
    receipt: ContextCompilationReceiptV2,
    selected_candidates: Vec<ContextCandidateV2>,
}

impl CompiledContextV2 {
    #[must_use]
    pub const fn receipt(&self) -> &ContextCompilationReceiptV2 {
        &self.receipt
    }

    #[must_use]
    pub fn selected_candidates(&self) -> &[ContextCandidateV2] {
        &self.selected_candidates
    }

    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        self.receipt.validate()?;
        let selected_ids = self
            .selected_candidates
            .iter()
            .map(|candidate| candidate.item_id.clone())
            .collect::<Vec<_>>();
        if selected_ids != self.receipt.selected_item_ids {
            return Err(ContextCompilerV2Error::SelectedSetMismatch);
        }
        let used_tokens = self
            .selected_candidates
            .iter()
            .try_fold(0_u64, |total, candidate| {
                total
                    .checked_add(candidate.tokenization.token_count())
                    .ok_or(ContextCompilerV2Error::Arithmetic)
            })?;
        if used_tokens != self.receipt.used_tokens {
            return Err(ContextCompilerV2Error::SelectedTokenCountMismatch);
        }
        for candidate in &self.selected_candidates {
            if candidate.generation_vector_digest != self.receipt.generation_vector_digest {
                return Err(ContextCompilerV2Error::SelectedSetMismatch);
            }
            candidate.admission.validate_for_candidate(
                candidate,
                self.receipt.scope_digest,
                self.receipt.authority_domain_digest,
                self.receipt.admission_verifier_digest,
            )?;
        }
        if self.receipt.context_digest != compute_context_digest(&self.selected_candidates) {
            return Err(ContextCompilerV2Error::DigestMismatch("context"));
        }
        Ok(())
    }
}

pub fn compile_v2(
    mut request: ContextCompilationRequestV2,
) -> Result<CompiledContextV2, ContextCompilerV2Error> {
    request.model_profile.validate()?;
    for (name, digest) in [
        ("objective", request.objective_digest),
        ("prompt_portfolio", request.prompt_portfolio_digest),
        ("generation_vector", request.generation_vector_digest),
        ("scope", request.scope_digest),
        ("authority_domain", request.authority_domain_digest),
        ("admission_verifier", request.admission_verifier_digest),
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

    request
        .candidates
        .sort_by(|left, right| left.item_id.cmp(&right.item_id));
    let mut by_id = BTreeMap::<StableId, ContextCandidateV2>::new();
    for candidate in request.candidates {
        candidate.validate(
            request.generation_vector_digest,
            request.scope_digest,
            request.authority_domain_digest,
            request.admission_verifier_digest,
            &request.model_profile,
        )?;
        let item_id = candidate.item_id.clone();
        if by_id.insert(item_id.clone(), candidate).is_some() {
            return Err(ContextCompilerV2Error::DuplicateCandidate(
                item_id.to_string(),
            ));
        }
    }

    request
        .mandatory_groups
        .sort_by(|left, right| left.group_id.cmp(&right.group_id));
    let mut group_ids = BTreeSet::new();
    let mut mandatory_reference_count = 0_usize;
    for group in &mut request.mandatory_groups {
        mandatory_reference_count = mandatory_reference_count
            .checked_add(group.item_ids.len())
            .ok_or(ContextCompilerV2Error::Arithmetic)?;
        if mandatory_reference_count > MAX_MANDATORY_REFERENCES_V2 {
            return Err(ContextCompilerV2Error::MandatoryReferenceLimitExceeded);
        }
        if !group_ids.insert(group.group_id.clone()) {
            return Err(ContextCompilerV2Error::DuplicateMandatoryGroup(
                group.group_id.to_string(),
            ));
        }
        ensure_digest("mandatory_group_reason", group.reason_digest)?;
        if group.item_ids.is_empty() {
            return Err(ContextCompilerV2Error::EmptyMandatoryGroup(
                group.group_id.to_string(),
            ));
        }
        group.item_ids.sort();
        for pair in group.item_ids.windows(2) {
            if pair[0] == pair[1] {
                return Err(ContextCompilerV2Error::DuplicateMandatoryItem(
                    pair[0].to_string(),
                ));
            }
        }
        for item_id in &group.item_ids {
            if !by_id.contains_key(item_id) {
                return Err(ContextCompilerV2Error::UnknownMandatoryItem(
                    item_id.to_string(),
                ));
            }
        }
    }

    let candidate_set_digest = compute_candidate_set_digest(by_id.values());
    let mandatory_groups_digest = compute_mandatory_groups_digest(&request.mandatory_groups);
    let mut mandatory_ids = by_id
        .values()
        .filter(|candidate| {
            matches!(
                candidate.role,
                ContextRoleV2::TrustedInstruction | ContextRoleV2::Schema
            )
        })
        .map(|candidate| candidate.item_id.clone())
        .collect::<BTreeSet<_>>();
    for group in &request.mandatory_groups {
        mandatory_ids.extend(group.item_ids.iter().cloned());
    }

    let mandatory_tokens = mandatory_ids.iter().try_fold(0_u64, |total, item_id| {
        let Some(candidate) = by_id.get(item_id) else {
            return Err(ContextCompilerV2Error::UnknownMandatoryItem(
                item_id.to_string(),
            ));
        };
        total
            .checked_add(candidate.tokenization.token_count())
            .ok_or(ContextCompilerV2Error::Arithmetic)
    })?;
    if mandatory_tokens > request.token_budget {
        return Err(ContextCompilerV2Error::InsufficientMandatoryBudget {
            required_tokens: mandatory_tokens,
            token_budget: request.token_budget,
        });
    }

    let mut selected = by_id
        .values()
        .filter(|candidate| mandatory_ids.contains(&candidate.item_id))
        .cloned()
        .collect::<Vec<_>>();
    selected.sort_by(context_placement_order);
    let mut optional = by_id
        .values()
        .filter(|candidate| !mandatory_ids.contains(&candidate.item_id))
        .cloned()
        .collect::<Vec<_>>();
    optional.sort_by(value_per_token_order);

    let mut used_tokens = mandatory_tokens;
    let mut omitted = Vec::new();
    for candidate in optional {
        let next = used_tokens
            .checked_add(candidate.tokenization.token_count())
            .ok_or(ContextCompilerV2Error::Arithmetic)?;
        if next > request.token_budget {
            omitted.push(candidate.item_id);
        } else {
            used_tokens = next;
            selected.push(candidate);
        }
    }
    selected.sort_by(context_placement_order);
    omitted.sort();

    let selected_ids = selected
        .iter()
        .map(|candidate| candidate.item_id.clone())
        .collect::<Vec<_>>();
    let model_profile_digest = request.model_profile.digest();
    let context_digest = compute_context_digest(&selected);
    let mut receipt = ContextCompilationReceiptV2 {
        compilation_id: request.compilation_id,
        objective_digest: request.objective_digest,
        prompt_portfolio_digest: request.prompt_portfolio_digest,
        generation_vector_digest: request.generation_vector_digest,
        scope_digest: request.scope_digest,
        authority_domain_digest: request.authority_domain_digest,
        admission_verifier_digest: request.admission_verifier_digest,
        model_profile_digest,
        candidate_set_digest,
        mandatory_groups_digest,
        selected_item_ids: selected_ids,
        omitted_item_ids: omitted,
        used_tokens,
        token_upper_bound: request.token_budget,
        truncation_policy_digest: request.truncation_policy_digest,
        context_digest,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    let compiled = CompiledContextV2 {
        receipt,
        selected_candidates: selected,
    };
    compiled.validate()?;
    Ok(compiled)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextRealizedItemV2 {
    pub item_id: StableId,
    pub role: ContextRoleV2,
    pub content: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextSerializationReceiptV2 {
    serialization_id: StableId,
    compilation_receipt_digest: Digest32,
    context_digest: Digest32,
    model_profile_digest: Digest32,
    selected_item_ids: Vec<StableId>,
    realization_manifest_digest: Digest32,
    template_digest: Digest32,
    tool_schema_digest: Digest32,
    tokenizer_digest: Digest32,
    payload_digest: Digest32,
    serialized_payload_bytes: u64,
    serialized_token_count: u64,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl ContextSerializationReceiptV2 {
    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub const fn serialized_payload_bytes(&self) -> u64 {
        self.serialized_payload_bytes
    }

    #[must_use]
    pub const fn serialized_token_count(&self) -> u64 {
        self.serialized_token_count
    }

    #[must_use]
    pub const fn realization_manifest_digest(&self) -> Digest32 {
        self.realization_manifest_digest
    }

    #[must_use]
    pub fn selected_item_ids(&self) -> &[StableId] {
        &self.selected_item_ids
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate_for(
        &self,
        compiled: &CompiledContextV2,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ContextCompilerV2Error> {
        compiled.validate()?;
        profile.validate()?;
        for (name, digest) in [
            ("compilation_receipt", self.compilation_receipt_digest),
            ("context", self.context_digest),
            ("model_profile", self.model_profile_digest),
            ("realization_manifest", self.realization_manifest_digest),
            ("template", self.template_digest),
            ("tool_schema", self.tool_schema_digest),
            ("tokenizer", self.tokenizer_digest),
            ("payload", self.payload_digest),
            ("serialization_receipt", self.receipt_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.compilation_receipt_digest != compiled.receipt.receipt_digest
            || self.context_digest != compiled.receipt.context_digest
            || self.model_profile_digest != compiled.receipt.model_profile_digest
            || self.model_profile_digest != profile.digest()
            || self.selected_item_ids != compiled.receipt.selected_item_ids
            || self.template_digest != profile.template_digest
            || self.tool_schema_digest != profile.tool_schema_digest
            || self.tokenizer_digest != profile.tokenizer_digest
        {
            return Err(ContextCompilerV2Error::SerializationMismatch);
        }
        if self.serialized_payload_bytes == 0
            || self.serialized_payload_bytes
                > u64::try_from(MAX_SERIALIZED_PAYLOAD_BYTES_V2).unwrap_or(u64::MAX)
        {
            return Err(ContextCompilerV2Error::SerializedPayloadTooLarge);
        }
        if self.serialized_token_count == 0
            || self.serialized_token_count > compiled.receipt.token_upper_bound
            || self.serialized_token_count > profile.maximum_context_tokens
        {
            return Err(ContextCompilerV2Error::SerializedTokenBudgetExceeded {
                serialized_tokens: self.serialized_token_count,
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
    fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(SERIALIZATION_DOMAIN);
        push_id(&mut bytes, &self.serialization_id);
        push_digest(&mut bytes, self.compilation_receipt_digest);
        push_digest(&mut bytes, self.context_digest);
        push_digest(&mut bytes, self.model_profile_digest);
        push_ids(&mut bytes, &self.selected_item_ids);
        push_digest(&mut bytes, self.realization_manifest_digest);
        push_digest(&mut bytes, self.template_digest);
        push_digest(&mut bytes, self.tool_schema_digest);
        push_digest(&mut bytes, self.tokenizer_digest);
        push_digest(&mut bytes, self.payload_digest);
        push_u64(&mut bytes, self.serialized_payload_bytes);
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
    #[must_use]
    pub const fn receipt(&self) -> &ContextSerializationReceiptV2 {
        &self.receipt
    }

    #[must_use]
    pub fn payload(&self) -> &[u8] {
        &self.payload
    }

    pub fn validate_for(
        &self,
        compiled: &CompiledContextV2,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ContextCompilerV2Error> {
        self.receipt.validate_for(compiled, profile)?;
        if self.payload.is_empty()
            || self.payload.len() > MAX_SERIALIZED_PAYLOAD_BYTES_V2
            || self.receipt.serialized_payload_bytes
                != u64::try_from(self.payload.len()).unwrap_or(u64::MAX)
            || self.receipt.payload_digest != Digest32::of_bytes(&self.payload)
        {
            return Err(ContextCompilerV2Error::SerializationMismatch);
        }
        Ok(())
    }
}

pub fn record_serialization(
    compiled: &CompiledContextV2,
    profile: &ContextModelProfileV2,
    serialization_id: StableId,
    realizations: Vec<ContextRealizedItemV2>,
    serializer: &impl ContextSerializerV2,
    tokenizer: &impl ExactTokenizerV2,
) -> Result<SerializedContextV2, ContextCompilerV2Error> {
    compiled.validate()?;
    profile.validate()?;
    if profile.digest() != compiled.receipt.model_profile_digest {
        return Err(ContextCompilerV2Error::ModelProfileMismatch);
    }
    if serializer.serializer_digest() != profile.serializer_digest
        || serializer.template_digest() != profile.template_digest
        || serializer.tool_schema_digest() != profile.tool_schema_digest
    {
        return Err(ContextCompilerV2Error::SerializerProfileMismatch);
    }
    if tokenizer.tokenizer_digest() != profile.tokenizer_digest {
        return Err(ContextCompilerV2Error::TokenizerProfileMismatch);
    }

    let ordered = validate_realizations(compiled, realizations)?;
    let realization_manifest_digest = compute_realization_manifest_digest(&ordered);
    let payload = serializer.serialize(&ordered)?;
    if payload.is_empty() {
        return Err(ContextCompilerV2Error::EmptySerializedPayload);
    }
    if payload.len() > MAX_SERIALIZED_PAYLOAD_BYTES_V2 {
        return Err(ContextCompilerV2Error::SerializedPayloadTooLarge);
    }
    let serialized_token_count = tokenizer.count_tokens(&payload)?;
    if serialized_token_count == 0 || serialized_token_count > MAX_CONTEXT_TOKENS_V2 {
        return Err(ContextCompilerV2Error::InvalidSerializedTokenCount);
    }
    if serialized_token_count > compiled.receipt.token_upper_bound
        || serialized_token_count > profile.maximum_context_tokens
    {
        return Err(ContextCompilerV2Error::SerializedTokenBudgetExceeded {
            serialized_tokens: serialized_token_count,
            token_budget: compiled.receipt.token_upper_bound,
        });
    }

    let mut receipt = ContextSerializationReceiptV2 {
        serialization_id,
        compilation_receipt_digest: compiled.receipt.receipt_digest,
        context_digest: compiled.receipt.context_digest,
        model_profile_digest: compiled.receipt.model_profile_digest,
        selected_item_ids: compiled.receipt.selected_item_ids.clone(),
        realization_manifest_digest,
        template_digest: profile.template_digest,
        tool_schema_digest: profile.tool_schema_digest,
        tokenizer_digest: profile.tokenizer_digest,
        payload_digest: Digest32::of_bytes(&payload),
        serialized_payload_bytes: u64::try_from(payload.len()).unwrap_or(u64::MAX),
        serialized_token_count,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    let serialized = SerializedContextV2 { receipt, payload };
    serialized.validate_for(compiled, profile)?;
    Ok(serialized)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextAttachmentV2 {
    attachment_id: StableId,
    compilation_receipt_digest: Digest32,
    serialization_receipt_digest: Digest32,
    generation_vector_digest: Digest32,
    admission_verifier_digest: Digest32,
    admission_snapshot_digest: Digest32,
    admission_snapshot_verification_digest: Digest32,
    admission_snapshot_observed_unix_ms: u64,
    revocation_epoch: u64,
    model_profile_digest: Digest32,
    payload_digest: Digest32,
    selected_item_ids: Vec<StableId>,
    attachment_digest: Digest32,
    authority: AuthorityPosture,
}

impl ContextAttachmentV2 {
    #[must_use]
    pub const fn attachment_digest(&self) -> Digest32 {
        self.attachment_digest
    }

    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub const fn admission_snapshot_digest(&self) -> Digest32 {
        self.admission_snapshot_digest
    }

    #[must_use]
    pub const fn admission_snapshot_observed_unix_ms(&self) -> u64 {
        self.admission_snapshot_observed_unix_ms
    }

    #[must_use]
    pub const fn revocation_epoch(&self) -> u64 {
        self.revocation_epoch
    }

    #[must_use]
    pub fn selected_item_ids(&self) -> &[StableId] {
        &self.selected_item_ids
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate_for(
        &self,
        compiled: &CompiledContextV2,
        serialization: &SerializedContextV2,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ContextCompilerV2Error> {
        compiled.validate()?;
        serialization.validate_for(compiled, profile)?;
        for (name, digest) in [
            ("admission_verifier", self.admission_verifier_digest),
            ("admission_snapshot", self.admission_snapshot_digest),
            (
                "admission_snapshot_verification",
                self.admission_snapshot_verification_digest,
            ),
            ("attachment", self.attachment_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.admission_snapshot_observed_unix_ms == 0 {
            return Err(ContextCompilerV2Error::InvalidAdmissionSnapshotTime);
        }
        if self.compilation_receipt_digest != compiled.receipt.receipt_digest
            || self.serialization_receipt_digest != serialization.receipt.receipt_digest
            || self.generation_vector_digest != compiled.receipt.generation_vector_digest
            || self.admission_verifier_digest != compiled.receipt.admission_verifier_digest
            || self.model_profile_digest != compiled.receipt.model_profile_digest
            || self.payload_digest != serialization.receipt.payload_digest
            || self.selected_item_ids != compiled.receipt.selected_item_ids
        {
            return Err(ContextCompilerV2Error::AttachmentMismatch);
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
    fn compute_attachment_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ATTACHMENT_DOMAIN);
        push_id(&mut bytes, &self.attachment_id);
        push_digest(&mut bytes, self.compilation_receipt_digest);
        push_digest(&mut bytes, self.serialization_receipt_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_digest(&mut bytes, self.admission_verifier_digest);
        push_digest(&mut bytes, self.admission_snapshot_digest);
        push_digest(&mut bytes, self.admission_snapshot_verification_digest);
        push_u64(&mut bytes, self.admission_snapshot_observed_unix_ms);
        push_u64(&mut bytes, self.revocation_epoch);
        push_digest(&mut bytes, self.model_profile_digest);
        push_digest(&mut bytes, self.payload_digest);
        push_ids(&mut bytes, &self.selected_item_ids);
        Digest32::of_bytes(&bytes)
    }
}

pub fn build_attachment(
    compiled: &CompiledContextV2,
    serialization: &SerializedContextV2,
    profile: &ContextModelProfileV2,
    current_snapshot: &VerifiedAdmissionSnapshotV2,
    attachment_id: StableId,
) -> Result<ContextAttachmentV2, ContextCompilerV2Error> {
    serialization.validate_for(compiled, profile)?;
    revalidate_selected_admissions(compiled, current_snapshot)?;
    let mut attachment = ContextAttachmentV2 {
        attachment_id,
        compilation_receipt_digest: compiled.receipt.receipt_digest,
        serialization_receipt_digest: serialization.receipt.receipt_digest,
        generation_vector_digest: compiled.receipt.generation_vector_digest,
        admission_verifier_digest: compiled.receipt.admission_verifier_digest,
        admission_snapshot_digest: current_snapshot.snapshot_digest(),
        admission_snapshot_verification_digest: current_snapshot.verification_digest(),
        admission_snapshot_observed_unix_ms: current_snapshot.observed_unix_ms(),
        revocation_epoch: current_snapshot.revocation_epoch(),
        model_profile_digest: compiled.receipt.model_profile_digest,
        payload_digest: serialization.receipt.payload_digest,
        selected_item_ids: compiled.receipt.selected_item_ids.clone(),
        attachment_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    attachment.attachment_digest = attachment.compute_attachment_digest();
    attachment.validate_for(compiled, serialization, profile)?;
    Ok(attachment)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextDeliveryPreparationV2 {
    preparation_id: StableId,
    attachment_digest: Digest32,
    serialization_receipt_digest: Digest32,
    payload_digest: Digest32,
    model_profile_digest: Digest32,
    provider_id_digest: Digest32,
    provider_model_digest: Digest32,
    admission_verifier_digest: Digest32,
    admission_snapshot_digest: Digest32,
    admission_snapshot_verification_digest: Digest32,
    admission_snapshot_observed_unix_ms: u64,
    revocation_epoch: u64,
    preparation_digest: Digest32,
    authority: AuthorityPosture,
}

impl ContextDeliveryPreparationV2 {
    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub const fn preparation_digest(&self) -> Digest32 {
        self.preparation_digest
    }

    #[must_use]
    pub const fn admission_snapshot_digest(&self) -> Digest32 {
        self.admission_snapshot_digest
    }

    #[must_use]
    pub const fn admission_snapshot_observed_unix_ms(&self) -> u64 {
        self.admission_snapshot_observed_unix_ms
    }

    #[must_use]
    pub const fn revocation_epoch(&self) -> u64 {
        self.revocation_epoch
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate_for(
        &self,
        attachment: &ContextAttachmentV2,
        serialization: &SerializedContextV2,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("delivery_preparation", self.preparation_digest),
            ("attachment", self.attachment_digest),
            ("serialization_receipt", self.serialization_receipt_digest),
            ("payload", self.payload_digest),
            ("model_profile", self.model_profile_digest),
            ("provider_id", self.provider_id_digest),
            ("provider_model", self.provider_model_digest),
            ("admission_verifier", self.admission_verifier_digest),
            ("admission_snapshot", self.admission_snapshot_digest),
            (
                "admission_snapshot_verification",
                self.admission_snapshot_verification_digest,
            ),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.attachment_digest != attachment.attachment_digest
            || self.serialization_receipt_digest != serialization.receipt.receipt_digest
            || self.payload_digest != attachment.payload_digest
            || self.payload_digest != serialization.receipt.payload_digest
            || self.model_profile_digest != profile.digest()
            || self.model_profile_digest != attachment.model_profile_digest
            || self.provider_id_digest != profile.provider_id_digest
            || self.provider_model_digest != profile.provider_model_digest
            || self.admission_verifier_digest != attachment.admission_verifier_digest
            || self.admission_snapshot_observed_unix_ms
                < attachment.admission_snapshot_observed_unix_ms
            || self.revocation_epoch < attachment.revocation_epoch
        {
            return Err(ContextCompilerV2Error::DeliveryMismatch);
        }
        if self.authority.grants_any() {
            return Err(ContextCompilerV2Error::AuthorityGranted);
        }
        if self.preparation_digest != self.compute_preparation_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch(
                "delivery_preparation",
            ));
        }
        Ok(())
    }

    #[must_use]
    fn compute_preparation_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(DELIVERY_PREPARATION_DOMAIN);
        push_id(&mut bytes, &self.preparation_id);
        for digest in [
            self.attachment_digest,
            self.serialization_receipt_digest,
            self.payload_digest,
            self.model_profile_digest,
            self.provider_id_digest,
            self.provider_model_digest,
            self.admission_verifier_digest,
            self.admission_snapshot_digest,
            self.admission_snapshot_verification_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.admission_snapshot_observed_unix_ms);
        push_u64(&mut bytes, self.revocation_epoch);
        Digest32::of_bytes(&bytes)
    }
}

pub fn prepare_delivery_v2(
    compiled: &CompiledContextV2,
    serialization: &SerializedContextV2,
    attachment: &ContextAttachmentV2,
    profile: &ContextModelProfileV2,
    current_snapshot: &VerifiedAdmissionSnapshotV2,
    preparation_id: StableId,
) -> Result<ContextDeliveryPreparationV2, ContextCompilerV2Error> {
    attachment.validate_for(compiled, serialization, profile)?;
    if current_snapshot.revocation_epoch() < attachment.revocation_epoch
        || current_snapshot.observed_unix_ms() < attachment.admission_snapshot_observed_unix_ms
    {
        return Err(ContextCompilerV2Error::StaleAdmissionSnapshot);
    }
    revalidate_selected_admissions(compiled, current_snapshot)?;
    let actual_payload_digest = Digest32::of_bytes(&serialization.payload);
    if actual_payload_digest != attachment.payload_digest {
        return Err(ContextCompilerV2Error::DeliveryMismatch);
    }

    let mut preparation = ContextDeliveryPreparationV2 {
        preparation_id,
        attachment_digest: attachment.attachment_digest,
        serialization_receipt_digest: serialization.receipt.receipt_digest,
        payload_digest: actual_payload_digest,
        model_profile_digest: profile.digest(),
        provider_id_digest: profile.provider_id_digest,
        provider_model_digest: profile.provider_model_digest,
        admission_verifier_digest: current_snapshot.verifier_digest(),
        admission_snapshot_digest: current_snapshot.snapshot_digest(),
        admission_snapshot_verification_digest: current_snapshot.verification_digest(),
        admission_snapshot_observed_unix_ms: current_snapshot.observed_unix_ms(),
        revocation_epoch: current_snapshot.revocation_epoch(),
        preparation_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    preparation.preparation_digest = preparation.compute_preparation_digest();
    preparation.validate_for(attachment, serialization, profile)?;
    Ok(preparation)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ContextDeliveryDispositionV2 {
    Delivered,
    Rejected,
    NotDispatched,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextDeliveryReceiptV2 {
    delivery_id: StableId,
    preparation_digest: Digest32,
    attachment_digest: Digest32,
    serialization_receipt_digest: Digest32,
    payload_digest: Digest32,
    model_profile_digest: Digest32,
    provider_id_digest: Digest32,
    provider_model_digest: Digest32,
    provider_request_binding_digest: Digest32,
    provider_attempt_digest: Digest32,
    provider_receipt_digest: Digest32,
    provider_terminal_digest: Digest32,
    provider_evidence_verifier_digest: Digest32,
    provider_evidence_digest: Digest32,
    provider_recorded_at_unix_ms: u64,
    admission_snapshot_digest: Digest32,
    admission_snapshot_verification_digest: Digest32,
    admission_snapshot_observed_unix_ms: u64,
    revocation_epoch: u64,
    terminal_observed: bool,
    disposition: ContextDeliveryDispositionV2,
    observed_unix_ms: u64,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

pub type ContextDeliveryObservationV2 = ContextDeliveryReceiptV2;

impl ContextDeliveryReceiptV2 {
    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub const fn preparation_digest(&self) -> Digest32 {
        self.preparation_digest
    }

    #[must_use]
    pub const fn admission_snapshot_digest(&self) -> Digest32 {
        self.admission_snapshot_digest
    }

    #[must_use]
    pub const fn admission_snapshot_observed_unix_ms(&self) -> u64 {
        self.admission_snapshot_observed_unix_ms
    }

    #[must_use]
    pub const fn revocation_epoch(&self) -> u64 {
        self.revocation_epoch
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

    pub fn validate_for(
        &self,
        preparation: &ContextDeliveryPreparationV2,
        attachment: &ContextAttachmentV2,
        serialization: &SerializedContextV2,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("delivery_preparation", self.preparation_digest),
            ("attachment", self.attachment_digest),
            ("serialization_receipt", self.serialization_receipt_digest),
            ("payload", self.payload_digest),
            ("model_profile", self.model_profile_digest),
            ("provider_id", self.provider_id_digest),
            ("provider_model", self.provider_model_digest),
            (
                "provider_request_binding",
                self.provider_request_binding_digest,
            ),
            ("provider_attempt", self.provider_attempt_digest),
            ("provider_receipt", self.provider_receipt_digest),
            ("provider_terminal", self.provider_terminal_digest),
            (
                "provider_evidence_verifier",
                self.provider_evidence_verifier_digest,
            ),
            ("provider_evidence", self.provider_evidence_digest),
            ("admission_snapshot", self.admission_snapshot_digest),
            (
                "admission_snapshot_verification",
                self.admission_snapshot_verification_digest,
            ),
            ("delivery_receipt", self.receipt_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.preparation_digest != preparation.preparation_digest
            || self.attachment_digest != attachment.attachment_digest
            || self.serialization_receipt_digest != serialization.receipt.receipt_digest
            || self.payload_digest != preparation.payload_digest
            || self.payload_digest != attachment.payload_digest
            || self.payload_digest != serialization.receipt.payload_digest
            || self.model_profile_digest != preparation.model_profile_digest
            || self.model_profile_digest != profile.digest()
            || self.provider_id_digest != preparation.provider_id_digest
            || self.provider_model_digest != preparation.provider_model_digest
            || self.admission_snapshot_digest != preparation.admission_snapshot_digest
            || self.admission_snapshot_verification_digest
                != preparation.admission_snapshot_verification_digest
            || self.admission_snapshot_observed_unix_ms
                != preparation.admission_snapshot_observed_unix_ms
            || self.revocation_epoch != preparation.revocation_epoch
        {
            return Err(ContextCompilerV2Error::DeliveryMismatch);
        }
        match self.disposition {
            ContextDeliveryDispositionV2::Delivered
            | ContextDeliveryDispositionV2::Rejected
            | ContextDeliveryDispositionV2::NotDispatched => {
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
        if self.provider_recorded_at_unix_ms < preparation.admission_snapshot_observed_unix_ms
            || self.observed_unix_ms < self.provider_recorded_at_unix_ms
        {
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
    fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(DELIVERY_DOMAIN);
        push_id(&mut bytes, &self.delivery_id);
        for digest in [
            self.preparation_digest,
            self.attachment_digest,
            self.serialization_receipt_digest,
            self.payload_digest,
            self.model_profile_digest,
            self.provider_id_digest,
            self.provider_model_digest,
            self.provider_request_binding_digest,
            self.provider_attempt_digest,
            self.provider_receipt_digest,
            self.provider_terminal_digest,
            self.provider_evidence_verifier_digest,
            self.provider_evidence_digest,
            self.admission_snapshot_digest,
            self.admission_snapshot_verification_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.provider_recorded_at_unix_ms);
        push_u64(&mut bytes, self.admission_snapshot_observed_unix_ms);
        push_u64(&mut bytes, self.revocation_epoch);
        bytes.push(u8::from(self.terminal_observed));
        bytes.push(delivery_disposition_code(self.disposition));
        push_u64(&mut bytes, self.observed_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[expect(
    clippy::too_many_arguments,
    reason = "the public delivery receipt binds eight independently authenticated inputs"
)]
pub fn observe_delivery(
    preparation: &ContextDeliveryPreparationV2,
    attachment: &ContextAttachmentV2,
    serialization: &SerializedContextV2,
    profile: &ContextModelProfileV2,
    delivery_id: StableId,
    provider_receipt: &ProviderInvocationReceipt,
    delivery_verifier: &impl ContextProviderDeliveryVerifierV2,
    observed_unix_ms: u64,
) -> Result<ContextDeliveryReceiptV2, ContextCompilerV2Error> {
    preparation.validate_for(attachment, serialization, profile)?;
    provider_receipt
        .validate()
        .map_err(ContextCompilerV2Error::ProviderReceiptInvalid)?;

    let Some(provider_input) = provider_receipt
        .intent
        .binding
        .ephemeral_input_sha256
        .as_ref()
    else {
        return Err(ContextCompilerV2Error::MissingProviderInputBinding);
    };
    let Some(_provider_input_witness) = provider_receipt
        .intent
        .binding
        .ephemeral_input_witness_sha256
        .as_ref()
    else {
        return Err(ContextCompilerV2Error::MissingProviderInputWitness);
    };
    let expected_provider_input = Sha256Digest::for_bytes(serialization.payload());
    if provider_input != &expected_provider_input {
        return Err(ContextCompilerV2Error::DeliveryMismatch);
    }

    let provider_id_digest =
        Digest32::of_bytes(provider_receipt.intent.binding.provider_id.as_bytes());
    let provider_model_digest =
        Digest32::of_bytes(provider_receipt.intent.binding.model.as_bytes());
    if provider_id_digest != preparation.provider_id_digest
        || provider_model_digest != preparation.provider_model_digest
    {
        return Err(ContextCompilerV2Error::ProviderModelProfileMismatch);
    }

    let provider_evidence_verifier_digest = delivery_verifier.verifier_digest();
    ensure_digest(
        "provider_evidence_verifier",
        provider_evidence_verifier_digest,
    )?;
    let delivery_evidence = delivery_verifier
        .verify_delivery(provider_receipt, preparation)
        .map_err(ContextCompilerV2Error::ProviderEvidenceInvalid)?;
    ensure_digest("provider_evidence", delivery_evidence.evidence_digest)?;

    if delivery_evidence.recorded_at_unix_ms < preparation.admission_snapshot_observed_unix_ms
        || observed_unix_ms < delivery_evidence.recorded_at_unix_ms
    {
        return Err(ContextCompilerV2Error::InvalidObservationTime);
    }

    let provider_request_binding_digest =
        Digest32::of_bytes(provider_receipt.request_binding_id.as_str().as_bytes());
    let provider_attempt_digest =
        Digest32::of_bytes(provider_receipt.attempt_id.as_str().as_bytes());
    let provider_receipt_digest = Digest32::of_bytes(
        &provider_receipt
            .canonical_wire_bytes()
            .map_err(ContextCompilerV2Error::ProviderReceiptInvalid)?,
    );
    let provider_terminal_digest = Digest32::of_bytes(
        &provider_receipt
            .terminal
            .canonical_wire_bytes()
            .map_err(ContextCompilerV2Error::ProviderReceiptInvalid)?,
    );
    let (terminal_observed, disposition) = match &provider_receipt.terminal {
        ProviderTerminal::Completed { .. } | ProviderTerminal::CompletedUnary { .. } => {
            (true, ContextDeliveryDispositionV2::Delivered)
        }
        ProviderTerminal::Rejected { .. } => (true, ContextDeliveryDispositionV2::Rejected),
        ProviderTerminal::NotDispatched { .. } => {
            (true, ContextDeliveryDispositionV2::NotDispatched)
        }
        ProviderTerminal::Indeterminate { .. } => {
            (false, ContextDeliveryDispositionV2::Indeterminate)
        }
    };

    let mut receipt = ContextDeliveryReceiptV2 {
        delivery_id,
        preparation_digest: preparation.preparation_digest,
        attachment_digest: attachment.attachment_digest,
        serialization_receipt_digest: serialization.receipt.receipt_digest,
        payload_digest: preparation.payload_digest,
        model_profile_digest: preparation.model_profile_digest,
        provider_id_digest,
        provider_model_digest,
        provider_request_binding_digest,
        provider_attempt_digest,
        provider_receipt_digest,
        provider_terminal_digest,
        provider_evidence_verifier_digest,
        provider_evidence_digest: delivery_evidence.evidence_digest,
        provider_recorded_at_unix_ms: delivery_evidence.recorded_at_unix_ms,
        admission_snapshot_digest: preparation.admission_snapshot_digest,
        admission_snapshot_verification_digest: preparation.admission_snapshot_verification_digest,
        admission_snapshot_observed_unix_ms: preparation.admission_snapshot_observed_unix_ms,
        revocation_epoch: preparation.revocation_epoch,
        terminal_observed,
        disposition,
        observed_unix_ms,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    receipt.validate_for(preparation, attachment, serialization, profile)?;
    Ok(receipt)
}

fn validate_realizations(
    compiled: &CompiledContextV2,
    realizations: Vec<ContextRealizedItemV2>,
) -> Result<Vec<ContextRealizedItemV2>, ContextCompilerV2Error> {
    if realizations.len() != compiled.selected_candidates.len() {
        return Err(ContextCompilerV2Error::RealizationSetMismatch);
    }
    let mut by_id = BTreeMap::<StableId, ContextRealizedItemV2>::new();
    let mut realization_bytes = 0_usize;
    for realization in realizations {
        if realization.content.len() > MAX_CONTEXT_ITEM_BYTES_V2 {
            return Err(ContextCompilerV2Error::RealizedContentTooLarge(
                realization.item_id.to_string(),
            ));
        }
        realization_bytes = realization_bytes
            .checked_add(realization.content.len())
            .ok_or(ContextCompilerV2Error::Arithmetic)?;
        if realization_bytes > MAX_REALIZATION_BYTES_V2 {
            return Err(ContextCompilerV2Error::RealizationBytesExceeded);
        }
        let item_id = realization.item_id.clone();
        if by_id.insert(item_id.clone(), realization).is_some() {
            return Err(ContextCompilerV2Error::DuplicateRealization(
                item_id.to_string(),
            ));
        }
    }
    let mut ordered = Vec::with_capacity(compiled.selected_candidates.len());
    for candidate in &compiled.selected_candidates {
        let Some(realization) = by_id.remove(&candidate.item_id) else {
            return Err(ContextCompilerV2Error::RealizationSetMismatch);
        };
        if realization.role != candidate.role {
            return Err(ContextCompilerV2Error::RealizedRoleMismatch(
                candidate.item_id.to_string(),
            ));
        }
        if Digest32::of_bytes(&realization.content) != candidate.content_digest {
            return Err(ContextCompilerV2Error::RealizedContentMismatch(
                candidate.item_id.to_string(),
            ));
        }
        ordered.push(realization);
    }
    if !by_id.is_empty() {
        return Err(ContextCompilerV2Error::RealizationSetMismatch);
    }
    Ok(ordered)
}

fn revalidate_selected_admissions(
    compiled: &CompiledContextV2,
    current_snapshot: &VerifiedAdmissionSnapshotV2,
) -> Result<(), ContextCompilerV2Error> {
    if current_snapshot.verifier_digest() != compiled.receipt.admission_verifier_digest {
        return Err(ContextCompilerV2Error::AdmissionVerifierMismatch(
            "current_snapshot".to_string(),
        ));
    }
    for candidate in &compiled.selected_candidates {
        candidate.admission.revalidate(current_snapshot)?;
    }
    Ok(())
}

fn compute_candidate_set_digest<'a>(
    candidates: impl IntoIterator<Item = &'a ContextCandidateV2>,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(CANDIDATE_SET_DOMAIN);
    for candidate in candidates {
        push_id(&mut bytes, &candidate.item_id);
        bytes.push(role_code(candidate.role));
        push_digest(&mut bytes, candidate.content_digest);
        push_digest(&mut bytes, candidate.source_digest);
        push_digest(&mut bytes, candidate.generation_vector_digest);
        push_digest(&mut bytes, candidate.tokenization.receipt_digest());
        push_i64(&mut bytes, candidate.expected_value.raw());
        push_digest(&mut bytes, candidate.admission.verification_digest());
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

fn compute_context_digest(candidates: &[ContextCandidateV2]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(CONTEXT_DOMAIN);
    push_len(&mut bytes, candidates.len());
    for candidate in candidates {
        bytes.push(role_code(candidate.role));
        push_id(&mut bytes, &candidate.item_id);
        push_digest(&mut bytes, candidate.content_digest);
        push_digest(&mut bytes, candidate.source_digest);
        push_digest(&mut bytes, candidate.generation_vector_digest);
        push_digest(&mut bytes, candidate.tokenization.receipt_digest());
        push_digest(&mut bytes, candidate.admission.verification_digest());
    }
    Digest32::of_bytes(&bytes)
}

fn compute_realization_manifest_digest(items: &[ContextRealizedItemV2]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(REALIZATION_MANIFEST_DOMAIN);
    push_len(&mut bytes, items.len());
    for item in items {
        push_id(&mut bytes, &item.item_id);
        bytes.push(role_code(item.role));
        push_digest(&mut bytes, Digest32::of_bytes(&item.content));
        push_len(&mut bytes, item.content.len());
    }
    Digest32::of_bytes(&bytes)
}

fn context_placement_order(left: &ContextCandidateV2, right: &ContextCandidateV2) -> Ordering {
    left.role
        .cmp(&right.role)
        .then_with(|| left.item_id.cmp(&right.item_id))
}

fn value_per_token_order(left: &ContextCandidateV2, right: &ContextCandidateV2) -> Ordering {
    let left_cross =
        i128::from(left.expected_value.raw()) * i128::from(right.tokenization.token_count());
    let right_cross =
        i128::from(right.expected_value.raw()) * i128::from(left.tokenization.token_count());
    right_cross
        .cmp(&left_cross)
        .then_with(|| right.expected_value.cmp(&left.expected_value))
        .then_with(|| left.item_id.cmp(&right.item_id))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ContextCompilerV2Error {
    EmptyDigest(&'static str),
    DigestMismatch(&'static str),
    CandidateLimitExceeded,
    GroupLimitExceeded,
    InvalidModelContextLimit,
    InvalidTokenBudget,
    InvalidTokenCount(String),
    CandidateContentTooLarge(String),
    InvalidSerializedTokenCount,
    DuplicateCandidate(String),
    DuplicateMandatoryGroup(String),
    EmptyMandatoryGroup(String),
    DuplicateMandatoryItem(String),
    UnknownMandatoryItem(String),
    GenerationVectorMismatch(String),
    TokenizationItemMismatch(String),
    TokenizerMismatch(String),
    TokenizerProfileMismatch,
    ValueOutOfRange(String),
    SecretRejected(String),
    InvalidAdmissionTime(String),
    InvalidAdmissionSnapshotTime,
    DuplicateRevocation(String),
    NonCanonicalRevocationList,
    RevocationLimitExceeded,
    IncompleteRevocationSnapshot,
    UnexpectedSnapshotPredecessor,
    SnapshotPredecessorMismatch,
    SnapshotDomainMismatch,
    RevocationFrontierMismatch,
    RevocationResurrection(String),
    AdmissionRecordUnverified(String),
    AdmissionSnapshotUnverified,
    AdmissionNotYetValid(String),
    AdmissionExpired(String),
    AdmissionRevoked(String),
    AdmissionBindingMismatch(String),
    AdmissionVerifierMismatch(String),
    AdmissionSnapshotDomainMismatch(String),
    StaleAdmissionSnapshot,
    MandatoryReferenceLimitExceeded,
    InsufficientMandatoryBudget {
        required_tokens: u64,
        token_budget: u64,
    },
    TokenBudgetExceeded,
    SelectedSetMismatch,
    SelectedTokenCountMismatch,
    ModelProfileMismatch,
    SerializerProfileMismatch,
    RealizationSetMismatch,
    DuplicateRealization(String),
    RealizedRoleMismatch(String),
    RealizedContentMismatch(String),
    RealizedContentTooLarge(String),
    RealizationBytesExceeded,
    EmptySerializedPayload,
    SerializedPayloadTooLarge,
    SerializedTokenBudgetExceeded {
        serialized_tokens: u64,
        token_budget: u64,
    },
    SerializationMismatch,
    AttachmentMismatch,
    DeliveryMismatch,
    MissingProviderInputBinding,
    MissingProviderInputWitness,
    ProviderModelProfileMismatch,
    ProviderReceiptInvalid(String),
    ProviderEvidenceInvalid(String),
    MissingTerminalObservation,
    InvalidDeliveryDisposition,
    InvalidObservationTime,
    AuthorityGranted,
    Arithmetic,
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

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_i64(bytes: &mut Vec<u8>, value: i64) {
    bytes.extend_from_slice(&value.to_be_bytes());
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
        ContextDeliveryDispositionV2::NotDispatched => 2,
        ContextDeliveryDispositionV2::Indeterminate => 3,
    }
}

#[cfg(test)]
#[path = "v2_tests.rs"]
mod tests;
