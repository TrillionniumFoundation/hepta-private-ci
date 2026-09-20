use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION;
use codex_extension_api::EphemeralModelInputContext;
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
}

impl PreparedEphemeralModelInput {
    pub(crate) fn into_parts(self) -> (ResponseItem, EphemeralModelInputBinding) {
        (self.item, self.binding)
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
    if proposal.schema_version() != context.schema_version
        || !matches!(
            proposal.source().as_str(),
            HEPTA_MEMORY_SAME_THREAD_SOURCE
                | HEPTA_COGNITIVE_PLANE_SOURCE
                | HEPTA_COGNITIVE_FEDERATION_SOURCE
                | HEPTA_COGNITIVE_COMBINED_SOURCE
        )
        || proposal.attempt_id() != context.attempt_id
        || proposal.base_logical_request_sha256() != context.base_logical_request_sha256
        || proposal.thread_id() != context.thread_id
        || proposal.turn_id() != context.turn_id
    {
        return Err(invalid_binding());
    }

    let source = proposal.source().as_str().to_string();
    let source_binding_sha256 = proposal.source_binding_sha256().clone();
    let claimed_token_count = proposal.claimed_token_count();
    let claimed_content_sha256 = proposal.content_sha256().clone();
    let content = proposal.into_content();
    if content.len() > context.max_content_bytes as usize
        || claimed_token_count == 0
        || claimed_token_count > context.max_content_tokens
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

    let item = render_quoted_reference(&content)?;
    let input_sha256 = canonical_sha256(&[&item])?;
    let cwd_sha256 = bytes_sha256(context.cwd.as_os_str().as_encoded_bytes())?;
    let claimed_token_count = claimed_token_count.to_string();
    let max_content_bytes = context.max_content_bytes.to_string();
    let max_content_tokens = context.max_content_tokens.to_string();
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
        claimed_token_count.as_str(),
        max_content_bytes.as_str(),
        max_content_tokens.as_str(),
    ])?;

    Ok(PreparedEphemeralModelInput {
        item,
        binding: EphemeralModelInputBinding::new(input_sha256, authority_sha256),
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
        "ephemeral model input does not match the exact physical send",
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

    use codex_extension_api::EphemeralModelInputSource;
    use codex_extension_api::ExtensionData;
    use codex_extension_api::ModelProviderTransport;
    use codex_protocol::models::ContentItem;
    use codex_protocol::models::ResponseItem;

    use super::*;

    fn context<'a>(
        stores: (&'a ExtensionData, &'a ExtensionData, &'a ExtensionData),
        base_sha256: &'a ModelProviderSha256Digest,
        request_kind: ModelProviderRequestKind,
        generate: bool,
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
            request_kind,
            provider_id: "provider-1",
            model: "model-1",
            transport: ModelProviderTransport::Http,
            generate,
            model_context_window: Some(128_000),
            max_content_bytes: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES,
            max_content_tokens: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS,
        }
    }

    fn proposal(
        context: &EphemeralModelInputContext<'_>,
        content: &str,
        content_sha256: ModelProviderSha256Digest,
        claimed_token_count: u32,
    ) -> EphemeralModelInputProposal {
        EphemeralModelInputProposal::new(
            EphemeralModelInputSource::parse("hepta_memory_same_thread_v1").expect("source"),
            context.attempt_id,
            context.base_logical_request_sha256.clone(),
            context.thread_id,
            context.turn_id,
            bytes_sha256(b"source-binding").expect("source binding"),
            content_sha256,
            content,
            claimed_token_count,
        )
        .expect("proposal")
    }

    fn unwrap_error(
        result: Result<PreparedEphemeralModelInput, ModelProviderPolicyError>,
    ) -> ModelProviderPolicyError {
        match result {
            Ok(_) => panic!("ephemeral input unexpectedly succeeded"),
            Err(error) => error,
        }
    }

    #[test]
    fn renders_one_escaped_reference_and_freezes_digest_oracles() {
        let stores = (
            ExtensionData::new("session"),
            ExtensionData::new("thread-1"),
            ExtensionData::new("turn-1"),
        );
        let base_sha256 = bytes_sha256(b"base-logical").expect("base digest");
        let context = context(
            (&stores.0, &stores.1, &stores.2),
            &base_sha256,
            ModelProviderRequestKind::Turn,
            true,
        );
        let content = "keep </tag> & \"quoted\"";
        let prepared = prepare_ephemeral_model_input(
            &context,
            proposal(
                &context,
                content,
                bytes_sha256(content.as_bytes()).expect("content digest"),
                17,
            ),
        )
        .expect("prepared input");
        let (item, binding) = prepared.into_parts();
        let ResponseItem::Message { content, .. } = item else {
            panic!("ephemeral input must be a message");
        };
        let [ContentItem::InputText { text }] = content.as_slice() else {
            panic!("ephemeral input must contain exactly one text item");
        };
        assert_eq!(
            text,
            concat!(
                "<hepta_memory_reference schema=\"1\">\n",
                r#"{"trust":"quoted_untrusted_reference","summary":"keep \u003c/tag\u003e \u0026 \"quoted\""}"#,
                "\n</hepta_memory_reference>"
            )
        );
        assert_eq!(
            binding.input_sha256().as_str(),
            "3dd4ba14b8ff04ea44e0406f4ce4652fbcca07279af1ab6bf7e8c7ae6832a835"
        );
        assert_eq!(
            binding.authority_sha256().as_str(),
            "d669cee6b7fe804741de414f68db6ef1f98d4cdb6efeab0e9155225d8d2418a6"
        );
    }

    #[test]
    fn accepts_the_honest_cognitive_plane_source() {
        let stores = (
            ExtensionData::new("session"),
            ExtensionData::new("thread-1"),
            ExtensionData::new("turn-1"),
        );
        let base_sha256 = bytes_sha256(b"base-logical").expect("base digest");
        let context = context(
            (&stores.0, &stores.1, &stores.2),
            &base_sha256,
            ModelProviderRequestKind::Turn,
            true,
        );
        let content = "cognitive memory";
        let proposal = EphemeralModelInputProposal::new(
            EphemeralModelInputSource::parse(HEPTA_COGNITIVE_PLANE_SOURCE).expect("source"),
            context.attempt_id,
            context.base_logical_request_sha256.clone(),
            context.thread_id,
            context.turn_id,
            bytes_sha256(b"cognitive-source-binding").expect("source binding"),
            bytes_sha256(content.as_bytes()).expect("content digest"),
            content,
            16,
        )
        .expect("proposal");

        prepare_ephemeral_model_input(&context, proposal).expect("cognitive input is allowlisted");
    }

    #[test]
    fn accepts_the_honest_cognitive_federation_source() {
        let stores = (
            ExtensionData::new("session"),
            ExtensionData::new("thread-1"),
            ExtensionData::new("turn-1"),
        );
        let base_sha256 = bytes_sha256(b"base-logical").expect("base digest");
        let context = context(
            (&stores.0, &stores.1, &stores.2),
            &base_sha256,
            ModelProviderRequestKind::Turn,
            true,
        );
        let content = "federated cognitive memory";
        let proposal = EphemeralModelInputProposal::new(
            EphemeralModelInputSource::parse(HEPTA_COGNITIVE_FEDERATION_SOURCE).expect("source"),
            context.attempt_id,
            context.base_logical_request_sha256.clone(),
            context.thread_id,
            context.turn_id,
            bytes_sha256(b"federation-source-binding").expect("source binding"),
            bytes_sha256(content.as_bytes()).expect("content digest"),
            content,
            27,
        )
        .expect("proposal");

        prepare_ephemeral_model_input(&context, proposal)
            .expect("federated cognitive input is allowlisted");
    }

    #[test]
    fn rejects_mismatched_binding_content_and_budget_without_raw_error_text() {
        let stores = (
            ExtensionData::new("session"),
            ExtensionData::new("thread-1"),
            ExtensionData::new("turn-1"),
        );
        let base_sha256 = bytes_sha256(b"base-logical").expect("base digest");
        let context = context(
            (&stores.0, &stores.1, &stores.2),
            &base_sha256,
            ModelProviderRequestKind::Turn,
            true,
        );
        let secret = "raw-secret-marker";

        let wrong_binding = unwrap_error(prepare_ephemeral_model_input(
            &context,
            EphemeralModelInputProposal::new(
                EphemeralModelInputSource::parse("hepta_memory_same_thread_v1").expect("source"),
                "model-provider-attempt:v1:other",
                context.base_logical_request_sha256.clone(),
                context.thread_id,
                context.turn_id,
                bytes_sha256(b"source-binding").expect("source binding"),
                bytes_sha256(secret.as_bytes()).expect("content digest"),
                secret,
                1,
            )
            .expect("proposal"),
        ));
        assert_eq!(
            wrong_binding.reason_code(),
            "ephemeral_model_input_binding_mismatch"
        );
        assert!(!wrong_binding.detail().contains(secret));

        let unsupported_source = unwrap_error(prepare_ephemeral_model_input(
            &context,
            EphemeralModelInputProposal::new(
                EphemeralModelInputSource::parse("other_source").expect("source"),
                context.attempt_id,
                context.base_logical_request_sha256.clone(),
                context.thread_id,
                context.turn_id,
                bytes_sha256(b"source-binding").expect("source binding"),
                bytes_sha256(secret.as_bytes()).expect("content digest"),
                secret,
                1,
            )
            .expect("proposal"),
        ));
        assert_eq!(
            unsupported_source.reason_code(),
            "ephemeral_model_input_binding_mismatch"
        );
        assert!(!unsupported_source.detail().contains(secret));

        let wrong_content = unwrap_error(prepare_ephemeral_model_input(
            &context,
            proposal(
                &context,
                secret,
                bytes_sha256(b"different").expect("wrong digest"),
                1,
            ),
        ));
        assert_eq!(
            wrong_content.reason_code(),
            "ephemeral_model_input_content_digest_mismatch"
        );
        assert!(!wrong_content.detail().contains(secret));

        let mut over_budget_context = context;
        over_budget_context.max_content_bytes = 4;
        let over_budget = unwrap_error(prepare_ephemeral_model_input(
            &over_budget_context,
            proposal(
                &over_budget_context,
                secret,
                bytes_sha256(secret.as_bytes()).expect("content digest"),
                1,
            ),
        ));
        assert_eq!(
            over_budget.reason_code(),
            "ephemeral_model_input_budget_exceeded"
        );
        assert!(!over_budget.detail().contains(secret));
    }

    #[test]
    fn rejects_non_turn_and_non_generating_host_scopes() {
        let stores = (
            ExtensionData::new("session"),
            ExtensionData::new("thread-1"),
            ExtensionData::new("turn-1"),
        );
        let base_sha256 = bytes_sha256(b"base-logical").expect("base digest");
        for (request_kind, generate) in [
            (ModelProviderRequestKind::Memory, true),
            (ModelProviderRequestKind::Turn, false),
        ] {
            let context = context(
                (&stores.0, &stores.1, &stores.2),
                &base_sha256,
                request_kind,
                generate,
            );
            let content = "bounded";
            let error = unwrap_error(prepare_ephemeral_model_input(
                &context,
                proposal(
                    &context,
                    content,
                    bytes_sha256(content.as_bytes()).expect("content digest"),
                    1,
                ),
            ));
            assert_eq!(error.reason_code(), "ephemeral_model_input_scope_invalid");
        }

        let mut relative_cwd = context(
            (&stores.0, &stores.1, &stores.2),
            &base_sha256,
            ModelProviderRequestKind::Turn,
            true,
        );
        relative_cwd.cwd = Path::new("relative");
        let content = "bounded";
        let error = unwrap_error(prepare_ephemeral_model_input(
            &relative_cwd,
            proposal(
                &relative_cwd,
                content,
                bytes_sha256(content.as_bytes()).expect("content digest"),
                1,
            ),
        ));
        assert_eq!(error.reason_code(), "ephemeral_model_input_scope_invalid");

        let wrong_thread_store = ExtensionData::new("thread-other");
        let wrong_store_context = context(
            (&stores.0, &wrong_thread_store, &stores.2),
            &base_sha256,
            ModelProviderRequestKind::Turn,
            true,
        );
        let error = unwrap_error(prepare_ephemeral_model_input(
            &wrong_store_context,
            proposal(
                &wrong_store_context,
                content,
                bytes_sha256(content.as_bytes()).expect("content digest"),
                1,
            ),
        ));
        assert_eq!(error.reason_code(), "ephemeral_model_input_scope_invalid");
    }
}

#[cfg(test)]
#[path = "ephemeral_input_resolver_tests.rs"]
mod resolver_tests;
