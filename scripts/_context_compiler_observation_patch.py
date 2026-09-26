#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:110]!r}")
    file_path.write_text(text.replace(old, new, 1))


replace_once(
    "codex-rs/hepta-context-compiler/src/v2.rs",
    "use std::fmt;\n",
    "use std::fmt;\nuse std::str::FromStr;\n",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/v2.rs",
    "use codex_hepta_contracts::ProviderTerminal;\n",
    "use codex_hepta_contracts::ProviderTerminal;\n"
    "use codex_hepta_contracts::ProviderTransport;\n",
)

exact_observation = r'''
/// Observe a provider terminal against the exact canonical request bytes that
/// crossed the pre-compression HTTP boundary.
///
/// Unlike the legacy compatibility entrypoint, this path does not pretend that
/// a developer-fragment context bundle was an ephemeral-input attachment. The
/// construction-closed final-request proof binds the preparation payload,
/// complete byte coverage, exact tokenizer identity/count, provider/model, and
/// wire semantic digest. The provider-owned receipt remains independently
/// authenticated by `delivery_verifier`.
#[allow(clippy::too_many_arguments)]
pub fn observe_final_provider_delivery_v2(
    preparation: &ContextDeliveryPreparationV2,
    attachment: &ContextAttachmentV2,
    serialization: &SerializedContextV2,
    profile: &ContextModelProfileV2,
    final_request_proof: &crate::provider_closure::FinalProviderRequestProofV2,
    delivery_id: StableId,
    provider_receipt: &ProviderInvocationReceipt,
    delivery_verifier: &impl ContextProviderDeliveryVerifierV2,
    observed_unix_ms: u64,
) -> Result<ContextDeliveryReceiptV2, ContextCompilerV2Error> {
    preparation.validate_for(attachment, serialization, profile)?;
    final_request_proof
        .validate_for(preparation, profile)
        .map_err(|error| ContextCompilerV2Error::ProviderEvidenceInvalid(error.to_string()))?;
    provider_receipt
        .validate()
        .map_err(ContextCompilerV2Error::ProviderReceiptInvalid)?;

    if provider_receipt.intent.binding.transport != ProviderTransport::Http {
        return Err(ContextCompilerV2Error::DeliveryMismatch);
    }
    let provider_wire_semantic_digest = Digest32::from_str(
        provider_receipt
            .intent
            .binding
            .wire_semantic_sha256
            .as_str(),
    )
    .map_err(|error| ContextCompilerV2Error::ProviderReceiptInvalid(error.to_string()))?;
    if provider_wire_semantic_digest != final_request_proof.provider_wire_semantic_digest() {
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

'''
replace_once(
    "codex-rs/hepta-context-compiler/src/v2.rs",
    "fn validate_realizations(\n",
    exact_observation + "fn validate_realizations(\n",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/lib.rs",
    "pub use v2::observe_delivery;\n",
    "pub use v2::observe_delivery;\n"
    "pub use v2::observe_final_provider_delivery_v2;\n",
)
