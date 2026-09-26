use serde::Serialize;

use super::ContextCompilerV2Error;
use super::ContextDeliveryDispositionV2;
use super::ContextDeliveryReceiptV2;

const DELIVERY_EVIDENCE_SCHEMA: &str = "hepta.context-delivery-evidence.v2";

#[derive(Serialize)]
struct CanonicalDeliveryEvidenceV2<'a> {
    schema: &'static str,
    delivery_id: &'a str,
    preparation_digest: String,
    attachment_digest: String,
    serialization_receipt_digest: String,
    payload_digest: String,
    model_profile_digest: String,
    provider_id_digest: String,
    provider_model_digest: String,
    provider_request_binding_digest: String,
    provider_attempt_digest: String,
    provider_receipt_digest: String,
    provider_terminal_digest: String,
    provider_evidence_verifier_digest: String,
    provider_evidence_digest: String,
    provider_recorded_at_unix_ms: u64,
    admission_snapshot_digest: String,
    admission_snapshot_verification_digest: String,
    admission_snapshot_observed_unix_ms: u64,
    revocation_epoch: u64,
    terminal_observed: bool,
    disposition: &'static str,
    observed_unix_ms: u64,
    receipt_digest: String,
}

impl ContextDeliveryReceiptV2 {
    /// Canonical, raw-prompt-free durable representation of this construction-
    /// closed receipt. Encoding does not grant authority and does not expose a
    /// decoder that could manufacture a new `ContextDeliveryReceiptV2`.
    pub fn canonical_evidence_bytes(&self) -> Result<Vec<u8>, ContextCompilerV2Error> {
        serde_json::to_vec(&CanonicalDeliveryEvidenceV2 {
            schema: DELIVERY_EVIDENCE_SCHEMA,
            delivery_id: self.delivery_id.as_str(),
            preparation_digest: self.preparation_digest.to_string(),
            attachment_digest: self.attachment_digest.to_string(),
            serialization_receipt_digest: self.serialization_receipt_digest.to_string(),
            payload_digest: self.payload_digest.to_string(),
            model_profile_digest: self.model_profile_digest.to_string(),
            provider_id_digest: self.provider_id_digest.to_string(),
            provider_model_digest: self.provider_model_digest.to_string(),
            provider_request_binding_digest: self.provider_request_binding_digest.to_string(),
            provider_attempt_digest: self.provider_attempt_digest.to_string(),
            provider_receipt_digest: self.provider_receipt_digest.to_string(),
            provider_terminal_digest: self.provider_terminal_digest.to_string(),
            provider_evidence_verifier_digest: self
                .provider_evidence_verifier_digest
                .to_string(),
            provider_evidence_digest: self.provider_evidence_digest.to_string(),
            provider_recorded_at_unix_ms: self.provider_recorded_at_unix_ms,
            admission_snapshot_digest: self.admission_snapshot_digest.to_string(),
            admission_snapshot_verification_digest: self
                .admission_snapshot_verification_digest
                .to_string(),
            admission_snapshot_observed_unix_ms: self.admission_snapshot_observed_unix_ms,
            revocation_epoch: self.revocation_epoch,
            terminal_observed: self.terminal_observed,
            disposition: disposition_name(self.disposition),
            observed_unix_ms: self.observed_unix_ms,
            receipt_digest: self.receipt_digest.to_string(),
        })
        .map_err(|_| ContextCompilerV2Error::DeliveryEvidenceEncodingFailed)
    }
}

const fn disposition_name(disposition: ContextDeliveryDispositionV2) -> &'static str {
    match disposition {
        ContextDeliveryDispositionV2::Delivered => "delivered",
        ContextDeliveryDispositionV2::Rejected => "rejected",
        ContextDeliveryDispositionV2::NotDispatched => "not_dispatched",
        ContextDeliveryDispositionV2::Indeterminate => "indeterminate",
    }
}
