use std::fmt;

use codex_hepta_types::Digest32;

use super::ContextCompilerV2Error;
use super::ContextRealizedItemV2;
use super::SerializedContextV2;

impl fmt::Debug for ContextRealizedItemV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ContextRealizedItemV2")
            .field("item_id", &self.item_id)
            .field("role", &self.role)
            .field("content_digest", &Digest32::of_bytes(&self.content))
            .field("content_bytes", &self.content.len())
            .finish()
    }
}

impl fmt::Debug for SerializedContextV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SerializedContextV2")
            .field("receipt", &self.receipt)
            .field("payload_bytes", &self.payload.len())
            .finish()
    }
}

impl ContextCompilerV2Error {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::EmptyDigest(_) => "context_v2_empty_digest",
            Self::DigestMismatch(_) => "context_v2_digest_mismatch",
            Self::CandidateLimitExceeded => "context_v2_candidate_limit",
            Self::GroupLimitExceeded => "context_v2_group_limit",
            Self::InvalidModelContextLimit => "context_v2_invalid_model_context_limit",
            Self::InvalidTokenBudget => "context_v2_invalid_token_budget",
            Self::InvalidTokenCount(_) => "context_v2_invalid_token_count",
            Self::CandidateContentTooLarge(_) => "context_v2_candidate_content_too_large",
            Self::InvalidSerializedTokenCount => "context_v2_invalid_serialized_token_count",
            Self::DuplicateCandidate(_) => "context_v2_duplicate_candidate",
            Self::DuplicateMandatoryGroup(_) => "context_v2_duplicate_mandatory_group",
            Self::EmptyMandatoryGroup(_) => "context_v2_empty_mandatory_group",
            Self::DuplicateMandatoryItem(_) => "context_v2_duplicate_mandatory_item",
            Self::UnknownMandatoryItem(_) => "context_v2_unknown_mandatory_item",
            Self::GenerationVectorMismatch(_) => "context_v2_generation_vector_mismatch",
            Self::TokenizationItemMismatch(_) => "context_v2_tokenization_item_mismatch",
            Self::TokenizerMismatch(_) => "context_v2_tokenizer_mismatch",
            Self::TokenizerProfileMismatch => "context_v2_tokenizer_profile_mismatch",
            Self::ValueOutOfRange(_) => "context_v2_value_out_of_range",
            Self::SecretRejected(_) => "context_v2_secret_rejected",
            Self::InvalidAdmissionTime(_) => "context_v2_invalid_admission_time",
            Self::InvalidAdmissionSnapshotTime => "context_v2_invalid_admission_snapshot_time",
            Self::DuplicateRevocation(_) => "context_v2_duplicate_revocation",
            Self::NonCanonicalRevocationList => "context_v2_noncanonical_revocation",
            Self::RevocationLimitExceeded => "context_v2_revocation_limit",
            Self::IncompleteRevocationSnapshot => "context_v2_incomplete_revocation_snapshot",
            Self::UnexpectedSnapshotPredecessor => "context_v2_unexpected_snapshot_predecessor",
            Self::SnapshotPredecessorMismatch => "context_v2_snapshot_predecessor_mismatch",
            Self::SnapshotDomainMismatch => "context_v2_snapshot_domain_mismatch",
            Self::RevocationFrontierMismatch => "context_v2_revocation_frontier_mismatch",
            Self::RevocationResurrection(_) => "context_v2_revocation_resurrection",
            Self::AdmissionRecordUnverified(_) => "context_v2_admission_record_unverified",
            Self::AdmissionSnapshotUnverified => "context_v2_admission_snapshot_unverified",
            Self::AdmissionNotYetValid(_) => "context_v2_admission_not_yet_valid",
            Self::AdmissionExpired(_) => "context_v2_admission_expired",
            Self::AdmissionRevoked(_) => "context_v2_admission_revoked",
            Self::AdmissionBindingMismatch(_) => "context_v2_admission_binding_mismatch",
            Self::AdmissionVerifierMismatch(_) => "context_v2_admission_verifier_mismatch",
            Self::AdmissionSnapshotDomainMismatch(_) => {
                "context_v2_admission_snapshot_domain_mismatch"
            }
            Self::StaleAdmissionSnapshot => "context_v2_stale_admission_snapshot",
            Self::MandatoryReferenceLimitExceeded => "context_v2_mandatory_reference_limit",
            Self::InsufficientMandatoryBudget { .. } => "context_v2_insufficient_mandatory_budget",
            Self::TokenBudgetExceeded => "context_v2_token_budget_exceeded",
            Self::SelectedSetMismatch => "context_v2_selected_set_mismatch",
            Self::SelectedTokenCountMismatch => "context_v2_selected_token_count_mismatch",
            Self::ModelProfileMismatch => "context_v2_model_profile_mismatch",
            Self::SerializerProfileMismatch => "context_v2_serializer_profile_mismatch",
            Self::RealizationSetMismatch => "context_v2_realization_set_mismatch",
            Self::DuplicateRealization(_) => "context_v2_duplicate_realization",
            Self::RealizedRoleMismatch(_) => "context_v2_realized_role_mismatch",
            Self::RealizedContentMismatch(_) => "context_v2_realized_content_mismatch",
            Self::RealizedContentTooLarge(_) => "context_v2_realized_content_too_large",
            Self::RealizationBytesExceeded => "context_v2_realization_bytes_exceeded",
            Self::EmptySerializedPayload => "context_v2_empty_serialized_payload",
            Self::SerializedPayloadTooLarge => "context_v2_serialized_payload_too_large",
            Self::SerializedTokenBudgetExceeded { .. } => {
                "context_v2_serialized_token_budget_exceeded"
            }
            Self::SerializationMismatch => "context_v2_serialization_mismatch",
            Self::AttachmentMismatch => "context_v2_attachment_mismatch",
            Self::DeliveryMismatch => "context_v2_delivery_mismatch",
            Self::MissingProviderInputBinding => "context_v2_missing_provider_input_binding",
            Self::MissingProviderInputWitness => "context_v2_missing_provider_input_witness",
            Self::ProviderModelProfileMismatch => "context_v2_provider_model_profile_mismatch",
            Self::ProviderReceiptInvalid(_) => "context_v2_provider_receipt_invalid",
            Self::ProviderEvidenceInvalid(_) => "context_v2_provider_evidence_invalid",
            Self::MissingTerminalObservation => "context_v2_missing_terminal_observation",
            Self::InvalidDeliveryDisposition => "context_v2_invalid_delivery_disposition",
            Self::InvalidObservationTime => "context_v2_invalid_observation_time",
            Self::DeliveryEvidenceEncodingFailed => "context_v2_delivery_evidence_encoding_failed",
            Self::RecoveryEvidenceInvalid => "context_v2_recovery_evidence_invalid",
            Self::AuthorityGranted => "context_v2_authority_granted",
            Self::Arithmetic => "context_v2_arithmetic",
        }
    }
}

impl fmt::Debug for ContextCompilerV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dynamic_error_detail_and_raw_bytes_are_redacted() {
        let marker = "RAW-CONTEXT-DO-NOT-LOG";
        let error = ContextCompilerV2Error::RealizedContentMismatch(marker.to_owned());
        assert_eq!(format!("{error}"), "context_v2_realized_content_mismatch");
        assert_eq!(format!("{error:?}"), "context_v2_realized_content_mismatch");
        assert!(!format!("{error:#?}").contains(marker));
    }
}
