use codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderRequestKind as ApiRequestKind;
use codex_extension_api::ModelProviderTerminal as ApiTerminal;
use codex_extension_api::ModelProviderTransport as ApiTransport;
use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_contracts::Sha256Digest;

pub(crate) fn provider_intent(
    input: &ModelProviderInvocationInput<'_>,
) -> Result<ProviderInvocationIntent, ModelProviderPolicyError> {
    if input.schema_version != MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION {
        return Err(ModelProviderPolicyError::new(
            "hepta_provider_schema_unsupported",
            "unsupported model-provider policy input schema version",
        ));
    }
    for (label, value) in [
        ("attempt id", input.attempt_id),
        ("request binding id", input.request_binding_id),
        ("thread id", input.thread_id),
        ("turn id", input.turn_id),
        ("provider id", input.provider_id),
        ("model", input.model),
    ] {
        if value.trim().is_empty() {
            return Err(ModelProviderPolicyError::new(
                "hepta_provider_identity_invalid",
                format!("provider invocation requires a non-empty {label}"),
            ));
        }
    }
    if input.thread_id != input.thread_store.level_id()
        || input.turn_id != input.turn_store.level_id()
    {
        return Err(ModelProviderPolicyError::new(
            "hepta_provider_scope_mismatch",
            "provider invocation identity does not match extension store scope",
        ));
    }
    if input.ephemeral_input_sha256.is_some() != input.ephemeral_input_witness_sha256.is_some() {
        return Err(ModelProviderPolicyError::new(
            "hepta_provider_ephemeral_input_incomplete",
            "ephemeral provider input requires both its content and host witness digests",
        ));
    }
    let binding = ProviderRequestBinding {
        schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
        thread_id: input.thread_id.to_string(),
        turn_id: input.turn_id.to_string(),
        host_request_binding_id_sha256: Sha256Digest::for_bytes(
            input.request_binding_id.as_bytes(),
        ),
        request_kind: match input.request_kind {
            ApiRequestKind::Turn => ProviderRequestKind::Turn,
            ApiRequestKind::Prewarm => ProviderRequestKind::Prewarm,
            ApiRequestKind::Compaction => ProviderRequestKind::Compaction,
            ApiRequestKind::Memory => ProviderRequestKind::Memory,
        },
        provider_id: input.provider_id.to_string(),
        provider_config_sha256: contract_digest(input.provider_config_sha256.as_str())?,
        model: input.model.to_string(),
        transport: match input.transport {
            ApiTransport::Http => ProviderTransport::Http,
            ApiTransport::WebSocket => ProviderTransport::WebSocket,
        },
        endpoint_sha256: contract_digest(input.endpoint_sha256.as_str())?,
        logical_request_sha256: contract_digest(input.logical_request_sha256.as_str())?,
        wire_semantic_sha256: contract_digest(input.wire_semantic_sha256.as_str())?,
        ephemeral_input_sha256: input
            .ephemeral_input_sha256
            .map(|digest| contract_digest(digest.as_str()))
            .transpose()?,
        ephemeral_input_witness_sha256: input
            .ephemeral_input_witness_sha256
            .map(|digest| contract_digest(digest.as_str()))
            .transpose()?,
        previous_response_id_sha256: input
            .previous_response_id_sha256
            .map(|digest| contract_digest(digest.as_str()))
            .transpose()?,
        generate: input.generate,
    };
    Ok(ProviderInvocationIntent::for_host_attempt_id(
        input.attempt_id,
        binding,
    ))
}

pub(crate) fn provider_terminal(
    terminal: ApiTerminal,
) -> Result<ProviderTerminal, ModelProviderPolicyError> {
    Ok(match terminal {
        ApiTerminal::Completed {
            response_id_sha256,
            response_items_sha256,
            token_usage_sha256,
            end_turn,
        } => ProviderTerminal::Completed {
            response_id_sha256: contract_digest(response_id_sha256.as_str())?,
            response_items_sha256: contract_digest(response_items_sha256.as_str())?,
            token_usage_sha256: contract_digest(token_usage_sha256.as_str())?,
            end_turn,
        },
        ApiTerminal::CompletedUnary {
            response_items_sha256,
        } => ProviderTerminal::CompletedUnary {
            response_items_sha256: contract_digest(response_items_sha256.as_str())?,
        },
        ApiTerminal::Rejected { reason_code } => ProviderTerminal::Rejected {
            reason_code: stable_reason_code(reason_code)?,
        },
        ApiTerminal::NotDispatched { reason_code } => ProviderTerminal::NotDispatched {
            reason_code: stable_reason_code(reason_code)?,
        },
        ApiTerminal::Indeterminate {
            reason_code,
            partial_response_sha256,
        } => ProviderTerminal::Indeterminate {
            reason_code: stable_reason_code(reason_code)?,
            partial_response_sha256: partial_response_sha256
                .map(|digest| contract_digest(digest.as_str()))
                .transpose()?,
        },
    })
}

fn stable_reason_code(reason_code: String) -> Result<String, ModelProviderPolicyError> {
    if (1..=128).contains(&reason_code.len())
        && reason_code.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-' | b'.')
        })
    {
        Ok(reason_code)
    } else {
        Err(ModelProviderPolicyError::new(
            "hepta_provider_reason_code_invalid",
            "provider terminal reason code is not a stable secret-free identifier",
        ))
    }
}

fn contract_digest(value: &str) -> Result<Sha256Digest, ModelProviderPolicyError> {
    Sha256Digest::parse(value)
        .map_err(|detail| ModelProviderPolicyError::new("hepta_provider_digest_invalid", detail))
}
