//! Codex owns MRTR input work for the lifetime of the logical outbound request.
//! The budget counts resources only; it does not grant execution authority.

use std::future::Future;
use std::future::poll_fn;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;
use std::time::Duration;

use futures::future::try_join_all;
use rmcp::ErrorData;
use rmcp::RoleClient;
use rmcp::model::CallToolRequestParams;
use rmcp::model::CallToolResponse;
use rmcp::model::CallToolResult;
use rmcp::model::ClientResult;
use rmcp::model::DEFAULT_MRTR_MAX_ROUNDS;
use rmcp::model::GetExtensions;
use rmcp::model::GetMeta;
use rmcp::model::InputRequest;
use rmcp::model::InputRequiredResult;
use rmcp::model::InputResponses;
use rmcp::model::NumberOrString;
use rmcp::model::ReadResourceRequestParams;
use rmcp::model::ReadResourceResponse;
use rmcp::model::ReadResourceResult;
use rmcp::model::ServerRequest;
use rmcp::service::RequestContext;
use rmcp::service::RunningService;
use rmcp::service::Service;
use rmcp::service::ServiceError;
use tokio_util::sync::CancellationToken;

use crate::elicitation_client_service::ElicitationClientService;

const MAX_INPUT_REQUESTS: usize = 64;

enum InputKind {
    Sampling,
    Elicitation,
    Roots,
}

struct OwnerState {
    remaining: usize,
    active: bool,
}

struct OwnerInner {
    state: Mutex<OwnerState>,
    cancellation: CancellationToken,
}

pub(crate) struct InputRequestOwner(Arc<OwnerInner>);

// Retained across retries; never obtained from a remote key or meta.
#[derive(Clone)]
pub(crate) struct InputRequestOwnerRef(Weak<OwnerInner>);

// This private extension is constructed only after a whole batch is reserved.
// Its token is always a descendant of that logical request's cancellation token.
#[derive(Clone)]
pub(crate) struct OwnedInputContext {
    owner: Weak<OwnerInner>,
    cancellation: CancellationToken,
}

impl InputRequestOwner {
    pub(crate) fn new() -> Self {
        Self(Arc::new(OwnerInner {
            state: Mutex::new(OwnerState {
                remaining: MAX_INPUT_REQUESTS,
                active: true,
            }),
            cancellation: CancellationToken::new(),
        }))
    }

    pub(crate) fn reference(&self) -> InputRequestOwnerRef {
        InputRequestOwnerRef(Arc::downgrade(&self.0))
    }
}

impl Drop for InputRequestOwner {
    fn drop(&mut self) {
        self.0
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .active = false;
        self.0.cancellation.cancel();
    }
}

pub(crate) fn inactive_owner() -> ErrorData {
    ErrorData::invalid_request("MCP input request has no active local owner", None)
}

impl InputRequestOwnerRef {
    fn reserve(&self, count: usize) -> Result<OwnedInputContext, ErrorData> {
        let owner = self.0.upgrade().ok_or_else(inactive_owner)?;
        let mut state = owner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if !state.active || owner.cancellation.is_cancelled() {
            return Err(inactive_owner());
        }
        if count > state.remaining {
            return Err(ErrorData::invalid_request(
                "MCP input request budget exceeded (maximum 64 per request)",
                None,
            ));
        }
        state.remaining -= count;
        Ok(OwnedInputContext {
            owner: self.0.clone(),
            cancellation: owner.cancellation.child_token(),
        })
    }
}

impl OwnedInputContext {
    pub(crate) async fn run<T, F, Fut>(
        &self,
        cancellation: CancellationToken,
        callback: F,
    ) -> Result<T, ErrorData>
    where
        F: FnOnce() -> Fut,
        Fut: Future<Output = Result<T, ErrorData>>,
    {
        let mut callback = Some(callback);
        let mut response = None;
        tokio::select! {
            biased;
            _ = self.cancellation.cancelled() => Err(inactive_owner()),
            _ = cancellation.cancelled() => Err(inactive_owner()),
            result = poll_fn(|cx| {
                let Some(owner) = self.owner.upgrade() else {
                    return std::task::Poll::Ready(Err(inactive_owner()));
                };
                // Serialize callback polling with owner teardown, including the
                // first poll that can publish a UI prompt. Teardown also drops
                // the pending callback future and its exact responder guard.
                let state = owner.state.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
                if !state.active || self.cancellation.is_cancelled() || cancellation.is_cancelled() {
                    return std::task::Poll::Ready(Err(inactive_owner()));
                }
                if response.is_none() {
                    let Some(callback) = callback.take() else {
                        return std::task::Poll::Ready(Err(inactive_owner()));
                    };
                    response = Some(Box::pin(callback()));
                }
                let Some(response) = response.as_mut() else {
                    return std::task::Poll::Ready(Err(inactive_owner()));
                };
                response.as_mut().poll(cx)
            }) => result,
        }
    }
}

pub(crate) async fn call_tool(
    service: &RunningService<RoleClient, ElicitationClientService>,
    mut params: CallToolRequestParams,
    owner: &InputRequestOwnerRef,
) -> Result<CallToolResult, ServiceError> {
    let mut state_only_rounds = 0;
    for _ in 0..DEFAULT_MRTR_MAX_ROUNDS {
        match service.peer().call_tool_once(params.clone()).await? {
            CallToolResponse::Complete(result) => return Ok(result),
            CallToolResponse::InputRequired(result) => {
                (params.input_responses, params.request_state) =
                    prepare_retry(service, result, owner, &mut state_only_rounds).await?;
            }
            CallToolResponse::Task(_) => return Err(ServiceError::UnexpectedResponse),
            _ => return Err(ServiceError::UnexpectedResponse),
        }
    }
    Err(ServiceError::InputRequiredRoundsExceeded {
        max_rounds: DEFAULT_MRTR_MAX_ROUNDS,
    })
}

pub(crate) async fn read_resource(
    service: &RunningService<RoleClient, ElicitationClientService>,
    mut params: ReadResourceRequestParams,
    owner: &InputRequestOwnerRef,
) -> Result<ReadResourceResult, ServiceError> {
    let mut state_only_rounds = 0;
    for _ in 0..DEFAULT_MRTR_MAX_ROUNDS {
        match service.peer().read_resource_once(params.clone()).await? {
            ReadResourceResponse::Complete(result) => return Ok(result),
            ReadResourceResponse::InputRequired(result) => {
                (params.input_responses, params.request_state) =
                    prepare_retry(service, result, owner, &mut state_only_rounds).await?;
            }
            _ => return Err(ServiceError::UnexpectedResponse),
        }
    }
    Err(ServiceError::InputRequiredRoundsExceeded {
        max_rounds: DEFAULT_MRTR_MAX_ROUNDS,
    })
}

async fn prepare_retry(
    service: &RunningService<RoleClient, ElicitationClientService>,
    result: InputRequiredResult,
    owner: &InputRequestOwnerRef,
    state_only_rounds: &mut usize,
) -> Result<(Option<InputResponses>, Option<String>), ServiceError> {
    let requests = result.input_requests.unwrap_or_default();
    if requests.is_empty() && result.request_state.is_none() {
        return Err(ServiceError::UnexpectedResponse);
    }
    // Reserve the entire batch before constructing or polling any callback.
    // The owner survives transport/session recovery and never refunds work.
    let batch = owner
        .reserve(requests.len())
        .map_err(ServiceError::McpError)?;
    let had_input_requests = !requests.is_empty();
    let responses = try_join_all(requests.into_iter().map(|(key, request)| {
        let input = OwnedInputContext {
            owner: batch.owner.clone(),
            cancellation: batch.cancellation.child_token(),
        };
        async move {
            let (kind, mut request) = match request {
                InputRequest::CreateMessage(request) => (
                    InputKind::Sampling,
                    ServerRequest::CreateMessageRequest(request),
                ),
                InputRequest::Elicitation(request) => (
                    InputKind::Elicitation,
                    ServerRequest::ElicitRequest(request),
                ),
                InputRequest::ListRoots(request) => {
                    (InputKind::Roots, ServerRequest::ListRootsRequest(request))
                }
                _ => return Err(ServiceError::UnexpectedResponse),
            };
            let mut context = RequestContext::new(
                NumberOrString::String(Arc::from(key.as_str())),
                service.peer().clone(),
            );
            context.meta = std::mem::take(request.get_meta_mut());
            context.extensions = std::mem::take(request.extensions_mut());
            context.extensions.insert(input.clone());
            context.ct = input.cancellation.clone();
            let response = tokio::select! {
                biased;
                _ = input.cancellation.cancelled() => Err(inactive_owner()),
                result = service.service().handle_request(request, context) => result,
            }
            .map_err(ServiceError::McpError)?;
            let response = match (kind, response) {
                (InputKind::Sampling, ClientResult::CreateMessageResult(result)) => {
                    serde_json::to_value(result)
                }
                (InputKind::Elicitation, ClientResult::ElicitResult(result)) => {
                    serde_json::to_value(result)
                }
                (InputKind::Roots, ClientResult::ListRootsResult(result)) => {
                    serde_json::to_value(result)
                }
                _ => return Err(ServiceError::UnexpectedResponse),
            }
            .map_err(|error| {
                ServiceError::McpError(ErrorData::internal_error(error.to_string(), None))
            })?;
            Ok((key, response))
        }
    }))
    .await?;
    if had_input_requests {
        *state_only_rounds = 0;
    } else {
        let millis = (50u64.saturating_mul(1_u64 << (*state_only_rounds).min(3))).min(250);
        tokio::time::sleep(Duration::from_millis(millis)).await;
        *state_only_rounds += 1;
    }
    let responses: InputResponses = responses.into_iter().collect();
    Ok((
        (!responses.is_empty()).then_some(responses),
        result.request_state,
    ))
}

#[cfg(test)]
#[path = "mrtr_tests.rs"]
mod tests;
