use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyError;
use codex_hepta_evidence::EvidenceError;

pub(crate) fn provider_block(
    reason_code: impl Into<String>,
    message: impl Into<String>,
) -> ModelProviderPolicyDecision {
    ModelProviderPolicyDecision::Block {
        reason_code: reason_code.into(),
        message: message.into(),
    }
}

pub(crate) fn provider_block_for_error(error: EvidenceError) -> ModelProviderPolicyDecision {
    let error = provider_evidence_error("hepta_provider_intent_write_failed", error);
    tracing::warn!(
        reason_code = error.reason_code(),
        detail = error.detail(),
        "enforced provider governance intent claim failed"
    );
    provider_block(
        error.reason_code(),
        "Hepta could not claim authoritative provider intent evidence",
    )
}

pub(crate) fn provider_evidence_error(
    fallback_reason_code: &'static str,
    error: EvidenceError,
) -> ModelProviderPolicyError {
    let reason_code = match error {
        EvidenceError::IdempotencyConflict { .. } => "hepta_provider_evidence_conflict",
        EvidenceError::Corrupt(_) => "hepta_provider_evidence_corrupt",
        EvidenceError::Unavailable(_) => "hepta_provider_evidence_unavailable",
        EvidenceError::InvalidRecord(_) => "hepta_provider_evidence_invalid",
        EvidenceError::Serialization(_) => fallback_reason_code,
    };
    ModelProviderPolicyError::new(reason_code, error.to_string())
}
