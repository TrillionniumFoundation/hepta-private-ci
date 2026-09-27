#!/usr/bin/env python3
# Apply redaction, stable error codes, and durable evidence hardening after V3 integration.

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new))


v2_path = "codex-rs/hepta-context-compiler/src/v2.rs"
replace(
    v2_path,
    'use codex_hepta_types::StableId;\n\npub const MAX_CONTEXT_CANDIDATES_V2',
    'use codex_hepta_types::StableId;\n\n'
    '#[path = "v2/delivery_evidence.rs"]\n'
    'mod delivery_evidence;\n'
    '#[path = "v2/redaction.rs"]\n'
    'mod redaction;\n\n'
    'pub const MAX_CONTEXT_CANDIDATES_V2',
)
replace(v2_path, "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct ContextRealizedItemV2", "#[derive(Clone, Eq, PartialEq)]\npub struct ContextRealizedItemV2")
replace(v2_path, "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct SerializedContextV2", "#[derive(Clone, Eq, PartialEq)]\npub struct SerializedContextV2")
replace(v2_path, "#[derive(Clone, Debug, Eq, PartialEq)]\npub enum ContextCompilerV2Error", "#[derive(Clone, Eq, PartialEq)]\npub enum ContextCompilerV2Error")
replace(v2_path, "    InvalidObservationTime,\n    AuthorityGranted,", "    InvalidObservationTime,\n    DeliveryEvidenceEncodingFailed,\n    AuthorityGranted,")
replace(v2_path, '        write!(formatter, "{self:?}")', "        formatter.write_str(self.code())")
write("codex-rs/hepta-context-compiler/src/v2/redaction.rs", 'use std::fmt;\n\nuse codex_hepta_types::Digest32;\n\nuse super::ContextCompilerV2Error;\nuse super::ContextRealizedItemV2;\nuse super::SerializedContextV2;\n\nimpl fmt::Debug for ContextRealizedItemV2 {\n    fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result {\n        formatter\n            .debug_struct("ContextRealizedItemV2")\n            .field("item_id", &self.item_id)\n            .field("role", &self.role)\n            .field("content_digest", &Digest32::of_bytes(&self.content))\n            .field("content_bytes", &self.content.len())\n            .finish()\n    }\n}\n\nimpl fmt::Debug for SerializedContextV2 {\n    fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result {\n        formatter\n            .debug_struct("SerializedContextV2")\n            .field("receipt", &self.receipt)\n            .field("payload_bytes", &self.payload.len())\n            .finish()\n    }\n}\n\nimpl ContextCompilerV2Error {\n    #[must_use]\n    pub const fn code(&self) -> &\'static str {\n        match self {\n            Self::EmptyDigest(_) => "context_v2_empty_digest",\n            Self::DigestMismatch(_) => "context_v2_digest_mismatch",\n            Self::CandidateLimitExceeded => "context_v2_candidate_limit",\n            Self::GroupLimitExceeded => "context_v2_group_limit",\n            Self::InvalidModelContextLimit => "context_v2_invalid_model_context_limit",\n            Self::InvalidTokenBudget => "context_v2_invalid_token_budget",\n            Self::InvalidTokenCount(_) => "context_v2_invalid_token_count",\n            Self::CandidateContentTooLarge(_) => "context_v2_candidate_content_too_large",\n            Self::InvalidSerializedTokenCount => "context_v2_invalid_serialized_token_count",\n            Self::DuplicateCandidate(_) => "context_v2_duplicate_candidate",\n            Self::DuplicateMandatoryGroup(_) => "context_v2_duplicate_mandatory_group",\n            Self::EmptyMandatoryGroup(_) => "context_v2_empty_mandatory_group",\n            Self::DuplicateMandatoryItem(_) => "context_v2_duplicate_mandatory_item",\n            Self::UnknownMandatoryItem(_) => "context_v2_unknown_mandatory_item",\n            Self::GenerationVectorMismatch(_) => "context_v2_generation_vector_mismatch",\n            Self::TokenizationItemMismatch(_) => "context_v2_tokenization_item_mismatch",\n            Self::TokenizerMismatch(_) => "context_v2_tokenizer_mismatch",\n            Self::TokenizerProfileMismatch => "context_v2_tokenizer_profile_mismatch",\n            Self::ValueOutOfRange(_) => "context_v2_value_out_of_range",\n            Self::SecretRejected(_) => "context_v2_secret_rejected",\n            Self::InvalidAdmissionTime(_) => "context_v2_invalid_admission_time",\n            Self::InvalidAdmissionSnapshotTime => "context_v2_invalid_admission_snapshot_time",\n            Self::DuplicateRevocation(_) => "context_v2_duplicate_revocation",\n            Self::NonCanonicalRevocationList => "context_v2_noncanonical_revocation",\n            Self::RevocationLimitExceeded => "context_v2_revocation_limit",\n            Self::IncompleteRevocationSnapshot => "context_v2_incomplete_revocation_snapshot",\n            Self::UnexpectedSnapshotPredecessor => "context_v2_unexpected_snapshot_predecessor",\n            Self::SnapshotPredecessorMismatch => "context_v2_snapshot_predecessor_mismatch",\n            Self::SnapshotDomainMismatch => "context_v2_snapshot_domain_mismatch",\n            Self::RevocationFrontierMismatch => "context_v2_revocation_frontier_mismatch",\n            Self::RevocationResurrection(_) => "context_v2_revocation_resurrection",\n            Self::AdmissionRecordUnverified(_) => "context_v2_admission_record_unverified",\n            Self::AdmissionSnapshotUnverified => "context_v2_admission_snapshot_unverified",\n            Self::AdmissionNotYetValid(_) => "context_v2_admission_not_yet_valid",\n            Self::AdmissionExpired(_) => "context_v2_admission_expired",\n            Self::AdmissionRevoked(_) => "context_v2_admission_revoked",\n            Self::AdmissionBindingMismatch(_) => "context_v2_admission_binding_mismatch",\n            Self::AdmissionVerifierMismatch(_) => "context_v2_admission_verifier_mismatch",\n            Self::AdmissionSnapshotDomainMismatch(_) => "context_v2_admission_snapshot_domain_mismatch",\n            Self::StaleAdmissionSnapshot => "context_v2_stale_admission_snapshot",\n            Self::MandatoryReferenceLimitExceeded => "context_v2_mandatory_reference_limit",\n            Self::InsufficientMandatoryBudget { .. } => "context_v2_insufficient_mandatory_budget",\n            Self::TokenBudgetExceeded => "context_v2_token_budget_exceeded",\n            Self::SelectedSetMismatch => "context_v2_selected_set_mismatch",\n            Self::SelectedTokenCountMismatch => "context_v2_selected_token_count_mismatch",\n            Self::ModelProfileMismatch => "context_v2_model_profile_mismatch",\n            Self::SerializerProfileMismatch => "context_v2_serializer_profile_mismatch",\n            Self::RealizationSetMismatch => "context_v2_realization_set_mismatch",\n            Self::DuplicateRealization(_) => "context_v2_duplicate_realization",\n            Self::RealizedRoleMismatch(_) => "context_v2_realized_role_mismatch",\n            Self::RealizedContentMismatch(_) => "context_v2_realized_content_mismatch",\n            Self::RealizedContentTooLarge(_) => "context_v2_realized_content_too_large",\n            Self::RealizationBytesExceeded => "context_v2_realization_bytes_exceeded",\n            Self::EmptySerializedPayload => "context_v2_empty_serialized_payload",\n            Self::SerializedPayloadTooLarge => "context_v2_serialized_payload_too_large",\n            Self::SerializedTokenBudgetExceeded { .. } => "context_v2_serialized_token_budget_exceeded",\n            Self::SerializationMismatch => "context_v2_serialization_mismatch",\n            Self::AttachmentMismatch => "context_v2_attachment_mismatch",\n            Self::DeliveryMismatch => "context_v2_delivery_mismatch",\n            Self::MissingProviderInputBinding => "context_v2_missing_provider_input_binding",\n            Self::MissingProviderInputWitness => "context_v2_missing_provider_input_witness",\n            Self::ProviderModelProfileMismatch => "context_v2_provider_model_profile_mismatch",\n            Self::ProviderReceiptInvalid(_) => "context_v2_provider_receipt_invalid",\n            Self::ProviderEvidenceInvalid(_) => "context_v2_provider_evidence_invalid",\n            Self::MissingTerminalObservation => "context_v2_missing_terminal_observation",\n            Self::InvalidDeliveryDisposition => "context_v2_invalid_delivery_disposition",\n            Self::InvalidObservationTime => "context_v2_invalid_observation_time",\n            Self::DeliveryEvidenceEncodingFailed => "context_v2_delivery_evidence_encoding_failed",\n            Self::AuthorityGranted => "context_v2_authority_granted",\n            Self::Arithmetic => "context_v2_arithmetic",\n        }\n    }\n}\n\nimpl fmt::Debug for ContextCompilerV2Error {\n    fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result {\n        formatter.write_str(self.code())\n    }\n}\n\n#[cfg(test)]\nmod tests {\n    use super::*;\n\n    #[test]\n    fn error_debug_and_display_do_not_reveal_dynamic_detail() {\n        let marker = "raw-secret-marker";\n        let error = ContextCompilerV2Error::RealizedContentMismatch(marker.to_owned());\n        assert!(!format!("{error:?}").contains(marker));\n        assert!(!error.to_string().contains(marker));\n        assert_eq!(error.code(), "context_v2_realized_content_mismatch");\n    }\n}\n')

provider_path = "codex-rs/hepta-context-compiler/src/provider_closure.rs"
replace(provider_path, "#[derive(Clone, Debug, Eq, PartialEq)]\npub enum ProviderClosureErrorV2", "#[derive(Clone, Eq, PartialEq)]\npub enum ProviderClosureErrorV2")
replace(provider_path, "impl fmt::Display for ProviderClosureErrorV2 {\n", 'impl ProviderClosureErrorV2 {\n    #[must_use]\n    pub const fn code(&self) -> &\'static str {\n        match self {\n            Self::Core(_) => "provider_closure_v2_core",\n            Self::EmptyDigest(_) => "provider_closure_v2_empty_digest",\n            Self::SnapshotPredecessorMismatch => "provider_closure_v2_snapshot_predecessor_mismatch",\n            Self::InvalidTokenizerIdentity => "provider_closure_v2_invalid_tokenizer_identity",\n            Self::TokenizerFailed(_) => "provider_closure_v2_tokenizer_failed",\n            Self::InvalidTokenCount => "provider_closure_v2_invalid_token_count",\n            Self::FinalRequestEmpty => "provider_closure_v2_final_request_empty",\n            Self::FinalRequestTooLarge => "provider_closure_v2_final_request_too_large",\n            Self::ContextPayloadNotUtf8 => "provider_closure_v2_context_payload_not_utf8",\n            Self::ContextPayloadMissing => "provider_closure_v2_context_payload_missing",\n            Self::ContextPayloadAmbiguous => "provider_closure_v2_context_payload_ambiguous",\n            Self::FramingVerifierRejected(_) => "provider_closure_v2_framing_verifier_rejected",\n            Self::SegmentCoverageInvalid => "provider_closure_v2_segment_coverage_invalid",\n            Self::Arithmetic => "provider_closure_v2_arithmetic",\n        }\n    }\n}\n\nimpl fmt::Debug for ProviderClosureErrorV2 {\n    fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result {\n        formatter.write_str(self.code())\n    }\n}\n\nimpl fmt::Display for ProviderClosureErrorV2 {\n')
replace(provider_path, '        write!(formatter, "{self:?}")', "        formatter.write_str(self.code())")

delivery_path = "codex-rs/hepta-prompt-registry/src/delivery.rs"
replace(delivery_path, "use std::collections::BTreeSet;\n", "use std::collections::BTreeSet;\nuse std::fmt;\n")
replace(delivery_path, "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct RealizationDeliveryV2", "#[derive(Clone, Eq, PartialEq)]\npub struct RealizationDeliveryV2")
replace(delivery_path, "impl RealizationDeliveryV2 {\n", '''impl fmt::Debug for RealizationDeliveryV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RealizationDeliveryV2")
            .field("snapshot_digest", &self.snapshot_digest)
            .field("binding", &self.binding)
            .field("payload_digest", &Digest32::of_bytes(&self.payload))
            .field("payload_bytes", &self.payload.len())
            .field("delivery_digest", &self.delivery_digest)
            .field("authority", &self.authority)
            .finish()
    }
}

impl RealizationDeliveryV2 {
''')

authority_path = "codex-rs/hepta-prompt-registry/src/context_authority.rs"
replace(authority_path, "#[derive(Clone, Debug, Eq, PartialEq)]\npub enum PromptContextAuthorityErrorV3", "#[derive(Clone, Eq, PartialEq)]\npub enum PromptContextAuthorityErrorV3")
replace(authority_path, "impl fmt::Display for PromptContextAuthorityErrorV3 {\n", '''impl fmt::Debug for PromptContextAuthorityErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl fmt::Display for PromptContextAuthorityErrorV3 {
''')

product_path = "codex-rs/hepta-intelligence/src/prompt_product_v3.rs"
replace(product_path, "#[derive(Debug)]\npub enum PromptProductV3Error", "pub enum PromptProductV3Error")
replace(product_path, "impl fmt::Display for PromptProductV3Error {\n", '''impl fmt::Debug for PromptProductV3Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl fmt::Display for PromptProductV3Error {
''')

pipeline_path = "codex-rs/hepta-intelligence/src/prompt_pipeline.rs"
for old, new in [
    ("#[derive(Clone, Debug, Eq, PartialEq)]\npub struct PromptPayloadMaterializationV1", "#[derive(Clone, Eq, PartialEq)]\npub struct PromptPayloadMaterializationV1"),
    ("#[derive(Clone, Debug, Eq, PartialEq)]\npub struct PromptDeliveryPrepareRequestV1", "#[derive(Clone, Eq, PartialEq)]\npub struct PromptDeliveryPrepareRequestV1"),
    ("#[derive(Clone, Debug, Eq, PartialEq)]\npub struct PreparedPromptDeliveryV1", "#[derive(Clone, Eq, PartialEq)]\npub struct PreparedPromptDeliveryV1"),
    ("#[derive(Clone, Debug)]\nstruct ExactPreparedSerializer", "#[derive(Clone)]\nstruct ExactPreparedSerializer"),
]:
    replace(pipeline_path, old, new)
legacy_delivery_path = "codex-rs/hepta-intelligence/src/prompt_delivery.rs"
replace(legacy_delivery_path, "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct PromptRegistryCompiledContextV2", "#[derive(Clone, Eq, PartialEq)]\npub struct PromptRegistryCompiledContextV2")
intelligence_lib = "codex-rs/hepta-intelligence/src/lib.rs"
replace(intelligence_lib, "mod prompt_product_v3;\n\n", "mod prompt_product_v3;\n#[cfg(feature = \"legacy-prompt-context-v1\")]\nmod prompt_redaction;\n\n")
write("codex-rs/hepta-intelligence/src/prompt_redaction.rs", 'use std::fmt;\n\nuse crate::PreparedPromptDeliveryV1;\nuse crate::PromptDeliveryPrepareRequestV1;\nuse crate::PromptPayloadMaterializationV1;\nuse crate::PromptRegistryCompiledContextV2;\n\nimpl fmt::Debug for PromptPayloadMaterializationV1 {\n    fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result {\n        formatter.debug_struct("PromptPayloadMaterializationV1").field("payload_count", &self.payloads.len()).field("payload_bytes", &self.payloads.iter().map(|payload| payload.payload.len()).sum::<usize>()).field("bundle_digest", &self.bundle_digest).field("authority", &self.authority).finish()\n    }\n}\n\nimpl fmt::Debug for PromptDeliveryPrepareRequestV1 {\n    fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result {\n        formatter.debug_struct("PromptDeliveryPrepareRequestV1").field("serialization_id", &self.serialization_id).field("serialized_payload_bytes", &self.serialized_payload.len()).field("attachment_id", &self.attachment_id).finish()\n    }\n}\n\nimpl fmt::Debug for PreparedPromptDeliveryV1 {\n    fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result {\n        formatter.debug_struct("PreparedPromptDeliveryV1").field("serialization_receipt_digest", &self.serialization.receipt_digest()).field("attachment_digest", &self.attachment.attachment_digest()).field("materialization", &self.materialization).field("serialization_proof_digest", &self.serialization_proof.proof_digest).field("serialized_payload_bytes", &self.serialized_payload.len()).finish()\n    }\n}\n\nimpl fmt::Debug for PromptRegistryCompiledContextV2 {\n    fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result {\n        formatter.debug_struct("PromptRegistryCompiledContextV2").field("compilation_receipt_digest", &self.compiled.receipt().receipt_digest()).field("selected_delivery_count", &self.selected_deliveries.len()).field("serialized_payload_bytes", &self.serialized_payload.len()).field("serialization_receipt_digest", &self.serialization.receipt_digest()).field("attachment_digest", &self.attachment.attachment_digest()).field("delivery_set_digest", &self.delivery_set_digest).field("authority", &self.authority).finish()\n    }\n}\n')

extension_path = "codex-rs/ext/hepta-prompt/src/lib.rs"
replace(extension_path, "mod exact_body;\n", "mod exact_body;\nmod redaction;\n")
for old, new in [
    ("#[derive(Clone, Debug, Eq, PartialEq)]\npub struct PromptRuntimeDeveloperFragmentV1", "#[derive(Clone, Eq, PartialEq)]\npub struct PromptRuntimeDeveloperFragmentV1"),
    ("#[derive(Clone, Debug, Eq, PartialEq)]\npub struct PromptRuntimeAttachmentV1", "#[derive(Clone, Eq, PartialEq)]\npub struct PromptRuntimeAttachmentV1"),
    ("#[derive(Clone, Debug, Eq, PartialEq)]\npub struct PromptRuntimeHostError", "#[derive(Clone, Eq, PartialEq)]\npub struct PromptRuntimeHostError"),
    ("#[derive(Clone, Debug, Eq, PartialEq)]\npub struct PromptRuntimeFinalRequestV2", "#[derive(Clone, Eq, PartialEq)]\npub struct PromptRuntimeFinalRequestV2"),
    ("#[derive(Clone, Copy, Debug, Eq, PartialEq)]\npub enum PromptRuntimeError", "#[derive(Clone, Copy, Eq, PartialEq)]\npub enum PromptRuntimeError"),
]:
    replace(extension_path, old, new)
replace(extension_path, '        write!(formatter, "{}: {}", self.reason_code, self.detail)', "        formatter.write_str(&self.reason_code)")
replace(extension_path, '        write!(formatter, "{self:?}")', "        formatter.write_str(self.code())")
write("codex-rs/ext/hepta-prompt/src/redaction.rs", 'use std::fmt;\n\nuse codex_hepta_types::Digest32;\n\nuse super::PromptRuntimeAttachmentV1;\nuse super::PromptRuntimeDeveloperFragmentV1;\nuse super::PromptRuntimeError;\nuse super::PromptRuntimeFinalRequestV2;\nuse super::PromptRuntimeHostError;\n\nimpl fmt::Debug for PromptRuntimeDeveloperFragmentV1 {\n    fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result { formatter.debug_struct("PromptRuntimeDeveloperFragmentV1").field("content_digest", &self.content_digest).field("text_bytes", &self.text.len()).finish() }\n}\nimpl fmt::Debug for PromptRuntimeAttachmentV1 {\n    fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result { let fragment_bytes = self.developer_fragments.iter().map(|fragment| fragment.text.len()).sum::<usize>(); formatter.debug_struct("PromptRuntimeAttachmentV1").field("compilation_id", &self.compilation_id).field("context_attachment_digest", &self.context_attachment_digest).field("context_payload_digest", &self.context_payload_digest).field("model", &self.model).field("deadline_ms", &self.deadline_ms).field("developer_fragment_count", &self.developer_fragments.len()).field("developer_fragment_bytes", &fragment_bytes).field("source_binding_digest", &self.source_binding_digest).finish() }\n}\nimpl fmt::Debug for PromptRuntimeFinalRequestV2 {\n    fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result { formatter.debug_struct("PromptRuntimeFinalRequestV2").field("attachment", &self.attachment).field("attempt", &self.attempt).field("canonical_request_digest", &Digest32::of_bytes(&self.canonical_request)).field("canonical_request_bytes", &self.canonical_request.len()).finish() }\n}\nimpl fmt::Debug for PromptRuntimeHostError {\n    fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result { formatter.debug_struct("PromptRuntimeHostError").field("reason_code", &self.reason_code).field("detail_bytes", &self.detail.len()).finish() }\n}\nimpl PromptRuntimeError { #[must_use] pub const fn code(&self) -> &\'static str { match self { Self::InvalidAttachment(_) => "prompt_runtime_invalid_attachment", Self::InvalidProviderBinding => "prompt_runtime_invalid_provider_binding", Self::InvalidTerminalRecord => "prompt_runtime_invalid_terminal_record", Self::ClockUnavailable => "prompt_runtime_clock_unavailable", } } }\nimpl fmt::Debug for PromptRuntimeError { fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result { formatter.write_str(self.code()) } }\n\n#[cfg(test)]\nmod tests { use super::*; use codex_hepta_types::StableId; #[test] fn raw_fragment_and_attachment_debug_are_redacted() { let marker = "raw-secret-marker"; let fragment = PromptRuntimeDeveloperFragmentV1::new(marker.to_owned()).expect("fragment"); assert!(!format!("{fragment:?}").contains(marker)); let attachment = PromptRuntimeAttachmentV1::new(StableId::new("compilation:redaction").expect("id"), Digest32::of_bytes(b"attachment"), Digest32::of_bytes(b"payload"), "model", 1, vec![fragment]).expect("attachment"); assert!(!format!("{attachment:?}").contains(marker)); } #[test] fn host_error_debug_and_display_do_not_reveal_detail() { let marker = "raw-secret-marker"; let error = PromptRuntimeHostError::new("stable_code", marker); assert!(!format!("{error:?}").contains(marker)); assert!(!error.to_string().contains(marker)); } }\n')

fragment_path = "codex-rs/ext/extension-api/src/contributors/prompt.rs"
replace(fragment_path, "#[derive(Clone, Debug, PartialEq, Eq)]\npub struct PromptFragment", "#[derive(Clone, PartialEq, Eq)]\npub struct PromptFragment")
replace(fragment_path, "impl PromptFragment {\n", '''impl std::fmt::Debug for PromptFragment {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.debug_struct("PromptFragment").field("slot", &self.slot).field("text_bytes", &self.text.len()).field("content_kind", &self.content_kind).finish()
    }
}

impl PromptFragment {
''')

runtime_path = "codex-rs/hepta-agentd/src/prompt_runtime.rs"
replace(runtime_path, "use crate::exact_context_delivery::ExactContextDeliveryError;\n\n", "use crate::exact_context_delivery::ExactContextDeliveryError;\n\n#[path = \"prompt_runtime/redaction.rs\"]\nmod redaction;\n\n")
replace(runtime_path, "#[derive(Clone, Debug, Eq, PartialEq)]\npub enum AgentdPromptRuntimeError", "#[derive(Clone, Eq, PartialEq)]\npub enum AgentdPromptRuntimeError")
replace(runtime_path, "#[derive(Debug)]\npub enum AgentdPromptPipelineError", "pub enum AgentdPromptPipelineError")
runtime_text = read(runtime_path)
old_display = '        write!(formatter, "{self:?}")'
if runtime_text.count(old_display) != 2:
    raise SystemExit(f"{runtime_path}: expected two Display anchors, found {runtime_text.count(old_display)}")
write(runtime_path, runtime_text.replace(old_display, "        formatter.write_str(self.code())"))
write("codex-rs/hepta-agentd/src/prompt_runtime/redaction.rs", 'use std::fmt;\n\nuse super::AgentdPromptPipelineError;\nuse super::AgentdPromptRuntimeError;\n\nimpl AgentdPromptRuntimeError { #[must_use] pub const fn code(&self) -> &\'static str { match self { Self::InvalidTurnId => "agentd_prompt_invalid_turn", Self::InvalidModel => "agentd_prompt_invalid_model", Self::InvalidDeadline => "agentd_prompt_invalid_deadline", Self::SourceValidationFailed => "agentd_prompt_source_validation", Self::EmptySelection => "agentd_prompt_empty_selection", Self::UnsupportedPromptRole => "agentd_prompt_unsupported_role", Self::PayloadNotUtf8 => "agentd_prompt_payload_not_utf8", Self::CapacityExceeded => "agentd_prompt_capacity", Self::StageConflict => "agentd_prompt_stage_conflict", Self::DispatchConflict => "agentd_prompt_dispatch_conflict", Self::TerminalWithoutDispatch => "agentd_prompt_terminal_without_dispatch", Self::TerminalBindingMismatch => "agentd_prompt_terminal_binding_mismatch", Self::TerminalConflict => "agentd_prompt_terminal_conflict", Self::IndeterminatePending => "agentd_prompt_indeterminate_pending", Self::StatePoisoned => "agentd_prompt_state_poisoned", Self::CorruptState => "agentd_prompt_corrupt_state", Self::StateLocked => "agentd_prompt_state_locked", Self::Unavailable => "agentd_prompt_unavailable", Self::IndeterminateDurability => "agentd_prompt_indeterminate_durability", Self::ReopenRequired => "agentd_prompt_reopen_required", Self::Adapter(_) => "agentd_prompt_adapter", } } }\nimpl fmt::Debug for AgentdPromptRuntimeError { fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result { formatter.write_str(self.code()) } }\nimpl AgentdPromptPipelineError { #[must_use] pub const fn code(&self) -> &\'static str { match self { Self::RegistryOpen(_) => "agentd_prompt_pipeline_registry_open", Self::RuntimeOpen(_) => "agentd_prompt_pipeline_runtime_open", Self::ExactOpen(_) => "agentd_prompt_pipeline_exact_open", Self::StatePoisoned => "agentd_prompt_pipeline_state_poisoned", Self::CandidateSource(_) => "agentd_prompt_pipeline_candidate_source", Self::Compilation(_) => "agentd_prompt_pipeline_compilation", Self::Stage(_) => "agentd_prompt_pipeline_stage", Self::ExactStage(_) => "agentd_prompt_pipeline_exact_stage", } } }\nimpl fmt::Debug for AgentdPromptPipelineError { fn fmt(&self, formatter: &mut fmt::Formatter<\'_>) -> fmt::Result { formatter.write_str(self.code()) } }\n#[cfg(test)] mod tests { use super::*; #[test] fn dynamic_adapter_details_are_redacted() { let marker = "raw-secret-marker"; let error = AgentdPromptRuntimeError::Adapter(marker.to_owned()); assert_eq!(error.code(), "agentd_prompt_adapter"); assert!(!format!("{error:?}").contains(marker)); assert!(!error.to_string().contains(marker)); } }\n')

exact_path = "codex-rs/hepta-agentd/src/exact_context_delivery.rs"
replace(exact_path, "#[derive(Clone, Debug, Eq, PartialEq)]\npub(crate) enum ExactContextDeliveryError", "#[derive(Clone, Eq, PartialEq)]\npub(crate) enum ExactContextDeliveryError")
replace(exact_path, "impl fmt::Display for ExactContextDeliveryError {\n", '''impl fmt::Debug for ExactContextDeliveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result { formatter.write_str(self.reason_code()) }
}

impl fmt::Display for ExactContextDeliveryError {
''')
replace(exact_path, '''        match self {
            Self::Conflict(detail) => write!(formatter, "{}: {detail}", self.reason_code()),
            Self::Domain(detail) => write!(formatter, "{}: {detail}", self.reason_code()),
            _ => formatter.write_str(self.reason_code()),
        }''', "        formatter.write_str(self.reason_code())")