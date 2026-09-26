use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION;
use codex_extension_api::EphemeralModelInputContext;
use codex_extension_api::EphemeralModelInputFinalUseGuard;
use codex_extension_api::EphemeralModelInputProposal;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;

use super::binding::ModelProviderAttemptEnvelope;
use super::binding::ModelProviderPolicyContext;
use super::binding::bytes_sha256;
use super::binding::canonical_sha256;
use super::binding::digest_parts_sha256;
use super::lifecycle::ActiveModelProviderPolicies;

const WRAPPER_OPEN: &str = "<hepta_memory_reference schema=\"1\">";
const WRAPPER_CLOSE: &str = "</hepta_memory_reference>";
const HEPTA_MEMORY_SAME_THREAD_SOURCE: &str = "hepta_memory_same_thread_v1";
const HEPTA_COGNITIVE_PLANE_SOURCE: &str = "hepta_cognitive_plane_v1";
const HEPTA_COGNITIVE_FEDERATION_SOURCE: &str = "hepta_cognitive_federation_v1";
const HEPTA_COGNITIVE_COMBINED_SOURCE: &str = "hepta_cognitive_combined_v1";
const HEPTA_CONTEXT_COMPILER_SOURCE: &str = "hepta_context_compiler_v2";
const CONTEXT_COMPILER_MAX_CONTENT_BYTES: u32 = 16 * 1024 * 1024;
const CONTEXT_COMPILER_MAX_CONTENT_TOKENS: u32 = 1_000_000;

/// Digest-only binding consumed by the final provider-attempt envelope.
pub(crate) struct EphemeralModelInputBinding {
    input_sha256: ModelProviderSha256Digest,
    authority_sha256: ModelProviderSha256Digest,
}

impl EphemeralModelInputBinding {
    pub(super) fn new(
        input_sha256: ModelProviderSha256Digest,
        authority_sha256: ModelProviderSha256Digest,
    ) -> Self {
        Self {
            input_sha256,
            authority_sha256,
        }
    }

    pub(super) fn input_sha256(&self) -> &ModelProviderSha256Digest {
        &self.input_sha256
    }

    pub(super) fn authority_sha256(&self) -> &ModelProviderSha256Digest {
        &self.authority_sha256
    }
}

/// Host-owned, attempt-local model input and its digest-only authority.
///
/// This value deliberately implements neither `Clone` nor `Debug`. The raw
/// item may only be consumed into the one physical request being finalized.
pub(crate) struct PreparedEphemeralModelInput {
    item: ResponseItem,
    binding: EphemeralModelInputBinding,
    final_use_guard: Option<Box<dyn EphemeralModelInputFinalUseGuard>>,
}

impl PreparedEphemeralModelInput {
    pub(crate) fn into_parts(
        self,
    ) -> (
        ResponseItem,
        EphemeralModelInputBinding,
        Option<Box<dyn EphemeralModelInputFinalUseGuard>>,
    ) {
        (self.item, self.binding, self.final_use_guard)
    }
}

/// Resolves at most one fresh proposal for this exact physical send.
///
/// Inactive governance, non-generating requests, and non-local turns do not
/// invoke contributors. A proposal is never dispatch authority; the caller
/// must finalize the effective request and acquire a policy lease separately.
pub(crate) async fn resolve_ephemeral_model_input(
    context: &ModelProviderPolicyContext<'_>,
    attempt: &ModelProviderAttemptEnvelope,
    active_policies: &ActiveModelProviderPolicies,
    model_context_window: Option<i64>,
) -> Result<Option<PreparedEphemeralModelInput>, ModelProviderPolicyError> {
    if attempt.request_kind() != ModelProviderRequestKind::Turn
        || !attempt.generate()
        || active_policies.is_empty()
    {
        return Ok(None);
    }
    let Some(cwd) = context.ephemeral_input_cwd.as_deref() else {
        return Ok(None);
    };
    if context.thread_id != attempt.thread_id()
        || context.turn_id != attempt.turn_id()
        || context.request_kind != attempt.request_kind()
        || context.thread_store.level_id() != attempt.thread_id()
        || context.turn_store.level_id() != attempt.turn_id()
        || !cwd.is_absolute()
    {
        return Err(invalid_scope());
    }

    let contributor_input = || EphemeralModelInputContext {
        schema_version: EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION,
        session_store: context.session_store,
        thread_store: context.thread_store,
        turn_store: context.turn_store,
        attempt_id: attempt.attempt_id(),
        base_logical_request_sha256: attempt.base_logical_request_sha256(),
        thread_id: attempt.thread_id(),
        turn_id: attempt.turn_id(),
        cwd,
        request_kind: attempt.request_kind(),
        provider_id: attempt.provider_id(),
        model: attempt.model(),
        transport: attempt.transport(),
        generate: attempt.generate(),
        model_context_window,
        max_content_bytes: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES,
        max_content_tokens: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS,
    };
    let contributors = context
        .registry
        .ephemeral_model_input_contributors()
        .iter()
        .filter(|contributor| contributor.is_active(context.thread_store, context.turn_store))
        .collect::<Vec<_>>();
    let mut prepared = None;
    for contributor in contributors {
        if let Some(proposal) = contributor.contribute(contributor_input()).await? {
            if prepared.is_some() {
                return Err(ModelProviderPolicyError::new(
                    "ephemeral_model_input_multiple_claimants",
                    "multiple contributors claimed one physical model-provider send",
                ));
            }
            prepared = Some(prepare_ephemeral_model_input(
                &contributor_input(),
                proposal,
            )?);
        }
    }

    Ok(prepared)
}

/// Validates and renders one contributor proposal without retaining raw input
/// in `Prompt`, extension stores, policy inputs, traces, or evidence.
pub(super) fn prepare_ephemeral_model_input(
    context: &EphemeralModelInputContext<'_>,
    proposal: EphemeralModelInputProposal,
) -> Result<PreparedEphemeralModelInput, ModelProviderPolicyError> {
    validate_host_context(context)?;
    let developer_policy = proposal.is_developer_policy();
    let source = proposal.source().as_str();
    let valid_source_and_slot = match source {
        HEPTA_CONTEXT_COMPILER_SOURCE => developer_policy,
        HEPTA_MEMORY_SAME_THREAD_SOURCE
        | HEPTA_COGNITIVE_PLANE_SOURCE
        | HEPTA_COGNITIVE_FEDERATION_SOURCE
        | HEPTA_COGNITIVE_COMBINED_SOURCE => !developer_policy,
        _ => false,
    };
    if proposal.schema_version() != context.schema_version
        || !valid_source_and_slot
        || proposal.attempt_id() != context.attempt_id
        || proposal.base_logical_request_sha256() != context.base_logical_request_sha256
        || proposal.thread_id() != context.thread_id
        || proposal.turn_id() != context.turn_id
    {
        return Err(invalid_binding());
    }

    let source = source.to_string();
    let source_binding_sha256 = proposal.source_binding_sha256().clone();
    let claimed_token_count = proposal.claimed_token_count();
    let claimed_content_sha256 = proposal.content_sha256().clone();
    let (content, final_use_guard) = proposal.into_content_and_final_use_guard();
    let (max_content_bytes, max_content_tokens) = if developer_policy {
        (
            CONTEXT_COMPILER_MAX_CONTENT_BYTES,
            CONTEXT_COMPILER_MAX_CONTENT_TOKENS,
        )
    } else {
        (context.max_content_bytes, context.max_content_tokens)
    };
    if content.len() > max_content_bytes as usize
        || claimed_token_count == 0
        || claimed_token_count > max_content_tokens
        || context
            .model_context_window
            .is_some_and(|window| window <= 0 || i64::from(claimed_token_count) > window)
    {
        return Err(budget_exceeded());
    }

    let content_sha256 = bytes_sha256(content.as_bytes())?;
    if content_sha256 != claimed_content_sha256 {
        return Err(content_digest_mismatch());
    }

    let cwd_sha256 = bytes_sha256(context.cwd.as_os_str().as_encoded_bytes())?;
    let claimed_token_count_text = claimed_token_count.to_string();
    let max_content_bytes_text = max_content_bytes.to_string();
    let max_content_tokens_text = max_content_tokens.to_string();
    let (item, input_sha256, authority_sha256) = if developer_policy {
        let item = render_developer_policy(content.clone());
        let input_sha256 = content_sha256.clone();
        let authority_sha256 = digest_parts_sha256([
            "codex:context-compiler-input-authority:v1",
            source.as_str(),
            source_binding_sha256.as_str(),
            context.attempt_id,
            context.thread_id,
            context.turn_id,
            context.provider_id,
            context.model,
            cwd_sha256.as_str(),
            content_sha256.as_str(),
            input_sha256.as_str(),
            claimed_token_count_text.as_str(),
            max_content_bytes_text.as_str(),
            max_content_tokens_text.as_str(),
            "developer_policy",
        ])?;
        (item, input_sha256, authority_sha256)
    } else {
        let item = render_quoted_reference(&content)?;
        let input_sha256 = canonical_sha256(&[&item])?;
        let authority_sha256 = digest_parts_sha256([
            "codex:ephemeral-model-input-authority:v2",
            source.as_str(),
            source_binding_sha256.as_str(),
            context.attempt_id,
            context.thread_id,
            context.turn_id,
            cwd_sha256.as_str(),
            content_sha256.as_str(),
            input_sha256.as_str(),
            claimed_token_count_text.as_str(),
            max_content_bytes_text.as_str(),
            max_content_tokens_text.as_str(),
        ])?;
        (item, input_sha256, authority_sha256)
    };

    Ok(PreparedEphemeralModelInput {
        item,
        binding: EphemeralModelInputBinding::new(input_sha256, authority_sha256),
        final_use_guard,
    })
}

fn validate_host_context(
    context: &EphemeralModelInputContext<'_>,
) -> Result<(), ModelProviderPolicyError> {
    if context.schema_version != EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION
        || context.request_kind != ModelProviderRequestKind::Turn
        || !context.generate
        || context.attempt_id.trim().is_empty()
        || context.thread_id.trim().is_empty()
        || context.turn_id.trim().is_empty()
        || context.thread_store.level_id() != context.thread_id
        || context.turn_store.level_id() != context.turn_id
        || !context.cwd.is_absolute()
    {
        return Err(invalid_scope());
    }
    if context.max_content_bytes == 0
        || context.max_content_bytes > EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES
        || context.max_content_tokens == 0
        || context.max_content_tokens > EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS
    {
        return Err(budget_exceeded());
    }
    Ok(())
}

fn render_developer_policy(content: String) -> ResponseItem {
    ResponseItem::Message {
        id: None,
        role: "developer".to_string(),
        content: vec![ContentItem::InputText { text: content }],
        phase: None,
        internal_chat_message_metadata_passthrough: None,
    }
}

fn render_quoted_reference(content: &str) -> Result<ResponseItem, ModelProviderPolicyError> {
    let encoded = serde_json::to_string(content).map_err(|error| {
        ModelProviderPolicyError::new(
            "ephemeral_model_input_serialization_failed",
            format!("failed to encode ephemeral model input: {error}"),
        )
    })?;
    let encoded = encoded
        .replace('&', "\\u0026")
        .replace('<', "\\u003c")
        .replace('>', "\\u003e");
    let text = format!(
        "{WRAPPER_OPEN}\n{{\"trust\":\"quoted_untrusted_reference\",\"summary\":{encoded}}}\n{WRAPPER_CLOSE}"
    );
    Ok(ResponseItem::Message {
        id: None,
        role: "user".to_string(),
        content: vec![ContentItem::InputText { text }],
        phase: None,
        internal_chat_message_metadata_passthrough: None,
    })
}

fn invalid_scope() -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "ephemeral_model_input_scope_invalid",
        "ephemeral model input is restricted to generating turn sends",
    )
}

fn invalid_binding() -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "ephemeral_model_input_binding_mismatch",
        "ephemeral model input does not match the exact physical send and role slot",
    )
}

fn budget_exceeded() -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "ephemeral_model_input_budget_exceeded",
        "ephemeral model input exceeds the host-owned send budget",
    )
}

fn content_digest_mismatch() -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "ephemeral_model_input_content_digest_mismatch",
        "ephemeral model input content does not match its claimed digest",
    )
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use codex_extension_api::EphemeralModelInputProposal;
    use codex_extension_api::EphemeralModelInputSource;
    use codex_extension_api::ExtensionData;
    use codex_extension_api::ModelProviderTransport;
    use codex_protocol::models::ContentItem;
    use codex_protocol::models::ResponseItem;

    use super::*;

    fn context<'a>(
        stores: (&'a ExtensionData, &'a ExtensionData, &'a ExtensionData),
        base_sha256: &'a ModelProviderSha256Digest,
    ) -> EphemeralModelInputContext<'a> {
        EphemeralModelInputContext {
            schema_version: EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION,
            session_store: stores.0,
            thread_store: stores.1,
            turn_store: stores.2,
            attempt_id: "model-provider-attempt:v1:test",
            base_logical_request_sha256: base_sha256,
            thread_id: "thread-1",
            turn_id: "turn-1",
            cwd: Path::new("/workspace"),
            request_kind: ModelProviderRequestKind::Turn,
            provider_id: "provider-1",
            model: "model-1",
            transport: ModelProviderTransport::Http,
            generate: true,
            model_context_window: Some(128_000),
            max_content_bytes: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES,
            max_content_tokens: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS,
        }
    }

    #[test]
    fn context_compiler_slot_preserves_exact_developer_bytes() {
        let stores = (
            ExtensionData::new("session"),
            ExtensionData::new("thread-1"),
            ExtensionData::new("turn-1"),
        );
        let base = bytes_sha256(b"base").expect("base digest");
        let context = context((&stores.0, &stores.1, &stores.2), &base);
        let content = "exact compiled developer policy";
        let proposal = EphemeralModelInputProposal::new_developer_policy(
            EphemeralModelInputSource::parse(HEPTA_CONTEXT_COMPILER_SOURCE).expect("source"),
            context.attempt_id,
            base,
            context.thread_id,
            context.turn_id,
            bytes_sha256(b"preparation").expect("preparation digest"),
            bytes_sha256(content.as_bytes()).expect("content digest"),
            content,
            7,
        )
        .expect("proposal");
        let prepared = prepare_ephemeral_model_input(&context, proposal).expect("prepared");
        let (item, binding, guard) = prepared.into_parts();
        assert!(guard.is_none());
        assert_eq!(binding.input_sha256(), &bytes_sha256(content.as_bytes()).expect("digest"));
        let ResponseItem::Message { role, content: items, .. } = item else {
            panic!("developer input must be a message");
        };
        assert_eq!(role, "developer");
        let [ContentItem::InputText { text }] = items.as_slice() else {
            panic!("developer input must have one text item");
        };
        assert_eq!(text, content);
    }

    #[test]
    fn memory_source_cannot_claim_developer_policy_slot() {
        let stores = (
            ExtensionData::new("session"),
            ExtensionData::new("thread-1"),
            ExtensionData::new("turn-1"),
        );
        let base = bytes_sha256(b"base").expect("base digest");
        let context = context((&stores.0, &stores.1, &stores.2), &base);
        let proposal = EphemeralModelInputProposal::new_developer_policy(
            EphemeralModelInputSource::parse(HEPTA_MEMORY_SAME_THREAD_SOURCE).expect("source"),
            context.attempt_id,
            base,
            context.thread_id,
            context.turn_id,
            bytes_sha256(b"binding").expect("binding"),
            bytes_sha256(b"content").expect("content"),
            "content",
            1,
        )
        .expect("proposal shape");
        let error = prepare_ephemeral_model_input(&context, proposal)
            .err()
            .unwrap_or_else(|| panic!("role confusion must fail"));
        assert_eq!(error.reason_code(), "ephemeral_model_input_binding_mismatch");
    }
}
