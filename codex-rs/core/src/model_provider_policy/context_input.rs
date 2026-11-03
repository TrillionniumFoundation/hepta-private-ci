use codex_extension_api::MODEL_PROVIDER_CONTEXT_SCHEMA_VERSION;
use codex_extension_api::ModelProviderContextFinalUseInput;
use codex_extension_api::ModelProviderContextFinalUseProposal;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;

use super::binding::ModelProviderAttemptEnvelope;
use super::binding::ModelProviderPolicyContext;

/// Digest-only context binding consumed while freezing the exact provider
/// request. It deliberately implements neither `Clone` nor `Debug`.
pub(crate) struct ModelProviderContextBinding {
    input_sha256: ModelProviderSha256Digest,
    authority_sha256: ModelProviderSha256Digest,
}

impl ModelProviderContextBinding {
    pub(super) fn input_sha256(&self) -> &ModelProviderSha256Digest {
        &self.input_sha256
    }

    pub(super) fn authority_sha256(&self) -> &ModelProviderSha256Digest {
        &self.authority_sha256
    }
}

/// Resolves at most one final-use proof for context already assembled into the
/// logical request. Unlike ephemeral model input, this operation cannot add or
/// mutate request content.
pub(crate) async fn resolve_model_provider_context(
    context: &ModelProviderPolicyContext<'_>,
    attempt: &ModelProviderAttemptEnvelope,
) -> Result<Option<ModelProviderContextBinding>, ModelProviderPolicyError> {
    if attempt.request_kind() != ModelProviderRequestKind::Turn || !attempt.generate() {
        return Ok(None);
    }
    if context.thread_id != attempt.thread_id()
        || context.turn_id != attempt.turn_id()
        || context.request_kind != attempt.request_kind()
        || context.thread_store.level_id() != attempt.thread_id()
        || context.turn_store.level_id() != attempt.turn_id()
    {
        return Err(invalid_scope());
    }

    let input = || ModelProviderContextFinalUseInput {
        schema_version: MODEL_PROVIDER_CONTEXT_SCHEMA_VERSION,
        session_store: context.session_store,
        thread_store: context.thread_store,
        turn_store: context.turn_store,
        attempt_id: attempt.attempt_id(),
        base_logical_request_sha256: attempt.base_logical_request_sha256(),
        thread_id: attempt.thread_id(),
        turn_id: attempt.turn_id(),
        request_kind: attempt.request_kind(),
        provider_id: attempt.provider_id(),
        model: attempt.model(),
        transport: attempt.transport(),
        generate: attempt.generate(),
    };

    let contributors = context
        .registry
        .model_provider_context_final_use_contributors()
        .iter()
        .filter(|contributor| contributor.is_active(context.thread_store, context.turn_store))
        .collect::<Vec<_>>();
    let mut prepared = None;
    for contributor in contributors {
        if let Some(proposal) = contributor.prepare(input()).await? {
            if prepared.is_some() {
                return Err(ModelProviderPolicyError::new(
                    "model_provider_context_multiple_claimants",
                    "multiple context owners claimed one physical provider send",
                ));
            }
            prepared = Some(validate_proposal(&input(), proposal)?);
        }
    }
    Ok(prepared)
}

fn validate_proposal(
    input: &ModelProviderContextFinalUseInput<'_>,
    proposal: ModelProviderContextFinalUseProposal,
) -> Result<ModelProviderContextBinding, ModelProviderPolicyError> {
    if proposal.schema_version() != input.schema_version
        || proposal.attempt_id() != input.attempt_id
        || proposal.base_logical_request_sha256() != input.base_logical_request_sha256
        || proposal.thread_id() != input.thread_id
        || proposal.turn_id() != input.turn_id
        || proposal.provider_id() != input.provider_id
        || proposal.model() != input.model
        || input.request_kind != ModelProviderRequestKind::Turn
        || !input.generate
        || input.thread_store.level_id() != input.thread_id
        || input.turn_store.level_id() != input.turn_id
        || proposal.serialized_token_count() == 0
    {
        return Err(invalid_binding());
    }
    // Access every proof component here so a future proposal extension cannot
    // accidentally leave a security-relevant digest outside host validation.
    for digest in [
        proposal.context_payload_sha256(),
        proposal.authority_sha256(),
        proposal.source_binding_sha256(),
        proposal.execution_profile_sha256(),
        proposal.tokenization_proof_sha256(),
    ] {
        ModelProviderSha256Digest::parse(digest.as_str().to_owned())?;
    }
    Ok(ModelProviderContextBinding {
        input_sha256: proposal.context_payload_sha256().clone(),
        authority_sha256: proposal.authority_sha256().clone(),
    })
}

fn invalid_scope() -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "model_provider_context_scope_invalid",
        "provider context final-use scope does not match the physical attempt",
    )
}

fn invalid_binding() -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "model_provider_context_binding_invalid",
        "provider context final-use proof does not bind the exact attempt and request baseline",
    )
}
