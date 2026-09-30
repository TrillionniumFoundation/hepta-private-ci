//! Raw-context-free recovery binding for terminal-only reconciliation.
//!
//! The binding is created before transport from construction-closed compiler
//! objects and the exact provider intent. Its archive contains no prompt bytes
//! and grants no dispatch authority. After restart it may only authenticate a
//! terminal receipt for the same immutable provider attempt; it cannot create a
//! new attempt or release bytes to transport.

use serde::Deserialize;
use serde::Serialize;
use std::str::FromStr;

use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::ContextAttachmentV2;
use super::ContextCompilerV2Error;
use super::ContextDeliveryDispositionV2;
use super::ContextDeliveryPreparationV2;
use super::ContextDeliveryReceiptV2;
use super::ContextModelProfileV2;
use super::ContextProviderDeliveryVerifierV2;
use super::SerializedContextV2;
use super::ensure_digest;
use super::push_digest;
use crate::FinalProviderRequestProofV2;

const RECOVERY_BINDING_DOMAIN: &[u8] = b"hepta.context-delivery-recovery-binding.v2";
const RECOVERY_ARCHIVE_SCHEMA: &str = "hepta.context-delivery-recovery-archive.v2";

#[derive(Clone, Eq, PartialEq)]
pub struct ContextDeliveryRecoveryBindingV2 {
    preparation: ContextDeliveryPreparationV2,
    final_request_proof_digest: Digest32,
    provider_request_digest: Digest32,
    provider_wire_semantic_digest: Digest32,
    provider_intent: ProviderInvocationIntent,
    binding_digest: Digest32,
    authority: AuthorityPosture,
}

impl std::fmt::Debug for ContextDeliveryRecoveryBindingV2 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ContextDeliveryRecoveryBindingV2")
            .field("preparation_digest", &self.preparation.preparation_digest)
            .field(
                "final_request_proof_digest",
                &self.final_request_proof_digest,
            )
            .field("provider_request_digest", &self.provider_request_digest)
            .field(
                "provider_wire_semantic_digest",
                &self.provider_wire_semantic_digest,
            )
            .field("attempt_id", &self.provider_intent.attempt_id)
            .field("binding_digest", &self.binding_digest)
            .finish()
    }
}

impl ContextDeliveryRecoveryBindingV2 {
    #[must_use]
    pub const fn preparation(&self) -> &ContextDeliveryPreparationV2 {
        &self.preparation
    }

    #[must_use]
    pub const fn final_request_proof_digest(&self) -> Digest32 {
        self.final_request_proof_digest
    }

    #[must_use]
    pub const fn provider_request_digest(&self) -> Digest32 {
        self.provider_request_digest
    }

    #[must_use]
    pub const fn provider_wire_semantic_digest(&self) -> Digest32 {
        self.provider_wire_semantic_digest
    }

    #[must_use]
    pub const fn provider_intent(&self) -> &ProviderInvocationIntent {
        &self.provider_intent
    }

    #[must_use]
    pub const fn attachment_digest(&self) -> Digest32 {
        self.preparation.attachment_digest
    }

    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.preparation.payload_digest
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }

    pub fn canonical_archive_bytes(&self) -> Result<Vec<u8>, ContextCompilerV2Error> {
        self.validate()?;
        serde_json::to_vec(&RecoveryArchiveV2::from_binding(self))
            .map_err(|_| ContextCompilerV2Error::DeliveryEvidenceEncodingFailed)
    }

    /// Reopens terminal-reconciliation evidence. This constructor deliberately
    /// does not return dispatch authority and is accepted only by
    /// `observe_recovered_final_provider_delivery_v2`.
    pub fn reopen_canonical_archive(bytes: &[u8]) -> Result<Self, ContextCompilerV2Error> {
        let archive: RecoveryArchiveV2 = serde_json::from_slice(bytes)
            .map_err(|_| ContextCompilerV2Error::RecoveryEvidenceInvalid)?;
        if archive.schema != RECOVERY_ARCHIVE_SCHEMA {
            return Err(ContextCompilerV2Error::RecoveryEvidenceInvalid);
        }
        let binding = archive.into_binding()?;
        binding.validate()?;
        Ok(binding)
    }

    fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        validate_preparation_shape(&self.preparation)?;
        for (name, digest) in [
            ("final_request_proof", self.final_request_proof_digest),
            ("provider_request", self.provider_request_digest),
            ("provider_wire_semantic", self.provider_wire_semantic_digest),
            ("delivery_recovery_binding", self.binding_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        self.provider_intent
            .validate()
            .map_err(ContextCompilerV2Error::ProviderReceiptInvalid)?;
        if self.provider_intent.binding.transport != ProviderTransport::Http {
            return Err(ContextCompilerV2Error::RecoveryEvidenceInvalid);
        }
        let provider_id_digest =
            Digest32::of_bytes(self.provider_intent.binding.provider_id.as_bytes());
        let provider_model_digest =
            Digest32::of_bytes(self.provider_intent.binding.model.as_bytes());
        let wire_digest = parse_digest(self.provider_intent.binding.wire_semantic_sha256.as_str())?;
        let request_digest = self
            .provider_intent
            .binding
            .ephemeral_input_sha256
            .as_ref()
            .ok_or(ContextCompilerV2Error::MissingProviderInputBinding)
            .and_then(|value| parse_digest(value.as_str()))?;
        if self
            .provider_intent
            .binding
            .ephemeral_input_witness_sha256
            .is_none()
        {
            return Err(ContextCompilerV2Error::MissingProviderInputWitness);
        }
        if provider_id_digest != self.preparation.provider_id_digest
            || provider_model_digest != self.preparation.provider_model_digest
            || wire_digest != self.provider_wire_semantic_digest
            || request_digest != self.provider_request_digest
            || self.authority.grants_any()
            || self.binding_digest != self.compute_digest()?
        {
            return Err(ContextCompilerV2Error::RecoveryEvidenceInvalid);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Result<Digest32, ContextCompilerV2Error> {
        let mut bytes = RECOVERY_BINDING_DOMAIN.to_vec();
        for digest in [
            self.preparation.preparation_digest,
            self.final_request_proof_digest,
            self.provider_request_digest,
            self.provider_wire_semantic_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        bytes.extend_from_slice(
            &self
                .provider_intent
                .canonical_wire_bytes()
                .map_err(ContextCompilerV2Error::ProviderReceiptInvalid)?,
        );
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[allow(clippy::too_many_arguments)]
pub fn build_delivery_recovery_binding_v2(
    preparation: &ContextDeliveryPreparationV2,
    attachment: &ContextAttachmentV2,
    serialization: &SerializedContextV2,
    profile: &ContextModelProfileV2,
    final_request_proof: &FinalProviderRequestProofV2,
    provider_intent: &ProviderInvocationIntent,
) -> Result<ContextDeliveryRecoveryBindingV2, ContextCompilerV2Error> {
    preparation.validate_for(attachment, serialization, profile)?;
    final_request_proof
        .validate_for(preparation, profile)
        .map_err(|error| ContextCompilerV2Error::ProviderEvidenceInvalid(error.to_string()))?;
    let mut binding = ContextDeliveryRecoveryBindingV2 {
        preparation: preparation.clone(),
        final_request_proof_digest: final_request_proof.proof_digest(),
        provider_request_digest: final_request_proof.provider_request_digest(),
        provider_wire_semantic_digest: final_request_proof.provider_wire_semantic_digest(),
        provider_intent: provider_intent.clone(),
        binding_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    binding.binding_digest = binding.compute_digest()?;
    binding.validate()?;
    Ok(binding)
}

pub fn observe_recovered_final_provider_delivery_v2(
    recovery: &ContextDeliveryRecoveryBindingV2,
    delivery_id: StableId,
    provider_receipt: &ProviderInvocationReceipt,
    delivery_verifier: &impl ContextProviderDeliveryVerifierV2,
    observed_unix_ms: u64,
) -> Result<ContextDeliveryReceiptV2, ContextCompilerV2Error> {
    recovery.validate()?;
    provider_receipt
        .validate()
        .map_err(ContextCompilerV2Error::ProviderReceiptInvalid)?;
    if provider_receipt.intent != recovery.provider_intent {
        return Err(ContextCompilerV2Error::RecoveryEvidenceInvalid);
    }

    let provider_evidence_verifier_digest = delivery_verifier.verifier_digest();
    ensure_digest(
        "provider_evidence_verifier",
        provider_evidence_verifier_digest,
    )?;
    let delivery_evidence = delivery_verifier
        .verify_delivery(provider_receipt, &recovery.preparation)
        .map_err(ContextCompilerV2Error::ProviderEvidenceInvalid)?;
    ensure_digest("provider_evidence", delivery_evidence.evidence_digest)?;
    if delivery_evidence.recorded_at_unix_ms
        < recovery.preparation.admission_snapshot_observed_unix_ms
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

    let preparation = &recovery.preparation;
    let mut receipt = ContextDeliveryReceiptV2 {
        delivery_id,
        preparation_digest: preparation.preparation_digest,
        attachment_digest: preparation.attachment_digest,
        serialization_receipt_digest: preparation.serialization_receipt_digest,
        payload_digest: preparation.payload_digest,
        model_profile_digest: preparation.model_profile_digest,
        provider_id_digest: preparation.provider_id_digest,
        provider_model_digest: preparation.provider_model_digest,
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
    validate_recovered_receipt(&receipt, recovery)?;
    Ok(receipt)
}

fn validate_preparation_shape(
    preparation: &ContextDeliveryPreparationV2,
) -> Result<(), ContextCompilerV2Error> {
    for (name, digest) in [
        ("delivery_preparation", preparation.preparation_digest),
        ("attachment", preparation.attachment_digest),
        (
            "serialization_receipt",
            preparation.serialization_receipt_digest,
        ),
        ("payload", preparation.payload_digest),
        ("model_profile", preparation.model_profile_digest),
        ("provider_id", preparation.provider_id_digest),
        ("provider_model", preparation.provider_model_digest),
        ("admission_verifier", preparation.admission_verifier_digest),
        ("admission_snapshot", preparation.admission_snapshot_digest),
        (
            "admission_snapshot_verification",
            preparation.admission_snapshot_verification_digest,
        ),
    ] {
        ensure_digest(name, digest)?;
    }
    if preparation.admission_snapshot_observed_unix_ms == 0
        || preparation.authority.grants_any()
        || preparation.preparation_digest != preparation.compute_preparation_digest()
    {
        return Err(ContextCompilerV2Error::RecoveryEvidenceInvalid);
    }
    Ok(())
}

fn validate_recovered_receipt(
    receipt: &ContextDeliveryReceiptV2,
    recovery: &ContextDeliveryRecoveryBindingV2,
) -> Result<(), ContextCompilerV2Error> {
    let preparation = &recovery.preparation;
    for (name, digest) in [
        (
            "provider_request_binding",
            receipt.provider_request_binding_digest,
        ),
        ("provider_attempt", receipt.provider_attempt_digest),
        ("provider_receipt", receipt.provider_receipt_digest),
        ("provider_terminal", receipt.provider_terminal_digest),
        (
            "provider_evidence_verifier",
            receipt.provider_evidence_verifier_digest,
        ),
        ("provider_evidence", receipt.provider_evidence_digest),
        ("delivery_receipt", receipt.receipt_digest),
    ] {
        ensure_digest(name, digest)?;
    }
    if receipt.preparation_digest != preparation.preparation_digest
        || receipt.attachment_digest != preparation.attachment_digest
        || receipt.serialization_receipt_digest != preparation.serialization_receipt_digest
        || receipt.payload_digest != preparation.payload_digest
        || receipt.model_profile_digest != preparation.model_profile_digest
        || receipt.provider_id_digest != preparation.provider_id_digest
        || receipt.provider_model_digest != preparation.provider_model_digest
        || receipt.admission_snapshot_digest != preparation.admission_snapshot_digest
        || receipt.admission_snapshot_verification_digest
            != preparation.admission_snapshot_verification_digest
        || receipt.admission_snapshot_observed_unix_ms
            != preparation.admission_snapshot_observed_unix_ms
        || receipt.revocation_epoch != preparation.revocation_epoch
        || receipt.provider_recorded_at_unix_ms < preparation.admission_snapshot_observed_unix_ms
        || receipt.observed_unix_ms < receipt.provider_recorded_at_unix_ms
        || receipt.authority.grants_any()
        || receipt.receipt_digest != receipt.compute_receipt_digest()
    {
        return Err(ContextCompilerV2Error::RecoveryEvidenceInvalid);
    }
    match receipt.disposition {
        ContextDeliveryDispositionV2::Delivered
        | ContextDeliveryDispositionV2::Rejected
        | ContextDeliveryDispositionV2::NotDispatched
            if receipt.terminal_observed => {}
        ContextDeliveryDispositionV2::Indeterminate if !receipt.terminal_observed => {}
        _ => return Err(ContextCompilerV2Error::InvalidDeliveryDisposition),
    }
    Ok(())
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RecoveryArchiveV2 {
    schema: String,
    preparation_id: String,
    attachment_digest: String,
    serialization_receipt_digest: String,
    payload_digest: String,
    model_profile_digest: String,
    provider_id_digest: String,
    provider_model_digest: String,
    admission_verifier_digest: String,
    admission_snapshot_digest: String,
    admission_snapshot_verification_digest: String,
    admission_snapshot_observed_unix_ms: u64,
    revocation_epoch: u64,
    preparation_digest: String,
    final_request_proof_digest: String,
    provider_request_digest: String,
    provider_wire_semantic_digest: String,
    provider_intent: ProviderInvocationIntent,
    binding_digest: String,
}

impl RecoveryArchiveV2 {
    fn from_binding(binding: &ContextDeliveryRecoveryBindingV2) -> Self {
        let preparation = &binding.preparation;
        Self {
            schema: RECOVERY_ARCHIVE_SCHEMA.to_owned(),
            preparation_id: preparation.preparation_id.as_str().to_owned(),
            attachment_digest: preparation.attachment_digest.to_string(),
            serialization_receipt_digest: preparation.serialization_receipt_digest.to_string(),
            payload_digest: preparation.payload_digest.to_string(),
            model_profile_digest: preparation.model_profile_digest.to_string(),
            provider_id_digest: preparation.provider_id_digest.to_string(),
            provider_model_digest: preparation.provider_model_digest.to_string(),
            admission_verifier_digest: preparation.admission_verifier_digest.to_string(),
            admission_snapshot_digest: preparation.admission_snapshot_digest.to_string(),
            admission_snapshot_verification_digest: preparation
                .admission_snapshot_verification_digest
                .to_string(),
            admission_snapshot_observed_unix_ms: preparation.admission_snapshot_observed_unix_ms,
            revocation_epoch: preparation.revocation_epoch,
            preparation_digest: preparation.preparation_digest.to_string(),
            final_request_proof_digest: binding.final_request_proof_digest.to_string(),
            provider_request_digest: binding.provider_request_digest.to_string(),
            provider_wire_semantic_digest: binding.provider_wire_semantic_digest.to_string(),
            provider_intent: binding.provider_intent.clone(),
            binding_digest: binding.binding_digest.to_string(),
        }
    }

    fn into_binding(self) -> Result<ContextDeliveryRecoveryBindingV2, ContextCompilerV2Error> {
        Ok(ContextDeliveryRecoveryBindingV2 {
            preparation: ContextDeliveryPreparationV2 {
                preparation_id: StableId::new(self.preparation_id)
                    .map_err(|_| ContextCompilerV2Error::RecoveryEvidenceInvalid)?,
                attachment_digest: parse_digest(&self.attachment_digest)?,
                serialization_receipt_digest: parse_digest(&self.serialization_receipt_digest)?,
                payload_digest: parse_digest(&self.payload_digest)?,
                model_profile_digest: parse_digest(&self.model_profile_digest)?,
                provider_id_digest: parse_digest(&self.provider_id_digest)?,
                provider_model_digest: parse_digest(&self.provider_model_digest)?,
                admission_verifier_digest: parse_digest(&self.admission_verifier_digest)?,
                admission_snapshot_digest: parse_digest(&self.admission_snapshot_digest)?,
                admission_snapshot_verification_digest: parse_digest(
                    &self.admission_snapshot_verification_digest,
                )?,
                admission_snapshot_observed_unix_ms: self.admission_snapshot_observed_unix_ms,
                revocation_epoch: self.revocation_epoch,
                preparation_digest: parse_digest(&self.preparation_digest)?,
                authority: AuthorityPosture::DENY_ALL,
            },
            final_request_proof_digest: parse_digest(&self.final_request_proof_digest)?,
            provider_request_digest: parse_digest(&self.provider_request_digest)?,
            provider_wire_semantic_digest: parse_digest(&self.provider_wire_semantic_digest)?,
            provider_intent: self.provider_intent,
            binding_digest: parse_digest(&self.binding_digest)?,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

fn parse_digest(value: &str) -> Result<Digest32, ContextCompilerV2Error> {
    let digest =
        Digest32::from_str(value).map_err(|_| ContextCompilerV2Error::RecoveryEvidenceInvalid)?;
    if digest.is_zero() {
        return Err(ContextCompilerV2Error::RecoveryEvidenceInvalid);
    }
    Ok(digest)
}
