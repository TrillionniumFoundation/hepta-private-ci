//! Provider terminal evidence bound to the exact final request bytes.
//!
//! The legacy V2 observer predates provider-specific request framing and binds
//! the provider input to the canonical context payload. The strict observer in
//! this module instead authenticates the exact `VerifiedProviderRequestV2`
//! bytes, the provider wire-semantic digest and the qualified tokenizer
//! attestation before it mints a terminal receipt.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::provider_bound::CanonicalSerializedContextProofV2;
use crate::provider_bound::FinalProviderRequestTokenizationV2;
use crate::provider_bound::ProviderBoundContextErrorV2;
use crate::provider_bound::ProviderRequestFramingPolicyV2;
use crate::provider_bound::VerifiedProviderRequestV2;
use crate::v2::CompiledContextV2;
use crate::v2::ContextAttachmentV2;
use crate::v2::ContextCompilerV2Error;
use crate::v2::ContextDeliveryDispositionV2;
use crate::v2::ContextDeliveryPreparationV2;
use crate::v2::ContextModelProfileV2;
use crate::v2::ContextProviderDeliveryVerifierV2;
use crate::v2::ContextRealizedItemV2;

const PROVIDER_BOUND_DELIVERY_DOMAIN: &[u8] = b"hepta.context-provider-bound-delivery.v2\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProviderBoundDeliveryErrorV2 {
    Context(ContextCompilerV2Error),
    ProviderBound(ProviderBoundContextErrorV2),
    ProviderReceiptInvalid(String),
    MissingProviderInputBinding,
    MissingProviderInputWitness,
    ProviderInputMismatch,
    ProviderWireSemanticMismatch,
    ProviderIdentityMismatch,
    ProviderEvidenceRejected(String),
    InvalidProviderEvidence,
    InvalidObservationTime,
    InvalidDisposition,
    InvalidSha256Digest,
    EmptyDigest(&'static str),
    AuthorityGranted,
    ReceiptIntegrityMismatch,
}

impl From<ContextCompilerV2Error> for ProviderBoundDeliveryErrorV2 {
    fn from(error: ContextCompilerV2Error) -> Self {
        Self::Context(error)
    }
}

impl From<ProviderBoundContextErrorV2> for ProviderBoundDeliveryErrorV2 {
    fn from(error: ProviderBoundContextErrorV2) -> Self {
        Self::ProviderBound(error)
    }
}

impl fmt::Display for ProviderBoundDeliveryErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProviderBoundDeliveryErrorV2 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderBoundDeliveryReceiptV2 {
    delivery_id: StableId,
    preparation_digest: Digest32,
    attachment_digest: Digest32,
    canonical_serialization_proof_digest: Digest32,
    canonical_payload_digest: Digest32,
    provider_request_digest: Digest32,
    provider_request_coverage_digest: Digest32,
    wire_semantic_digest: Digest32,
    tokenizer_identity_digest: Digest32,
    tokenizer_attestation_digest: Digest32,
    provider_request_binding_digest: Digest32,
    provider_attempt_digest: Digest32,
    provider_receipt_digest: Digest32,
    provider_terminal_digest: Digest32,
    provider_evidence_verifier_digest: Digest32,
    provider_evidence_digest: Digest32,
    provider_recorded_at_unix_ms: u64,
    terminal_observed: bool,
    disposition: ContextDeliveryDispositionV2,
    observed_unix_ms: u64,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl ProviderBoundDeliveryReceiptV2 {
    #[must_use]
    pub const fn delivery_id(&self) -> &StableId {
        &self.delivery_id
    }

    #[must_use]
    pub const fn preparation_digest(&self) -> Digest32 {
        self.preparation_digest
    }

    #[must_use]
    pub const fn attachment_digest(&self) -> Digest32 {
        self.attachment_digest
    }

    #[must_use]
    pub const fn canonical_serialization_proof_digest(&self) -> Digest32 {
        self.canonical_serialization_proof_digest
    }

    #[must_use]
    pub const fn canonical_payload_digest(&self) -> Digest32 {
        self.canonical_payload_digest
    }

    #[must_use]
    pub const fn provider_request_digest(&self) -> Digest32 {
        self.provider_request_digest
    }

    #[must_use]
    pub const fn provider_request_coverage_digest(&self) -> Digest32 {
        self.provider_request_coverage_digest
    }

    #[must_use]
    pub const fn wire_semantic_digest(&self) -> Digest32 {
        self.wire_semantic_digest
    }

    #[must_use]
    pub const fn tokenizer_identity_digest(&self) -> Digest32 {
        self.tokenizer_identity_digest
    }

    #[must_use]
    pub const fn tokenizer_attestation_digest(&self) -> Digest32 {
        self.tokenizer_attestation_digest
    }

    #[must_use]
    pub const fn disposition(&self) -> ContextDeliveryDispositionV2 {
        self.disposition
    }

    #[must_use]
    pub const fn terminal_observed(&self) -> bool {
        self.terminal_observed
    }

    #[must_use]
    pub const fn observed_unix_ms(&self) -> u64 {
        self.observed_unix_ms
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    #[allow(clippy::too_many_arguments)]
    pub fn validate_for(
        &self,
        compiled: &CompiledContextV2,
        realizations: &[ContextRealizedItemV2],
        serialization: &CanonicalSerializedContextProofV2,
        attachment: &ContextAttachmentV2,
        preparation: &ContextDeliveryPreparationV2,
        profile: &ContextModelProfileV2,
        provider_request: &VerifiedProviderRequestV2,
        tokenization: &FinalProviderRequestTokenizationV2,
        framing_policy: &impl ProviderRequestFramingPolicyV2,
    ) -> Result<(), ProviderBoundDeliveryErrorV2> {
        serialization.validate_for(compiled, profile, realizations)?;
        attachment.validate_for(compiled, serialization.serialized_context(), profile)?;
        preparation.validate_for(
            attachment,
            serialization.serialized_context(),
            profile,
        )?;
        provider_request.validate(serialization.canonical_payload(), framing_policy)?;
        tokenization.validate_for(profile, provider_request)?;
        for (name, digest) in [
            ("delivery_preparation", self.preparation_digest),
            ("context_attachment", self.attachment_digest),
            (
                "canonical_serialization_proof",
                self.canonical_serialization_proof_digest,
            ),
            ("canonical_payload", self.canonical_payload_digest),
            ("provider_request", self.provider_request_digest),
            (
                "provider_request_coverage",
                self.provider_request_coverage_digest,
            ),
            ("wire_semantic", self.wire_semantic_digest),
            ("tokenizer_identity", self.tokenizer_identity_digest),
            (
                "tokenizer_attestation",
                self.tokenizer_attestation_digest,
            ),
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
            ("provider_bound_delivery", self.receipt_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.preparation_digest != preparation.preparation_digest()
            || self.attachment_digest != attachment.attachment_digest()
            || self.canonical_serialization_proof_digest != serialization.proof_digest()
            || self.canonical_payload_digest
                != serialization.canonical_payload().coverage().payload_digest()
            || self.provider_request_digest != provider_request.request_digest()
            || self.provider_request_coverage_digest != provider_request.coverage_digest()
            || self.wire_semantic_digest != tokenization.wire_semantic_digest()
            || self.tokenizer_identity_digest != tokenization.tokenizer_identity().digest()
            || self.tokenizer_attestation_digest != tokenization.attestation_digest()
        {
            return Err(ProviderBoundDeliveryErrorV2::ReceiptIntegrityMismatch);
        }
        match self.disposition {
            ContextDeliveryDispositionV2::Delivered
            | ContextDeliveryDispositionV2::Rejected
            | ContextDeliveryDispositionV2::NotDispatched => {
                if !self.terminal_observed {
                    return Err(ProviderBoundDeliveryErrorV2::InvalidDisposition);
                }
            }
            ContextDeliveryDispositionV2::Indeterminate => {
                if self.terminal_observed {
                    return Err(ProviderBoundDeliveryErrorV2::InvalidDisposition);
                }
            }
        }
        if self.provider_recorded_at_unix_ms < preparation.admission_snapshot_observed_unix_ms()
            || self.observed_unix_ms < self.provider_recorded_at_unix_ms
        {
            return Err(ProviderBoundDeliveryErrorV2::InvalidObservationTime);
        }
        if self.authority.grants_any() {
            return Err(ProviderBoundDeliveryErrorV2::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(ProviderBoundDeliveryErrorV2::ReceiptIntegrityMismatch);
        }
        Ok(())
    }

    fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = PROVIDER_BOUND_DELIVERY_DOMAIN.to_vec();
        push_id(&mut bytes, &self.delivery_id);
        for digest in [
            self.preparation_digest,
            self.attachment_digest,
            self.canonical_serialization_proof_digest,
            self.canonical_payload_digest,
            self.provider_request_digest,
            self.provider_request_coverage_digest,
            self.wire_semantic_digest,
            self.tokenizer_identity_digest,
            self.tokenizer_attestation_digest,
            self.provider_request_binding_digest,
            self.provider_attempt_digest,
            self.provider_receipt_digest,
            self.provider_terminal_digest,
            self.provider_evidence_verifier_digest,
            self.provider_evidence_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.provider_recorded_at_unix_ms.to_be_bytes());
        bytes.push(u8::from(self.terminal_observed));
        bytes.push(disposition_code(self.disposition));
        bytes.extend_from_slice(&self.observed_unix_ms.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[allow(clippy::too_many_arguments)]
pub fn observe_provider_bound_delivery_v2(
    compiled: &CompiledContextV2,
    realizations: &[ContextRealizedItemV2],
    serialization: &CanonicalSerializedContextProofV2,
    attachment: &ContextAttachmentV2,
    preparation: &ContextDeliveryPreparationV2,
    profile: &ContextModelProfileV2,
    provider_request: &VerifiedProviderRequestV2,
    tokenization: &FinalProviderRequestTokenizationV2,
    framing_policy: &impl ProviderRequestFramingPolicyV2,
    delivery_id: StableId,
    provider_receipt: &ProviderInvocationReceipt,
    delivery_verifier: &impl ContextProviderDeliveryVerifierV2,
    observed_unix_ms: u64,
) -> Result<ProviderBoundDeliveryReceiptV2, ProviderBoundDeliveryErrorV2> {
    serialization.validate_for(compiled, profile, realizations)?;
    attachment.validate_for(compiled, serialization.serialized_context(), profile)?;
    preparation.validate_for(
        attachment,
        serialization.serialized_context(),
        profile,
    )?;
    provider_request.validate(serialization.canonical_payload(), framing_policy)?;
    tokenization.validate_for(profile, provider_request)?;
    provider_receipt
        .validate()
        .map_err(ProviderBoundDeliveryErrorV2::ProviderReceiptInvalid)?;

    let binding = &provider_receipt.intent.binding;
    let Some(provider_input) = binding.ephemeral_input_sha256.as_ref() else {
        return Err(ProviderBoundDeliveryErrorV2::MissingProviderInputBinding);
    };
    let Some(_provider_input_witness) = binding.ephemeral_input_witness_sha256.as_ref() else {
        return Err(ProviderBoundDeliveryErrorV2::MissingProviderInputWitness);
    };
    if provider_input != &Sha256Digest::for_bytes(provider_request.bytes()) {
        return Err(ProviderBoundDeliveryErrorV2::ProviderInputMismatch);
    }
    let provider_wire_semantic_digest = digest_from_sha256(&binding.wire_semantic_sha256)?;
    if provider_wire_semantic_digest != tokenization.wire_semantic_digest() {
        return Err(ProviderBoundDeliveryErrorV2::ProviderWireSemanticMismatch);
    }
    let identity = tokenization.tokenizer_identity();
    if Digest32::of_bytes(binding.provider_id.as_bytes()) != identity.provider_id_digest
        || Digest32::of_bytes(binding.model.as_bytes()) != identity.provider_model_digest
    {
        return Err(ProviderBoundDeliveryErrorV2::ProviderIdentityMismatch);
    }

    let verifier_digest = delivery_verifier.verifier_digest();
    ensure_digest("provider_evidence_verifier", verifier_digest)?;
    let decision = delivery_verifier
        .verify_delivery(provider_receipt, preparation)
        .map_err(ProviderBoundDeliveryErrorV2::ProviderEvidenceRejected)?;
    ensure_digest("provider_evidence", decision.evidence_digest)?;
    if decision.recorded_at_unix_ms < preparation.admission_snapshot_observed_unix_ms()
        || observed_unix_ms < decision.recorded_at_unix_ms
    {
        return Err(ProviderBoundDeliveryErrorV2::InvalidObservationTime);
    }

    let (terminal_observed, disposition) = match provider_receipt.terminal {
        ProviderTerminal::Completed { .. } | ProviderTerminal::CompletedUnary { .. } => {
            (true, ContextDeliveryDispositionV2::Delivered)
        }
        ProviderTerminal::Rejected { .. } => {
            (true, ContextDeliveryDispositionV2::Rejected)
        }
        ProviderTerminal::NotDispatched { .. } => {
            (true, ContextDeliveryDispositionV2::NotDispatched)
        }
        ProviderTerminal::Indeterminate { .. } => {
            (false, ContextDeliveryDispositionV2::Indeterminate)
        }
    };

    let binding_bytes = binding
        .canonical_wire_bytes()
        .map_err(ProviderBoundDeliveryErrorV2::ProviderReceiptInvalid)?;
    let intent_bytes = provider_receipt
        .intent
        .canonical_wire_bytes()
        .map_err(ProviderBoundDeliveryErrorV2::ProviderReceiptInvalid)?;
    let receipt_bytes = provider_receipt
        .canonical_wire_bytes()
        .map_err(ProviderBoundDeliveryErrorV2::ProviderReceiptInvalid)?;
    let terminal_bytes = provider_receipt
        .terminal
        .canonical_wire_bytes()
        .map_err(ProviderBoundDeliveryErrorV2::ProviderReceiptInvalid)?;

    let mut receipt = ProviderBoundDeliveryReceiptV2 {
        delivery_id,
        preparation_digest: preparation.preparation_digest(),
        attachment_digest: attachment.attachment_digest(),
        canonical_serialization_proof_digest: serialization.proof_digest(),
        canonical_payload_digest: serialization.canonical_payload().coverage().payload_digest(),
        provider_request_digest: provider_request.request_digest(),
        provider_request_coverage_digest: provider_request.coverage_digest(),
        wire_semantic_digest: tokenization.wire_semantic_digest(),
        tokenizer_identity_digest: identity.digest(),
        tokenizer_attestation_digest: tokenization.attestation_digest(),
        provider_request_binding_digest: Digest32::of_bytes(&binding_bytes),
        provider_attempt_digest: Digest32::of_bytes(&intent_bytes),
        provider_receipt_digest: Digest32::of_bytes(&receipt_bytes),
        provider_terminal_digest: Digest32::of_bytes(&terminal_bytes),
        provider_evidence_verifier_digest: verifier_digest,
        provider_evidence_digest: decision.evidence_digest,
        provider_recorded_at_unix_ms: decision.recorded_at_unix_ms,
        terminal_observed,
        disposition,
        observed_unix_ms,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    receipt.validate_for(
        compiled,
        realizations,
        serialization,
        attachment,
        preparation,
        profile,
        provider_request,
        tokenization,
        framing_policy,
    )?;
    Ok(receipt)
}

fn digest_from_sha256(value: &Sha256Digest) -> Result<Digest32, ProviderBoundDeliveryErrorV2> {
    let raw = value.as_str().as_bytes();
    if raw.len() != 64 {
        return Err(ProviderBoundDeliveryErrorV2::InvalidSha256Digest);
    }
    let mut output = [0_u8; 32];
    for (index, chunk) in raw.chunks_exact(2).enumerate() {
        let high = decode_hex(chunk[0])?;
        let low = decode_hex(chunk[1])?;
        output[index] = (high << 4) | low;
    }
    Ok(Digest32::from_array(output))
}

fn decode_hex(value: u8) -> Result<u8, ProviderBoundDeliveryErrorV2> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(ProviderBoundDeliveryErrorV2::InvalidSha256Digest),
    }
}

fn ensure_digest(
    name: &'static str,
    digest: Digest32,
) -> Result<(), ProviderBoundDeliveryErrorV2> {
    if digest.is_zero() {
        return Err(ProviderBoundDeliveryErrorV2::EmptyDigest(name));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u64::try_from(raw.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

const fn disposition_code(value: ContextDeliveryDispositionV2) -> u8 {
    match value {
        ContextDeliveryDispositionV2::Delivered => 0,
        ContextDeliveryDispositionV2::Rejected => 1,
        ContextDeliveryDispositionV2::NotDispatched => 2,
        ContextDeliveryDispositionV2::Indeterminate => 3,
    }
}
