//! Pure mode gates remain covered on every host platform.

use super::require_cognitive_retrieval_context_for_mode;
use super::require_cognitive_runtime_for_profile;
use crate::CognitiveRetrievalMode;
use codex_hepta_memory::CognitiveRuntime;

#[test]
fn compatibility_retrieval_mode_does_not_require_hnmf_context() {
    require_cognitive_retrieval_context_for_mode(CognitiveRetrievalMode::Compatibility, false)
        .expect("compatibility mode may run without an HNMF context");
}

#[test]
fn compatibility_retrieval_mode_rejects_hnmf_context_without_explicit_profile() {
    let result =
        require_cognitive_retrieval_context_for_mode(CognitiveRetrievalMode::Compatibility, true);
    assert!(matches!(
        result,
        Err(crate::AgentdError::Invalid(message))
            if message.contains("select HnmfRequired explicitly")
    ));
}

#[test]
fn hnmf_required_retrieval_mode_fails_closed_without_current_context() {
    let result =
        require_cognitive_retrieval_context_for_mode(CognitiveRetrievalMode::HnmfRequired, false);
    assert!(matches!(
        result,
        Err(crate::AgentdError::Invalid(message))
            if message.contains("HNMF-required retrieval profile")
    ));
    require_cognitive_retrieval_context_for_mode(CognitiveRetrievalMode::HnmfRequired, true)
        .expect("HNMF-required mode accepts an explicitly configured current context");
}

#[cfg(feature = "production-cognitive-write")]
#[test]
fn product_write_profile_fails_closed_when_cognitive_store_is_unavailable() {
    let result = require_cognitive_runtime_for_profile(CognitiveRuntime::Unavailable(
        codex_hepta_memory::CognitiveUnavailableReason::StorageUnavailable,
    ));
    assert!(matches!(
        result,
        Err(crate::AgentdError::CognitiveWriteRuntimeUnavailable)
    ));
}

#[cfg(not(feature = "production-cognitive-write"))]
#[test]
fn read_only_profile_preserves_degraded_cognitive_runtime_behavior() {
    let result = require_cognitive_runtime_for_profile(CognitiveRuntime::Unavailable(
        codex_hepta_memory::CognitiveUnavailableReason::StorageUnavailable,
    ))
    .expect("read-only profile remains availability tolerant");
    assert!(matches!(
        result,
        CognitiveRuntime::Unavailable(
            codex_hepta_memory::CognitiveUnavailableReason::StorageUnavailable
        )
    ));
}
