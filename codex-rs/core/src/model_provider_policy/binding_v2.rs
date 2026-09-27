//! Exact-tokenizer wrapper around the established provider binding.
//!
//! The compatibility implementation still owns provider request identity and
//! ephemeral-input witnesses. This wrapper freezes the same canonical wire
//! bytes, invokes an explicitly installed exact tokenizer capability, validates
//! its digest-only receipt, and records it in turn-scoped state before the
//! physical provider policy can run.

use std::sync::Arc;

use codex_extension_api::ExtensionData;
use codex_extension_api::MODEL_PROVIDER_EXACT_TOKENIZER_SCHEMA_VERSION;
use codex_extension_api::ModelProviderExactTokenizationState;
use codex_extension_api::ModelProviderExactTokenizerHost;
use codex_extension_api::ModelProviderExactTokenizerRequest;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTransport;
use serde::Serialize;
use serde_json::Value;

use super::ephemeral_input::EphemeralModelInputBinding;

// The established implementation is kept as a reviewed compatibility core.
// These aliases preserve the module paths expected inside that source file
// when it is compiled as a child of this wrapper.
mod ephemeral_input {
    pub(crate) use super::super::ephemeral_input::EphemeralModelInputBinding;
}

mod transport {
    pub(crate) use super::super::transport::ProviderRoutingHint;
}

#[path = "binding.rs"]
mod compatibility;

pub(crate) use compatibility::ModelProviderPolicyContext;
pub(crate) use compatibility::PreparedModelProviderPolicy;
#[cfg(test)]
pub(crate) use compatibility::bytes_sha256;
pub(crate) use compatibility::canonical_sha256;
pub(crate) use compatibility::digest_parts_sha256;

pub(crate) struct ModelProviderAttemptEnvelope {
    inner: compatibility::ModelProviderAttemptEnvelope,
    exact_tokenizer_host: Option<Arc<ModelProviderExactTokenizerHost>>,
    exact_tokenization_state: Arc<ModelProviderExactTokenizationState>,
}

impl ModelProviderAttemptEnvelope {
    pub(super) fn attempt_id(&self) -> &str {
        self.inner.attempt_id()
    }

    pub(super) fn base_logical_request_sha256(&self) -> &ModelProviderSha256Digest {
        self.inner.base_logical_request_sha256()
    }

    pub(super) fn thread_id(&self) -> &str {
        self.inner.thread_id()
    }

    pub(super) fn turn_id(&self) -> &str {
        self.inner.turn_id()
    }

    pub(super) fn request_kind(&self) -> ModelProviderRequestKind {
        self.inner.request_kind()
    }

    pub(super) fn provider_id(&self) -> &str {
        self.inner.provider_id()
    }

    pub(super) fn model(&self) -> &str {
        self.inner.model()
    }

    pub(super) fn transport(&self) -> ModelProviderTransport {
        self.inner.transport()
    }

    pub(super) fn generate(&self) -> bool {
        self.inner.generate()
    }

    pub(crate) fn finalize<L: Serialize, W: Serialize>(
        self,
        effective_logical_request: &L,
        effective_wire_semantic: &W,
        ephemeral_input: Option<EphemeralModelInputBinding>,
    ) -> Result<PreparedModelProviderPolicy, ModelProviderPolicyError> {
        let tokenization = match self.exact_tokenizer_host.as_ref() {
            Some(host) => {
                let canonical_final_request = canonical_json_bytes(effective_wire_semantic)?;
                let wire_semantic_sha256 = compatibility::bytes_sha256(&canonical_final_request)?;
                let compatibility_digest =
                    compatibility::canonical_sha256(effective_wire_semantic)?;
                if wire_semantic_sha256 != compatibility_digest {
                    return Err(ModelProviderPolicyError::new(
                        "exact_tokenizer_canonicalization_drift",
                        "exact tokenizer bytes differ from provider wire-semantic canonicalization",
                    ));
                }
                let request = ModelProviderExactTokenizerRequest {
                    schema_version: MODEL_PROVIDER_EXACT_TOKENIZER_SCHEMA_VERSION,
                    attempt_id: self.inner.attempt_id(),
                    provider_id: self.inner.provider_id(),
                    model: self.inner.model(),
                    wire_semantic_sha256: &wire_semantic_sha256,
                    canonical_final_request: &canonical_final_request,
                };
                let receipt = host.tokenize(request)?;
                if receipt.final_request_sha256() != &wire_semantic_sha256
                    || receipt.wire_semantic_sha256() != &wire_semantic_sha256
                {
                    return Err(ModelProviderPolicyError::new(
                        "exact_tokenizer_final_request_digest_mismatch",
                        "exact tokenizer receipt does not match the canonical provider request",
                    ));
                }
                Some(receipt)
            }
            None => None,
        };

        let prepared = self.inner.finalize(
            effective_logical_request,
            effective_wire_semantic,
            ephemeral_input,
        )?;
        if let Some(receipt) = tokenization {
            self.exact_tokenization_state.record(receipt)?;
        }
        Ok(prepared)
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn prepare_model_provider_policy<L: Serialize, W: Serialize>(
    context: &ModelProviderPolicyContext<'_>,
    provider_id: &str,
    model: &str,
    transport: ModelProviderTransport,
    endpoint: &str,
    logical_request: &L,
    wire_semantic: &W,
    previous_response_id: Option<&str>,
    generate: bool,
) -> Result<PreparedModelProviderPolicy, ModelProviderPolicyError> {
    prepare_model_provider_attempt(
        context,
        provider_id,
        model,
        transport,
        endpoint,
        logical_request,
        previous_response_id,
        generate,
    )?
    .finalize(logical_request, wire_semantic, None)
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn prepare_model_provider_attempt<L: Serialize>(
    context: &ModelProviderPolicyContext<'_>,
    provider_id: &str,
    model: &str,
    transport: ModelProviderTransport,
    endpoint: &str,
    base_logical_request: &L,
    previous_response_id: Option<&str>,
    generate: bool,
) -> Result<ModelProviderAttemptEnvelope, ModelProviderPolicyError> {
    let exact_tokenizer_host = exact_tokenizer_host(context);
    let exact_tokenization_state = context
        .turn_store
        .get_or_init(ModelProviderExactTokenizationState::default);
    let inner = compatibility::prepare_model_provider_attempt(
        context,
        provider_id,
        model,
        transport,
        endpoint,
        base_logical_request,
        previous_response_id,
        generate,
    )?;
    Ok(ModelProviderAttemptEnvelope {
        inner,
        exact_tokenizer_host,
        exact_tokenization_state,
    })
}

fn exact_tokenizer_host(
    context: &ModelProviderPolicyContext<'_>,
) -> Option<Arc<ModelProviderExactTokenizerHost>> {
    context
        .turn_store
        .get::<ModelProviderExactTokenizerHost>()
        .or_else(|| {
            context
                .thread_store
                .get::<ModelProviderExactTokenizerHost>()
        })
        .or_else(|| {
            context
                .session_store
                .get::<ModelProviderExactTokenizerHost>()
        })
}

fn canonical_json_bytes<T: Serialize>(
    value: &T,
) -> Result<Vec<u8>, ModelProviderPolicyError> {
    let value = serde_json::to_value(value).map_err(|error| {
        ModelProviderPolicyError::new(
            "exact_tokenizer_serialization_failed",
            format!("failed to serialize provider wire semantics: {error}"),
        )
    })?;
    serde_json::to_vec(&canonicalize_json(value)).map_err(|error| {
        ModelProviderPolicyError::new(
            "exact_tokenizer_serialization_failed",
            format!("failed to encode canonical provider wire semantics: {error}"),
        )
    })
}

fn canonicalize_json(value: Value) -> Value {
    match value {
        Value::Array(values) => Value::Array(values.into_iter().map(canonicalize_json).collect()),
        Value::Object(values) => {
            let mut entries = values.into_iter().collect::<Vec<_>>();
            entries.sort_by(|left, right| left.0.cmp(&right.0));
            Value::Object(
                entries
                    .into_iter()
                    .map(|(key, value)| (key, canonicalize_json(value)))
                    .collect(),
            )
        }
        scalar => scalar,
    }
}
