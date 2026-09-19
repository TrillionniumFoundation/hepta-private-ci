use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderTransport;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::GovernanceMode;
use sha2::Digest;
use sha2::Sha256;

pub const HEPTA_INFERENCE_APP_SERVER_CLIENT_NAME: &str = "hepta-infer-worker";

const REQUEST_DOMAIN: &[u8] = b"hepta.inference.provider-send.request.v1";
const SCOPE_DOMAIN: &[u8] = b"hepta.inference.provider-send.scope.v1";
const PAYLOAD_DOMAIN: &[u8] = b"hepta.inference.provider-send.payload.v1";
const FINAL_USE_SUBJECT: &str = "hepta-provider-control";
const FINAL_USE_DESTINATION: &str = "provider-send";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderFinalUseRequest {
    pub attempt_id: String,
    pub request_binding_id: String,
    pub binding: FinalUseBinding,
}

type ProviderFinalUseFuture =
    Pin<Box<dyn Future<Output = Result<(), ModelProviderPolicyError>> + Send + 'static>>;
type ProviderFinalUseAuthorizeFn =
    dyn Fn(ProviderFinalUseRequest) -> ProviderFinalUseFuture + Send + Sync + 'static;

/// Host-owned authority capability for one exact physical provider send.
///
/// The callback is authority-bearing. The capability id is diagnostic
/// provenance only and is never used to derive an authorization decision.
#[derive(Clone)]
pub struct ProviderFinalUseAuthorizerHost {
    capability_id: Arc<str>,
    authorize: Arc<ProviderFinalUseAuthorizeFn>,
}

impl fmt::Debug for ProviderFinalUseAuthorizerHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProviderFinalUseAuthorizerHost")
            .field("capability_id", &self.capability_id)
            .finish_non_exhaustive()
    }
}

impl PartialEq for ProviderFinalUseAuthorizerHost {
    fn eq(&self, other: &Self) -> bool {
        self.capability_id == other.capability_id && Arc::ptr_eq(&self.authorize, &other.authorize)
    }
}

impl Eq for ProviderFinalUseAuthorizerHost {}

impl ProviderFinalUseAuthorizerHost {
    pub fn from_fn<F, Fut>(capability_id: impl Into<String>, authorize: F) -> Self
    where
        F: Fn(ProviderFinalUseRequest) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<(), ModelProviderPolicyError>> + Send + 'static,
    {
        Self {
            capability_id: Arc::from(capability_id.into()),
            authorize: Arc::new(move |request| Box::pin(authorize(request))),
        }
    }

    pub fn capability_id(&self) -> &str {
        &self.capability_id
    }

    async fn authorize(
        &self,
        request: ProviderFinalUseRequest,
    ) -> Result<(), ModelProviderPolicyError> {
        (self.authorize)(request).await
    }
}

#[derive(Clone)]
pub(crate) struct ProviderFinalUseRequirement {
    request: ProviderFinalUseRequest,
    authorizer: Option<ProviderFinalUseAuthorizerHost>,
    mode: GovernanceMode,
}

impl ProviderFinalUseRequirement {
    pub(crate) async fn authorize(&self) -> Result<(), ModelProviderPolicyError> {
        let result = match self.authorizer.as_ref() {
            Some(authorizer) => authorizer.authorize(self.request.clone()).await,
            None => Err(ModelProviderPolicyError::new(
                "hepta_provider_final_use_unavailable",
                "Hepta generating provider send has no embedding-owned final-use authorizer",
            )),
        };
        match (self.mode, result) {
            (_, Ok(())) => Ok(()),
            (GovernanceMode::Enforce, Err(error)) => Err(error),
            (GovernanceMode::Shadow, Err(error)) => {
                tracing::warn!(
                    reason_code = error.reason_code(),
                    detail = error.detail(),
                    "shadow governance observed provider final-use authorization failure"
                );
                Ok(())
            }
        }
    }
}

/// Every generating physical provider attempt under Hepta governance receives
/// a final-use requirement. App Server client identity is bound into the scope
/// for provenance, but never decides whether authorization is required.
pub(crate) fn provider_final_use_requirement(
    input: &ModelProviderInvocationInput<'_>,
    mode: GovernanceMode,
    authorizer: Option<ProviderFinalUseAuthorizerHost>,
) -> Option<ProviderFinalUseRequirement> {
    if !input.generate {
        return None;
    }
    Some(ProviderFinalUseRequirement {
        request: ProviderFinalUseRequest {
            attempt_id: input.attempt_id.to_string(),
            request_binding_id: input.request_binding_id.to_string(),
            binding: provider_final_use_binding(input),
        },
        authorizer,
        mode,
    })
}

fn provider_final_use_binding(input: &ModelProviderInvocationInput<'_>) -> FinalUseBinding {
    let request_kind = match input.request_kind {
        ModelProviderRequestKind::Turn => "turn",
        ModelProviderRequestKind::Prewarm => "prewarm",
        ModelProviderRequestKind::Compaction => "compaction",
        ModelProviderRequestKind::Memory => "memory",
    };
    let transport = match input.transport {
        ModelProviderTransport::Http => "http",
        ModelProviderTransport::WebSocket => "websocket",
    };
    let client_name = input.app_server_client_name.unwrap_or("<none>");
    let ephemeral = input
        .ephemeral_input_sha256
        .map(|value| value.as_str())
        .unwrap_or("<none>");
    let ephemeral_witness = input
        .ephemeral_input_witness_sha256
        .map(|value| value.as_str())
        .unwrap_or("<none>");
    let previous_response = input
        .previous_response_id_sha256
        .map(|value| value.as_str())
        .unwrap_or("<none>");

    FinalUseBinding {
        subject_id: FINAL_USE_SUBJECT.to_string(),
        destination_id: FINAL_USE_DESTINATION.to_string(),
        request_sha256: digest_parts(
            REQUEST_DOMAIN,
            &[input.attempt_id, input.request_binding_id],
        ),
        scope_sha256: digest_parts(
            SCOPE_DOMAIN,
            &[
                input.thread_id,
                input.turn_id,
                client_name,
                request_kind,
                input.provider_id,
                input.provider_config_sha256.as_str(),
                input.model,
                transport,
                input.endpoint_sha256.as_str(),
            ],
        ),
        payload_sha256: digest_parts(
            PAYLOAD_DOMAIN,
            &[
                input.logical_request_sha256.as_str(),
                input.wire_semantic_sha256.as_str(),
                ephemeral,
                ephemeral_witness,
                previous_response,
                if input.generate { "generate" } else { "no-generate" },
            ],
        ),
    }
}

fn digest_parts(domain: &[u8], parts: &[&str]) -> [u8; 32] {
    let mut digest = Sha256::new();
    digest.update((domain.len() as u64).to_be_bytes());
    digest.update(domain);
    for part in parts {
        digest.update((part.len() as u64).to_be_bytes());
        digest.update(part.as_bytes());
    }
    digest.finalize().into()
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;
    use std::sync::Mutex;

    use codex_extension_api::ExtensionData;
    use codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION;
    use codex_extension_api::ModelProviderSha256Digest;

    use super::*;

    fn digest(byte: char) -> ModelProviderSha256Digest {
        ModelProviderSha256Digest::parse(byte.to_string().repeat(64)).expect("valid digest")
    }

    fn input<'a>(
        session: &'a ExtensionData,
        thread: &'a ExtensionData,
        turn: &'a ExtensionData,
        digests: &'a [ModelProviderSha256Digest; 4],
    ) -> ModelProviderInvocationInput<'a> {
        ModelProviderInvocationInput {
            schema_version: MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
            session_store: session,
            thread_store: thread,
            turn_store: turn,
            attempt_id: "attempt-1",
            request_binding_id: "request-1",
            thread_id: "thread-1",
            turn_id: "turn-1",
            app_server_client_name: Some(HEPTA_INFERENCE_APP_SERVER_CLIENT_NAME),
            request_kind: ModelProviderRequestKind::Turn,
            provider_id: "provider-1",
            provider_config_sha256: &digests[0],
            model: "model-1",
            transport: ModelProviderTransport::Http,
            endpoint_sha256: &digests[1],
            logical_request_sha256: &digests[2],
            wire_semantic_sha256: &digests[3],
            ephemeral_input_sha256: None,
            ephemeral_input_witness_sha256: None,
            previous_response_id_sha256: None,
            generate: true,
        }
    }

    #[test]
    fn exact_binding_changes_with_attempt_and_wire_semantics() {
        let session = ExtensionData::new("session-1");
        let thread = ExtensionData::new("thread-1");
        let turn = ExtensionData::new("turn-1");
        let digests = [digest('a'), digest('b'), digest('c'), digest('d')];
        let base = input(&session, &thread, &turn, &digests);
        let base_binding = provider_final_use_binding(&base);

        let mut different_attempt = input(&session, &thread, &turn, &digests);
        different_attempt.attempt_id = "attempt-2";
        assert_ne!(
            base_binding.request_sha256,
            provider_final_use_binding(&different_attempt).request_sha256
        );

        let changed_wire = digest('e');
        let mut different_wire = input(&session, &thread, &turn, &digests);
        different_wire.wire_semantic_sha256 = &changed_wire;
        assert_ne!(
            base_binding.payload_sha256,
            provider_final_use_binding(&different_wire).payload_sha256
        );
    }

    #[tokio::test]
    async fn enforce_generation_without_host_authorizer_fails_closed() {
        let session = ExtensionData::new("session-1");
        let thread = ExtensionData::new("thread-1");
        let turn = ExtensionData::new("turn-1");
        let digests = [digest('a'), digest('b'), digest('c'), digest('d')];
        let input = input(&session, &thread, &turn, &digests);
        let requirement =
            provider_final_use_requirement(&input, GovernanceMode::Enforce, None)
                .expect("generation requires final use");

        let error = requirement
            .authorize()
            .await
            .expect_err("missing host must fail closed");
        assert_eq!(error.reason_code(), "hepta_provider_final_use_unavailable");
    }

    #[tokio::test]
    async fn final_dispatch_authorizer_receives_exact_bound_request() {
        let session = ExtensionData::new("session-1");
        let thread = ExtensionData::new("thread-1");
        let turn = ExtensionData::new("turn-1");
        let digests = [digest('a'), digest('b'), digest('c'), digest('d')];
        let input = input(&session, &thread, &turn, &digests);
        let expected = ProviderFinalUseRequest {
            attempt_id: input.attempt_id.to_string(),
            request_binding_id: input.request_binding_id.to_string(),
            binding: provider_final_use_binding(&input),
        };
        let seen = Arc::new(Mutex::new(Vec::new()));
        let seen_for_host = Arc::clone(&seen);
        let host = ProviderFinalUseAuthorizerHost::from_fn("test-authorizer", move |request| {
            let seen = Arc::clone(&seen_for_host);
            async move {
                seen.lock().expect("seen lock").push(request);
                Ok(())
            }
        });
        let requirement =
            provider_final_use_requirement(&input, GovernanceMode::Enforce, Some(host))
                .expect("generation requires final use");

        requirement
            .authorize()
            .await
            .expect("exact provider send should be authorized");
        assert_eq!(
            seen.lock().expect("seen lock").as_slice(),
            std::slice::from_ref(&expected)
        );
    }

    #[tokio::test]
    async fn non_generating_attempt_does_not_require_inference_final_use() {
        let session = ExtensionData::new("session-1");
        let thread = ExtensionData::new("thread-1");
        let turn = ExtensionData::new("turn-1");
        let digests = [digest('a'), digest('b'), digest('c'), digest('d')];
        let mut input = input(&session, &thread, &turn, &digests);
        input.generate = false;
        assert!(
            provider_final_use_requirement(&input, GovernanceMode::Enforce, None).is_none()
        );
    }
}
