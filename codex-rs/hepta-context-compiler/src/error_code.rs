use crate::ContextCompilerV2Error;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ContextCompilerV2RetryClass {
    Never,
    RefreshAuthority,
    ReduceInput,
    ReconcileProvider,
}

pub trait ContextCompilerV2ErrorExt {
    fn stable_code(&self) -> &'static str;

    fn retry_class(&self) -> ContextCompilerV2RetryClass;
}

impl ContextCompilerV2ErrorExt for ContextCompilerV2Error {
    fn stable_code(&self) -> &'static str {
        match self {
            Self::EmptyDigest(_) => "CTX_V2_EMPTY_DIGEST",
            Self::DigestMismatch(_) => "CTX_V2_DIGEST_MISMATCH",
            Self::CandidateLimitExceeded => "CTX_V2_CANDIDATE_LIMIT",
            Self::GroupLimitExceeded => "CTX_V2_GROUP_LIMIT",
            Self::InvalidModelContextLimit => "CTX_V2_MODEL_CONTEXT_LIMIT",
            Self::InvalidTokenBudget => "CTX_V2_TOKEN_BUDGET_INVALID",
            Self::InvalidTokenCount(_) => "CTX_V2_TOKEN_COUNT_INVALID",
            Self::CandidateContentTooLarge(_) => "CTX_V2_CANDIDATE_TOO_LARGE",
            Self::InvalidSerializedTokenCount => "CTX_V2_SERIALIZED_TOKEN_COUNT_INVALID",
            Self::DuplicateCandidate(_) => "CTX_V2_DUPLICATE_CANDIDATE",
            Self::DuplicateMandatoryGroup(_) => "CTX_V2_DUPLICATE_MANDATORY_GROUP",
            Self::EmptyMandatoryGroup(_) => "CTX_V2_EMPTY_MANDATORY_GROUP",
            Self::DuplicateMandatoryItem(_) => "CTX_V2_DUPLICATE_MANDATORY_ITEM",
            Self::UnknownMandatoryItem(_) => "CTX_V2_UNKNOWN_MANDATORY_ITEM",
            Self::GenerationVectorMismatch(_) => "CTX_V2_GENERATION_MISMATCH",
            Self::TokenizationItemMismatch(_) => "CTX_V2_TOKENIZATION_ITEM_MISMATCH",
            Self::TokenizerMismatch(_) => "CTX_V2_TOKENIZER_MISMATCH",
            Self::TokenizerProfileMismatch => "CTX_V2_TOKENIZER_PROFILE_MISMATCH",
            Self::ValueOutOfRange(_) => "CTX_V2_VALUE_OUT_OF_RANGE",
            Self::SecretRejected(_) => "CTX_V2_SECRET_REJECTED",
            Self::InvalidAdmissionTime(_) => "CTX_V2_ADMISSION_TIME_INVALID",
            Self::InvalidAdmissionSnapshotTime => "CTX_V2_SNAPSHOT_TIME_INVALID",
            Self::DuplicateRevocation(_) => "CTX_V2_DUPLICATE_REVOCATION",
            Self::NonCanonicalRevocationList => "CTX_V2_REVOCATION_LIST_NONCANONICAL",
            Self::RevocationLimitExceeded => "CTX_V2_REVOCATION_LIMIT",
            Self::IncompleteRevocationSnapshot => "CTX_V2_REVOCATION_SNAPSHOT_INCOMPLETE",
            Self::UnexpectedSnapshotPredecessor => "CTX_V2_UNEXPECTED_SNAPSHOT_PREDECESSOR",
            Self::SnapshotPredecessorMismatch => "CTX_V2_SNAPSHOT_PREDECESSOR_MISMATCH",
            Self::SnapshotDomainMismatch => "CTX_V2_SNAPSHOT_DOMAIN_MISMATCH",
            Self::RevocationFrontierMismatch => "CTX_V2_REVOCATION_FRONTIER_MISMATCH",
            Self::RevocationResurrection(_) => "CTX_V2_REVOCATION_RESURRECTION",
            Self::AdmissionRecordUnverified(_) => "CTX_V2_ADMISSION_RECORD_UNVERIFIED",
            Self::AdmissionSnapshotUnverified => "CTX_V2_ADMISSION_SNAPSHOT_UNVERIFIED",
            Self::AdmissionNotYetValid(_) => "CTX_V2_ADMISSION_NOT_YET_VALID",
            Self::AdmissionExpired(_) => "CTX_V2_ADMISSION_EXPIRED",
            Self::AdmissionRevoked(_) => "CTX_V2_ADMISSION_REVOKED",
            Self::AdmissionBindingMismatch(_) => "CTX_V2_ADMISSION_BINDING_MISMATCH",
            Self::AdmissionVerifierMismatch(_) => "CTX_V2_ADMISSION_VERIFIER_MISMATCH",
            Self::AdmissionSnapshotDomainMismatch(_) => "CTX_V2_ADMISSION_SNAPSHOT_DOMAIN_MISMATCH",
            Self::StaleAdmissionSnapshot => "CTX_V2_ADMISSION_SNAPSHOT_STALE",
            Self::MandatoryReferenceLimitExceeded => "CTX_V2_MANDATORY_REFERENCE_LIMIT",
            Self::InsufficientMandatoryBudget { .. } => "CTX_V2_MANDATORY_BUDGET_INSUFFICIENT",
            Self::TokenBudgetExceeded => "CTX_V2_TOKEN_BUDGET_EXCEEDED",
            Self::SelectedSetMismatch => "CTX_V2_SELECTED_SET_MISMATCH",
            Self::SelectedTokenCountMismatch => "CTX_V2_SELECTED_TOKEN_COUNT_MISMATCH",
            Self::ModelProfileMismatch => "CTX_V2_MODEL_PROFILE_MISMATCH",
            Self::SerializerProfileMismatch => "CTX_V2_SERIALIZER_PROFILE_MISMATCH",
            Self::RealizationSetMismatch => "CTX_V2_REALIZATION_SET_MISMATCH",
            Self::DuplicateRealization(_) => "CTX_V2_DUPLICATE_REALIZATION",
            Self::RealizedRoleMismatch(_) => "CTX_V2_REALIZED_ROLE_MISMATCH",
            Self::RealizedContentMismatch(_) => "CTX_V2_REALIZED_CONTENT_MISMATCH",
            Self::RealizedContentTooLarge(_) => "CTX_V2_REALIZED_CONTENT_TOO_LARGE",
            Self::RealizationBytesExceeded => "CTX_V2_REALIZATION_BYTES_EXCEEDED",
            Self::EmptySerializedPayload => "CTX_V2_SERIALIZED_PAYLOAD_EMPTY",
            Self::SerializedPayloadTooLarge => "CTX_V2_SERIALIZED_PAYLOAD_TOO_LARGE",
            Self::SerializedTokenBudgetExceeded { .. } => "CTX_V2_SERIALIZED_TOKEN_BUDGET_EXCEEDED",
            Self::SerializationMismatch => "CTX_V2_SERIALIZATION_MISMATCH",
            Self::AttachmentMismatch => "CTX_V2_ATTACHMENT_MISMATCH",
            Self::DeliveryMismatch => "CTX_V2_DELIVERY_MISMATCH",
            Self::MissingProviderInputBinding => "CTX_V2_PROVIDER_INPUT_BINDING_MISSING",
            Self::MissingProviderInputWitness => "CTX_V2_PROVIDER_INPUT_WITNESS_MISSING",
            Self::ProviderModelProfileMismatch => "CTX_V2_PROVIDER_MODEL_PROFILE_MISMATCH",
            Self::ProviderReceiptInvalid(_) => "CTX_V2_PROVIDER_RECEIPT_INVALID",
            Self::ProviderEvidenceInvalid(_) => "CTX_V2_PROVIDER_EVIDENCE_INVALID",
            Self::MissingTerminalObservation => "CTX_V2_PROVIDER_TERMINAL_MISSING",
            Self::InvalidDeliveryDisposition => "CTX_V2_DELIVERY_DISPOSITION_INVALID",
            Self::InvalidObservationTime => "CTX_V2_OBSERVATION_TIME_INVALID",
            Self::AuthorityGranted => "CTX_V2_AUTHORITY_GRANTED",
            Self::Arithmetic => "CTX_V2_ARITHMETIC",
        }
    }

    fn retry_class(&self) -> ContextCompilerV2RetryClass {
        match self {
            Self::AdmissionNotYetValid(_)
            | Self::AdmissionExpired(_)
            | Self::AdmissionRevoked(_)
            | Self::AdmissionSnapshotUnverified
            | Self::AdmissionRecordUnverified(_)
            | Self::StaleAdmissionSnapshot
            | Self::SnapshotPredecessorMismatch
            | Self::RevocationFrontierMismatch => ContextCompilerV2RetryClass::RefreshAuthority,
            Self::CandidateLimitExceeded
            | Self::GroupLimitExceeded
            | Self::RevocationLimitExceeded
            | Self::MandatoryReferenceLimitExceeded
            | Self::InsufficientMandatoryBudget { .. }
            | Self::TokenBudgetExceeded
            | Self::CandidateContentTooLarge(_)
            | Self::RealizedContentTooLarge(_)
            | Self::RealizationBytesExceeded
            | Self::SerializedPayloadTooLarge
            | Self::SerializedTokenBudgetExceeded { .. } => ContextCompilerV2RetryClass::ReduceInput,
            Self::MissingTerminalObservation => ContextCompilerV2RetryClass::ReconcileProvider,
            _ => ContextCompilerV2RetryClass::Never,
        }
    }
}

#[cfg(test)]
mod tests {
    use crate::ContextCompilerV2Error;

    use super::ContextCompilerV2ErrorExt;
    use super::ContextCompilerV2RetryClass;

    #[test]
    fn stable_codes_and_retry_classes_are_explicit() {
        let stale = ContextCompilerV2Error::StaleAdmissionSnapshot;
        assert_eq!(stale.stable_code(), "CTX_V2_ADMISSION_SNAPSHOT_STALE");
        assert_eq!(stale.retry_class(), ContextCompilerV2RetryClass::RefreshAuthority);

        let terminal = ContextCompilerV2Error::MissingTerminalObservation;
        assert_eq!(terminal.stable_code(), "CTX_V2_PROVIDER_TERMINAL_MISSING");
        assert_eq!(terminal.retry_class(), ContextCompilerV2RetryClass::ReconcileProvider);
    }
}
