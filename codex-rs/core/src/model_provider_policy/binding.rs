use std::path::PathBuf;

use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionRegistry;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTransport;
use http::HeaderMap;
use serde::Serialize;
use serde_json::Value;
use sha2::Digest as _;
use sha2::Sha256;
use uuid::Uuid;

use crate::config::Config;

use super::ephemeral_input::EphemeralModelInputBinding;
use super::transport::ProviderRoutingHint;

/// Extension scopes and host identities required to bind one provider send.
///
/// IDs and the selected local cwd are host-resolved; extension stores remain
/// borrowed from Codex's single session/thread/turn lifecycle.
pub(crate) struct ModelProviderPolicyContext<'a> {
    pub(crate) registry: &'a ExtensionRegistry<Config>,
    pub(crate) session_store: &'a ExtensionData,
    pub(crate) thread_store: &'a ExtensionData,
    pub(crate) turn_store: &'a ExtensionData,
    pub(crate) thread_id: String,
    pub(crate) turn_id: String,
    pub(crate) request_kind: ModelProviderRequestKind,
    pub(crate) ephemeral_input_cwd: Option<PathBuf>,
}

/// Base identity and immutable host facts for one physical provider attempt.
///
/// The base logical digest mints the retry-stable request identity before an
/// attempt-local ephemeral input can affect the effective logical or wire
/// semantics.
pub(crate) struct ModelProviderAttemptEnvelope {
    attempt_id: String,
    request_binding_id: String,
    thread_id: String,
    turn_id: String,
    request_kind: ModelProviderRequestKind,
    provider_id: String,
    provider_config_sha256: ModelProviderSha256Digest,
    model: String,
    transport: ModelProviderTransport,
    endpoint_sha256: ModelProviderSha256Digest,
    turn_recovery_endpoint_sha256: Result<ModelProviderSha256Digest, ModelProviderPolicyError>,
    base_logical_request_sha256: ModelProviderSha256Digest,
    previous_response_id_sha256: Option<ModelProviderSha256Digest>,
    generate: bool,
}

impl ModelProviderAttemptEnvelope {
    pub(super) fn attempt_id(&self) -> &str {
        &self.attempt_id
    }

    pub(super) fn base_logical_request_sha256(&self) -> &ModelProviderSha256Digest {
        &self.base_logical_request_sha256
    }

    pub(super) fn thread_id(&self) -> &str {
        &self.thread_id
    }

    pub(super) fn turn_id(&self) -> &str {
        &self.turn_id
    }

    pub(super) fn request_kind(&self) -> ModelProviderRequestKind {
        self.request_kind
    }

    pub(super) fn provider_id(&self) -> &str {
        &self.provider_id
    }

    pub(super) fn model(&self) -> &str {
        &self.model
    }

    pub(super) fn transport(&self) -> ModelProviderTransport {
        self.transport
    }

    pub(super) fn generate(&self) -> bool {
        self.generate
    }

    pub(crate) fn finalize<L: Serialize, W: Serialize>(
        self,
        effective_logical_request: &L,
        effective_wire_semantic: &W,
        ephemeral_input: Option<EphemeralModelInputBinding>,
    ) -> Result<PreparedModelProviderPolicy, ModelProviderPolicyError> {
        let logical_request_sha256 = canonical_sha256(effective_logical_request)?;
        let wire_semantic_sha256 = canonical_sha256(effective_wire_semantic)?;
        if ephemeral_input.is_some() != (logical_request_sha256 != self.base_logical_request_sha256)
        {
            return Err(ModelProviderPolicyError::new(
                "ephemeral_model_input_effective_binding_mismatch",
                "effective logical semantics and ephemeral input presence must change together",
            ));
        }
        let (ephemeral_input_sha256, ephemeral_input_witness_sha256) = match ephemeral_input {
            Some(binding) => {
                let witness = ephemeral_input_witness_sha256(
                    self.attempt_id.as_str(),
                    self.thread_id.as_str(),
                    self.turn_id.as_str(),
                    self.request_binding_id.as_str(),
                    self.transport,
                    &logical_request_sha256,
                    &wire_semantic_sha256,
                    self.previous_response_id_sha256.as_ref(),
                    self.generate,
                    &binding,
                )?;
                (Some(binding.input_sha256().clone()), Some(witness))
            }
            None => (None, None),
        };

        Ok(PreparedModelProviderPolicy {
            attempt_id: self.attempt_id,
            request_binding_id: self.request_binding_id,
            thread_id: self.thread_id,
            turn_id: self.turn_id,
            request_kind: self.request_kind,
            provider_id: self.provider_id,
            provider_config_sha256: self.provider_config_sha256,
            model: self.model,
            transport: self.transport,
            endpoint_sha256: self.endpoint_sha256,
            turn_recovery_endpoint_sha256: self.turn_recovery_endpoint_sha256,
            logical_request_sha256,
            wire_semantic_sha256,
            ephemeral_input_sha256,
            ephemeral_input_witness_sha256,
            previous_response_id_sha256: self.previous_response_id_sha256,
            generate: self.generate,
        })
    }
}

/// Owned, digest-only material for one physical provider send.
///
/// Raw request/provider values are used only while constructing this value and
/// are never exposed across the Extension API seam.
pub(crate) struct PreparedModelProviderPolicy {
    attempt_id: String,
    request_binding_id: String,
    thread_id: String,
    turn_id: String,
    request_kind: ModelProviderRequestKind,
    provider_id: String,
    // Compatibility-named Extension API field. This is deliberately the
    // digest of the stable, secret-free provider selector, never a digest of
    // provider credentials or configuration derived from them.
    provider_config_sha256: ModelProviderSha256Digest,
    model: String,
    transport: ModelProviderTransport,
    endpoint_sha256: ModelProviderSha256Digest,
    turn_recovery_endpoint_sha256: Result<ModelProviderSha256Digest, ModelProviderPolicyError>,
    logical_request_sha256: ModelProviderSha256Digest,
    wire_semantic_sha256: ModelProviderSha256Digest,
    ephemeral_input_sha256: Option<ModelProviderSha256Digest>,
    ephemeral_input_witness_sha256: Option<ModelProviderSha256Digest>,
    previous_response_id_sha256: Option<ModelProviderSha256Digest>,
    generate: bool,
}

impl PreparedModelProviderPolicy {
    /// Retry- and transport-stable semantic identity used to authorize cold
    /// turn recovery. This deliberately excludes attempt IDs, auth material,
    /// trace/timing metadata, endpoint selection, and incremental transport
    /// framing while retaining the finalized effective logical request (which
    /// includes any ephemeral Cognitive/Federation attachment). The provider
    /// deployment identity normalizes HTTP/WebSocket schemes while binding the
    /// secret-free origin/path/query/header selectors that can change the
    /// physical model deployment.
    pub(crate) fn turn_recovery_fingerprint<C: Serialize>(
        &self,
        provider_headers: &HeaderMap,
        beta_features_header: Option<&str>,
        compatibility_projection: &C,
        routing_hint: Option<&ProviderRoutingHint>,
        responses_lite: bool,
    ) -> Result<ModelProviderSha256Digest, ModelProviderPolicyError> {
        let endpoint_sha256 = self
            .turn_recovery_endpoint_sha256
            .as_ref()
            .map_err(Clone::clone)?;
        let headers_sha256 = canonical_turn_recovery_headers_sha256(provider_headers)?;
        let compatibility_sha256 = canonical_sha256(compatibility_projection)?;
        digest_parts_sha256([
            "turn-recovery-request:v3",
            self.thread_id.as_str(),
            self.turn_id.as_str(),
            request_kind_name(self.request_kind),
            self.provider_id.as_str(),
            endpoint_sha256.as_str(),
            headers_sha256.as_str(),
            beta_features_header.map_or("beta-absent", |_| "beta-present"),
            beta_features_header.unwrap_or_default(),
            compatibility_sha256.as_str(),
            routing_hint.map_or("routing-absent", |_| "routing-present"),
            routing_hint.map_or("", ProviderRoutingHint::as_str),
            if responses_lite {
                "responses-lite"
            } else {
                "responses-standard"
            },
            self.model.as_str(),
            self.logical_request_sha256.as_str(),
            if self.generate {
                "generate"
            } else {
                "no-generate"
            },
        ])
    }

    pub(crate) fn invocation_input<'a>(
        &'a self,
        context: &'a ModelProviderPolicyContext<'a>,
    ) -> ModelProviderInvocationInput<'a> {
        ModelProviderInvocationInput {
            schema_version: codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
            session_store: context.session_store,
            thread_store: context.thread_store,
            turn_store: context.turn_store,
            attempt_id: &self.attempt_id,
            request_binding_id: &self.request_binding_id,
            thread_id: &self.thread_id,
            turn_id: &self.turn_id,
            request_kind: self.request_kind,
            provider_id: &self.provider_id,
            provider_config_sha256: &self.provider_config_sha256,
            model: &self.model,
            transport: self.transport,
            endpoint_sha256: &self.endpoint_sha256,
            logical_request_sha256: &self.logical_request_sha256,
            wire_semantic_sha256: &self.wire_semantic_sha256,
            ephemeral_input_sha256: self.ephemeral_input_sha256.as_ref(),
            ephemeral_input_witness_sha256: self.ephemeral_input_witness_sha256.as_ref(),
            previous_response_id_sha256: self.previous_response_id_sha256.as_ref(),
            generate: self.generate,
        }
    }
}

/// Builds the secret-free binding immediately before a provider send.
///
/// `wire_semantic` must include every stable, behavior-affecting wire value
/// outside the encoded request body, including routing-hint header presence and
/// value. Authentication, attestation, trace, timing, and request-ID material
/// must remain excluded.
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
    .finalize(
        logical_request,
        wire_semantic,
        /*ephemeral_input*/ None,
    )
}

/// Freezes retry-stable identity before attempt-local input is resolved.
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
    // Do not hash provider configuration here. It may contain bearer/header/
    // query/retry configuration, so even its digest would make evidence
    // secret-derived and unstable across credential rotation.
    let provider_config_sha256 =
        digest_parts_sha256(["model-provider-logical-selector:v1", provider_id])?;
    let endpoint_sha256 = canonical_endpoint_sha256(endpoint)?;
    let turn_recovery_endpoint_sha256 = canonical_turn_recovery_endpoint_sha256(endpoint);
    let base_logical_request_sha256 = canonical_sha256(base_logical_request)?;
    let previous_response_id_sha256 = previous_response_id
        .map(|value| bytes_sha256(value.as_bytes()))
        .transpose()?;
    let request_binding_digest = digest_parts([
        "model-provider-request:v1",
        context.thread_id.as_str(),
        context.turn_id.as_str(),
        request_kind_name(context.request_kind),
        provider_id,
        model,
        base_logical_request_sha256.as_str(),
        // Host identity is retry-stable across HTTP/WebSocket fallback and
        // incremental/full encodings. Hepta evidence additionally binds the
        // physical transport, wire semantics, endpoint and previous response.
        if generate { "generate" } else { "no-generate" },
    ]);

    Ok(ModelProviderAttemptEnvelope {
        attempt_id: format!("model-provider-attempt:v1:{}", Uuid::new_v4()),
        request_binding_id: format!("model-provider-request:v1:{request_binding_digest}"),
        thread_id: context.thread_id.clone(),
        turn_id: context.turn_id.clone(),
        request_kind: context.request_kind,
        provider_id: provider_id.to_string(),
        provider_config_sha256,
        model: model.to_string(),
        transport,
        endpoint_sha256,
        turn_recovery_endpoint_sha256,
        base_logical_request_sha256,
        previous_response_id_sha256,
        generate,
    })
}

#[allow(clippy::too_many_arguments)]
fn ephemeral_input_witness_sha256(
    attempt_id: &str,
    thread_id: &str,
    turn_id: &str,
    request_binding_id: &str,
    transport: ModelProviderTransport,
    logical_request_sha256: &ModelProviderSha256Digest,
    wire_semantic_sha256: &ModelProviderSha256Digest,
    previous_response_id_sha256: Option<&ModelProviderSha256Digest>,
    generate: bool,
    binding: &EphemeralModelInputBinding,
) -> Result<ModelProviderSha256Digest, ModelProviderPolicyError> {
    let (previous_presence, previous_sha256) = match previous_response_id_sha256 {
        Some(digest) => ("present", digest.as_str()),
        None => ("absent", ""),
    };
    digest_parts_sha256([
        "codex:ephemeral-model-input-witness:v2",
        attempt_id,
        thread_id,
        turn_id,
        request_binding_id,
        transport_name(transport),
        logical_request_sha256.as_str(),
        wire_semantic_sha256.as_str(),
        previous_presence,
        previous_sha256,
        if generate { "generate" } else { "no_generate" },
        binding.authority_sha256().as_str(),
        binding.input_sha256().as_str(),
    ])
}

pub(crate) fn canonical_sha256<T: Serialize>(
    value: &T,
) -> Result<ModelProviderSha256Digest, ModelProviderPolicyError> {
    let value = serde_json::to_value(value).map_err(|error| {
        ModelProviderPolicyError::new(
            "model_provider_policy_serialization_failed",
            format!("failed to serialize provider semantic material: {error}"),
        )
    })?;
    let canonical = canonicalize_json(value);
    let bytes = serde_json::to_vec(&canonical).map_err(|error| {
        ModelProviderPolicyError::new(
            "model_provider_policy_serialization_failed",
            format!("failed to encode provider semantic material: {error}"),
        )
    })?;
    bytes_sha256(&bytes)
}

pub(crate) fn bytes_sha256(
    bytes: &[u8],
) -> Result<ModelProviderSha256Digest, ModelProviderPolicyError> {
    ModelProviderSha256Digest::parse(format!("{:x}", Sha256::digest(bytes)))
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

fn digest_parts<'a>(parts: impl IntoIterator<Item = &'a str>) -> String {
    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update((part.len() as u64).to_be_bytes());
        hasher.update(part.as_bytes());
    }
    format!("{:x}", hasher.finalize())
}

pub(super) fn digest_parts_sha256<'a>(
    parts: impl IntoIterator<Item = &'a str>,
) -> Result<ModelProviderSha256Digest, ModelProviderPolicyError> {
    ModelProviderSha256Digest::parse(digest_parts(parts))
}

/// Digests only the non-secret routing shape of a provider endpoint.
///
/// Query values, URL credentials, and fragments are deliberately excluded.
/// Query names are sorted so map iteration order cannot perturb evidence.
fn canonical_endpoint_sha256(
    endpoint: &str,
) -> Result<ModelProviderSha256Digest, ModelProviderPolicyError> {
    #[derive(Serialize)]
    struct CanonicalEndpoint<'a> {
        schema: &'static str,
        scheme: &'a str,
        host: Option<&'a str>,
        port: Option<u16>,
        path: &'a str,
        query_names: Vec<String>,
    }

    let parsed = url::Url::parse(endpoint).map_err(|error| {
        ModelProviderPolicyError::new(
            "model_provider_policy_invalid_endpoint",
            format!("failed to parse provider endpoint URL: {error}"),
        )
    })?;
    let mut query_names = parsed
        .query_pairs()
        .map(|(name, _value)| name.into_owned())
        .collect::<Vec<_>>();
    query_names.sort();

    canonical_sha256(&CanonicalEndpoint {
        schema: "model-provider-endpoint:v1",
        scheme: parsed.scheme(),
        host: parsed.host_str(),
        port: parsed.port_or_known_default(),
        path: parsed.path(),
        query_names,
    })
}

/// Builds the deployment portion of a cold-recovery fingerprint.
///
/// HTTP and WebSocket schemes are normalized because they are alternate
/// transports to the same deployment. Query values are admitted only for a
/// small, explicit set of behavior selectors; credential values are replaced
/// by a presence marker, and unknown query parameters fail cold recovery
/// rather than hashing material that could be secret.
fn canonical_turn_recovery_endpoint_sha256(
    endpoint: &str,
) -> Result<ModelProviderSha256Digest, ModelProviderPolicyError> {
    #[derive(Serialize)]
    struct CanonicalRecoveryEndpoint {
        schema: &'static str,
        scheme_family: &'static str,
        host: Option<String>,
        port: Option<u16>,
        path: String,
        query: Vec<(String, String)>,
    }

    let parsed = url::Url::parse(endpoint).map_err(|error| {
        ModelProviderPolicyError::new(
            "turn_recovery_invalid_provider_endpoint",
            format!("failed to parse provider endpoint URL: {error}"),
        )
    })?;
    let scheme_family = match parsed.scheme() {
        "http" | "ws" => "http",
        "https" | "wss" => "https",
        scheme => {
            return Err(ModelProviderPolicyError::new(
                "turn_recovery_unsupported_provider_scheme",
                format!("provider endpoint scheme `{scheme}` has no stable recovery identity"),
            ));
        }
    };
    let mut query = Vec::new();
    for (name, value) in parsed.query_pairs() {
        let name = name.to_ascii_lowercase();
        let value = if is_provider_credential_selector(name.as_str()) {
            "credential-present".to_string()
        } else if is_provider_query_behavior_selector(name.as_str()) {
            value.into_owned()
        } else {
            return Err(ModelProviderPolicyError::new(
                "turn_recovery_ambiguous_provider_query",
                format!(
                    "provider query parameter `{name}` is not classified as a secret-free deployment selector"
                ),
            ));
        };
        query.push((name, value));
    }
    query.sort();

    canonical_sha256(&CanonicalRecoveryEndpoint {
        schema: "turn-recovery-provider-endpoint:v1",
        scheme_family,
        host: parsed.host_str().map(|host| host.to_ascii_lowercase()),
        port: parsed.port_or_known_default(),
        path: parsed.path().to_string(),
        query,
    })
}

/// Binds resolved, behavior-selecting provider headers without digesting
/// credentials. Unknown configured headers fail cold recovery because their
/// values could be either secrets or deployment selectors.
fn canonical_turn_recovery_headers_sha256(
    headers: &HeaderMap,
) -> Result<ModelProviderSha256Digest, ModelProviderPolicyError> {
    #[derive(Serialize)]
    struct CanonicalRecoveryHeaders {
        schema: &'static str,
        selectors: Vec<(String, String)>,
    }

    let mut selectors = Vec::new();
    for (name, value) in headers {
        let name = name.as_str().to_ascii_lowercase();
        if is_provider_routine_header(name.as_str()) {
            continue;
        }
        let value = if is_provider_credential_selector(name.as_str()) {
            "credential-present".to_string()
        } else if is_provider_header_behavior_selector(name.as_str()) {
            value
                .to_str()
                .map_err(|error| {
                    ModelProviderPolicyError::new(
                        "turn_recovery_invalid_provider_header",
                        format!("provider header `{name}` is not valid text: {error}"),
                    )
                })?
                .to_string()
        } else {
            return Err(ModelProviderPolicyError::new(
                "turn_recovery_ambiguous_provider_header",
                format!(
                    "provider header `{name}` is not classified as a secret-free deployment selector"
                ),
            ));
        };
        selectors.push((name, value));
    }
    selectors.sort();
    canonical_sha256(&CanonicalRecoveryHeaders {
        schema: "turn-recovery-provider-headers:v1",
        selectors,
    })
}

fn is_provider_credential_selector(name: &str) -> bool {
    let normalized = name.replace(['-', '_'], "");
    matches!(
        normalized.as_str(),
        "authorization"
            | "proxyauthorization"
            | "apikey"
            | "xapikey"
            | "key"
            | "token"
            | "accesstoken"
            | "securitytoken"
            | "xamzsecuritytoken"
            | "credential"
            | "password"
            | "secret"
            | "sig"
            | "signature"
            | "xamzsignature"
            | "cookie"
            | "setcookie"
    ) || normalized.contains("bearertoken")
        || normalized.contains("clientsecret")
}

fn is_provider_query_behavior_selector(name: &str) -> bool {
    matches!(
        name,
        "api-version"
            | "api_version"
            | "version"
            | "deployment"
            | "deployment-id"
            | "deployment_id"
            | "model"
            | "region"
            | "location"
            | "resource"
            | "resource-name"
            | "resource_name"
            | "tenant"
            | "tenant-id"
            | "tenant_id"
            | "project"
            | "organization"
    )
}

fn is_provider_header_behavior_selector(name: &str) -> bool {
    matches!(
        name,
        "openai-organization"
            | "openai-project"
            | "x-openai-organization"
            | "x-openai-project"
            | "azure-openai-deployment"
            | "x-azure-openai-deployment"
            | "x-goog-user-project"
            | "x-openai-region"
            | "x-region"
            | "x-tenant-id"
            | "x-deployment-id"
            | "openai-beta"
            | "x-openai-beta"
            | "version"
            | "anthropic-version"
            | "anthropic-beta"
            | "x-amzn-bedrock-guardrailidentifier"
            | "x-amzn-bedrock-guardrailversion"
            | "x-amzn-bedrock-performanceconfig-latency"
            | "x-amzn-bedrock-trace"
            | "x-amzn-bedrock-guardrailtrace"
    )
}

fn is_provider_routine_header(name: &str) -> bool {
    matches!(
        name,
        "user-agent"
            | "accept"
            | "accept-encoding"
            | "content-type"
            | "content-length"
            | "connection"
            | "host"
            | "cache-control"
            | "pragma"
            | "traceparent"
            | "tracestate"
            | "x-amz-bedrock-mantle-client-agent"
    ) || name.starts_with("x-stainless-")
}

const fn request_kind_name(kind: ModelProviderRequestKind) -> &'static str {
    match kind {
        ModelProviderRequestKind::Turn => "turn",
        ModelProviderRequestKind::Prewarm => "prewarm",
        ModelProviderRequestKind::Compaction => "compaction",
        ModelProviderRequestKind::Memory => "memory",
    }
}

const fn transport_name(transport: ModelProviderTransport) -> &'static str {
    match transport {
        ModelProviderTransport::Http => "http",
        ModelProviderTransport::WebSocket => "web_socket",
    }
}

#[cfg(test)]
#[path = "binding_tests.rs"]
mod tests;
