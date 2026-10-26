//! Managed provider composition for one caller-admitted Responses attempt.
//!
//! Authentication and routing come from the existing provider owner. This
//! adapter creates no credential store, login, turn, policy lease, retry or
//! final-use grant. The optional feature has no Core/App Server dependency.

use codex_api::RawResponsesInput;
use codex_api::RequestDispatchMetadata;
use codex_api::RequestedOutputLimit;
use codex_api::ResponseCapture;
use codex_api::ResponsesApiRequest;
use codex_api::ResponsesClient;
use codex_api::ResponsesOptions;
use codex_extension_api::ModelProviderAttemptLease;
use codex_hepta_types::Digest32;
use codex_http_client::ClientRouteClass;
use codex_http_client::HttpClientFactory;
use codex_http_client::ReqwestTransport;
use codex_login::default_client::create_client_for_sensitive_route;
use codex_model_provider::ProviderAuthScope;
use codex_model_provider::SharedModelProvider;
use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::Error;
use crate::ModelEvent;
use crate::ModelRequest;
use crate::ResponsesBridgeLimits;
use crate::ResponsesBridgeStatus;
use crate::ResponsesContinuationOwner;
use crate::ResponsesFailure;
use crate::ResponsesFailureStage;
use crate::Result;
use crate::TurnBinding;
use crate::forward_responses_stream;

#[path = "managed_responses_attempt.rs"]
mod attempt;

/// Prepared through the caller's existing AuthManager/provider configuration.
/// The endpoint is exposed for that owner's exact admission binding; it must
/// never be logged because configured URLs can contain sensitive material.
pub struct ManagedResponsesClient {
    client: ResponsesClient<ReqwestTransport>,
    endpoint: String,
}

struct OpaqueMode {
    raw_input: Option<RawResponsesInput>,
    output_limit: Option<RequestedOutputLimit>,
}

impl ManagedResponsesClient {
    /// Resolve the same scoped auth and route-aware HTTP transport used by
    /// Core. The caller supplies its installed AgentIdentity policy and shared
    /// session fallback; this function does not select a weaker policy.
    pub async fn from_owner(
        provider: &SharedModelProvider,
        scope: ProviderAuthScope,
        http_factory: &HttpClientFactory,
        setup_timeout: Duration,
        cancellation: &CancellationToken,
    ) -> Result<Self> {
        if setup_timeout.is_zero() {
            return Err(Error::Limit("provider setup deadline"));
        }
        let setup = async {
            // Requiring the installed manager prevents an accidental anonymous
            // or hand-built static-token fallback in this managed entry point.
            let manager = provider
                .auth_manager()
                .ok_or(Error::Contract("managed provider auth owner absent"))?;
            manager.auth().await.ok_or(Error::Contract(
                "managed provider authentication unavailable",
            ))?;
            let api_provider = provider
                .api_provider()
                .await
                .map_err(|_| Error::Owner("provider route resolution failed".into()))?;
            let auth = provider
                .api_auth_for_scope(scope)
                .await
                .map_err(|_| Error::Owner("provider scoped authentication failed".into()))?;
            let endpoint = api_provider.url_for_path("responses");
            let transport =
                create_client_for_sensitive_route(http_factory, &endpoint, ClientRouteClass::Api)
                    .map_err(|_| Error::Owner("provider HTTP route construction failed".into()))?;
            Ok(Self {
                client: ResponsesClient::new(
                    ReqwestTransport::from_http_client(transport),
                    api_provider,
                    auth.auth,
                )
                .with_redacted_response_diagnostics(),
                endpoint,
            })
        };
        tokio::select! {
            biased;
            _ = cancellation.cancelled() => Err(Error::Owner("provider setup cancelled".into())),
            result = tokio::time::timeout(setup_timeout, setup) => {
                result.map_err(|_| Error::Limit("provider setup deadline"))?
            }
        }
    }

    pub fn endpoint_for_admission(&self) -> &str {
        &self.endpoint
    }

    /// Consume a prepared client for exactly one transport attempt. A retry
    /// requires a new owner admission; this method never performs one itself.
    pub async fn stream_admitted<O: ResponsesContinuationOwner>(
        self,
        attempt: ManagedResponsesAttempt<'_>,
        owner: &mut O,
        events: mpsc::Sender<Result<ModelEvent>>,
        cancellation: &CancellationToken,
    ) -> Result<ManagedResponsesObservation> {
        self.stream_admitted_mode(attempt, owner, events, cancellation, None)
            .await
    }

    /// Opt-in raw completed-item/terminal retention. The same original owner
    /// must implement retain_opaque and bind any raw replay input to its exact
    /// encoded-body admission. No provider-capability claim is implied.
    pub async fn stream_admitted_opaque<O: ResponsesContinuationOwner>(
        self,
        attempt: ManagedResponsesAttempt<'_>,
        raw_input: Option<RawResponsesInput>,
        owner: &mut O,
        events: mpsc::Sender<Result<ModelEvent>>,
        cancellation: &CancellationToken,
    ) -> Result<ManagedResponsesObservation> {
        self.stream_admitted_mode(
            attempt,
            owner,
            events,
            cancellation,
            Some(OpaqueMode {
                raw_input,
                output_limit: None,
            }),
        )
        .await
    }

    /// Explicit fresh qualification attempt requesting a provider output cap.
    /// This is not evidence of backend support. The complete final capped body
    /// must be admitted by the same original owner before this method is called.
    pub async fn stream_admitted_bounded_opaque<O: ResponsesContinuationOwner>(
        self,
        attempt: ManagedResponsesAttempt<'_>,
        raw_input: Option<RawResponsesInput>,
        output_limit: RequestedOutputLimit,
        owner: &mut O,
        events: mpsc::Sender<Result<ModelEvent>>,
        cancellation: &CancellationToken,
    ) -> Result<ManagedResponsesObservation> {
        self.stream_admitted_mode(
            attempt,
            owner,
            events,
            cancellation,
            Some(OpaqueMode {
                raw_input,
                output_limit: Some(output_limit),
            }),
        )
        .await
    }

    async fn stream_admitted_mode<O: ResponsesContinuationOwner>(
        self,
        attempt: ManagedResponsesAttempt<'_>,
        owner: &mut O,
        events: mpsc::Sender<Result<ModelEvent>>,
        cancellation: &CancellationToken,
        opaque_mode: Option<OpaqueMode>,
    ) -> Result<ManagedResponsesObservation> {
        let ManagedResponsesAttempt {
            binding,
            request,
            expected_model,
            api_request,
            options,
            dispatch,
            lease,
            maximum_elapsed,
            terminal_timeout,
            bridge_limits,
        } = attempt;
        // Supervise the caller's real lease before any validation/await so an
        // aborted task cannot silently lose an admitted physical attempt.
        let lease_owner = attempt::AttemptOwner::new(
            lease,
            dispatch.clone(),
            options.encoded_body_observer.clone(),
        );
        let capture = opaque_mode.as_ref().map(|_| {
            Arc::new(ResponseCapture::new(
                bridge_limits.maximum_items,
                bridge_limits.maximum_retained_bytes,
            ))
        });
        let mut completion = attempt::CompletionOwner {
            continuation_owner: owner,
            attempt: Some(lease_owner),
            opaque_capture: capture.clone(),
        };
        let result = async {
            let bounded_valid = opaque_mode
                .as_ref()
                .and_then(|mode| mode.output_limit)
                .is_none_or(|limit| {
                    limit.tokens() == request.maximum_output_tokens
                        && completion
                            .continuation_owner
                            .supports_incomplete_retention()
                });
            if !bounded_valid
                || (opaque_mode.is_some()
                    && !completion.continuation_owner.supports_opaque_retention())
                || options.encoded_body_observer.is_none()
                || binding.admission_digest.is_zero()
                || request.context_digest != Digest32::of_bytes(request.payload.as_bytes())
                || request.maximum_output_tokens == 0
                || request.maximum_provider_input_tokens < request.input_tokens
                || expected_model.is_empty()
                || api_request.model != expected_model
                || !api_request.stream
                || api_request.store
                || dispatch.transport_invoked()
                || maximum_elapsed.is_zero()
                || terminal_timeout.is_zero()
                || bridge_limits.maximum_items == 0
                || bridge_limits.maximum_retained_bytes == 0
                || bridge_limits.maximum_visible_bytes == 0
            {
                return Err(Error::Contract("prepared managed Responses attempt"));
            }
            let now = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|_| Error::Contract("system clock"))?
                .as_millis();
            let remaining = u128::from(binding.deadline_unix_ms).saturating_sub(now);
            let remaining = Duration::from_millis(u64::try_from(remaining).unwrap_or(u64::MAX));
            if remaining.is_zero() {
                return Ok(ResponsesBridgeStatus::LocalCancellation);
            }
            let execute = async {
                let stream = match (capture, opaque_mode) {
                    (
                        Some(capture),
                        Some(OpaqueMode {
                            raw_input,
                            output_limit: Some(limit),
                        }),
                    ) => {
                        self.client
                            .stream_request_single_attempt_capped(
                                api_request,
                                options,
                                dispatch.clone(),
                                capture,
                                raw_input,
                                limit,
                            )
                            .await
                    }
                    (
                        Some(capture),
                        Some(OpaqueMode {
                            raw_input,
                            output_limit: None,
                        }),
                    ) => {
                        self.client
                            .stream_request_single_attempt_captured(
                                api_request,
                                options,
                                dispatch.clone(),
                                capture,
                                raw_input,
                            )
                            .await
                    }
                    (None, None) => {
                        self.client
                            .stream_request_single_attempt(api_request, options, dispatch.clone())
                            .await
                    }
                    _ => return Err(Error::Contract("prepared Responses capture mode mismatch")),
                }
                .map_err(|error| {
                    Error::Responses(ResponsesFailure::from_api(
                        ResponsesFailureStage::Request,
                        &error,
                    ))
                })?;
                forward_responses_stream(
                    binding,
                    request,
                    stream,
                    &mut completion,
                    events,
                    bridge_limits,
                    cancellation,
                )
                .await
            };
            tokio::select! {
                biased;
                _ = cancellation.cancelled() => Ok(ResponsesBridgeStatus::LocalCancellation),
                result = tokio::time::timeout(maximum_elapsed.min(remaining), execute) => {
                    result.unwrap_or(Ok(ResponsesBridgeStatus::LocalCancellation))
                }
            }
        }
        .await;
        if !matches!(result, Ok(ResponsesBridgeStatus::Completed)) {
            tokio::time::timeout(terminal_timeout, async {
                let retention = completion.retain_incomplete(binding, request).await;
                let partial = retention.as_ref().ok().copied().flatten();
                let reason = if partial.is_some() {
                    "native_provider_incomplete_retained"
                } else {
                    "native_response_unresolved"
                };
                // Even a failed private retention must leave both original
                // terminal owners conservative, never an unrecorded send.
                completion
                    .finish_unresolved(&dispatch, reason, partial)
                    .await?;
                retention.map(|_| ())
            })
            .await
            .map_err(|_| Error::Owner("provider terminal acknowledgment deadline".into()))??;
        }
        result.map(|status| ManagedResponsesObservation {
            status,
            transport_invoked: dispatch.transport_invoked(),
        })
    }
}

/// Everything here is supplied by the existing authenticated inference owner.
/// A transport witness and body observer alone do not authorize a send: the
/// opaque policy lease must come from that owner's actual admission path.
/// The owner must bind that lease and the exact encoded observer to this
/// compiled context, complete API payload, provider route, model and auth
/// scope. The adapter cannot inspect an opaque lease to establish this binding.
pub struct ManagedResponsesAttempt<'a> {
    pub binding: &'a TurnBinding,
    pub request: &'a ModelRequest,
    pub expected_model: &'a str,
    pub api_request: ResponsesApiRequest,
    pub options: ResponsesOptions,
    pub dispatch: RequestDispatchMetadata,
    pub lease: Box<dyn ModelProviderAttemptLease>,
    pub maximum_elapsed: Duration,
    pub terminal_timeout: Duration,
    pub bridge_limits: ResponsesBridgeLimits,
}

/// Provider terminal status is distinct from local cancellation. The request's
/// input/output reservations are local accounting bounds, not wire-level hard
/// token caps: the current ResponsesApiRequest has no maximum_output_tokens.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ManagedResponsesObservation {
    pub status: ResponsesBridgeStatus,
    pub transport_invoked: bool,
}

#[cfg(test)]
#[path = "managed_responses_error_tests.rs"]
mod error_tests;

#[cfg(test)]
#[path = "managed_responses_opaque_tests.rs"]
mod opaque_tests;

#[cfg(test)]
#[path = "managed_responses_budget_tests.rs"]
mod budget_tests;
