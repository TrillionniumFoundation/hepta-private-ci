//! Physical provider-attempt observation for prompt delivery.
//!
//! This module deliberately uses the existing model-provider policy seam. Core
//! invokes that seam after the effective provider request is finalized and
//! before the network send, and completes the returned lease with the same
//! physical attempt's terminal observation. The observer never injects prompt
//! bytes and remains inert until an exercise-bound compiler explicitly binds a
//! turn to a compilation.

use std::collections::BTreeMap;
use std::fmt;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyContributor;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderTerminal;
use codex_hepta_types::Digest32;
use codex_hepta_types::PromptDeliveryObservationV1;
use codex_hepta_types::PromptDeliveryRejectReasonV1;
use codex_hepta_types::StableId;

use crate::CodexOperationIntent;
use crate::PromptProviderTerminalObservationV1;
use crate::observe_prompt_delivery_after_admission_v1;
use crate::validate_operation_intent;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptDeliveryTurnBindingV1 {
    pub compilation_id: StableId,
    pub deadline_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptDeliveryProviderResultV1 {
    Observed {
        turn_id: String,
        observation: PromptDeliveryObservationV1,
    },
    Indeterminate {
        turn_id: String,
        compilation_id: StableId,
        provider_request_digest: Digest32,
        reason_code: String,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProviderObserverError {
    InvalidTurn,
    InvalidDeadline,
    BindingConflict,
}

impl fmt::Display for ProviderObserverError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ProviderObserverError {}

#[derive(Default)]
struct ObserverState {
    bindings: BTreeMap<String, PromptDeliveryTurnBindingV1>,
    results: Vec<PromptDeliveryProviderResultV1>,
}

#[derive(Clone, Default)]
pub struct PromptDeliveryProviderObserver {
    state: Arc<Mutex<ObserverState>>,
}

impl fmt::Debug for PromptDeliveryProviderObserver {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        formatter
            .debug_struct("PromptDeliveryProviderObserver")
            .field("bound_turns", &state.bindings.len())
            .field("results", &state.results.len())
            .finish()
    }
}

impl PromptDeliveryProviderObserver {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn bind_turn(
        &self,
        turn_id: impl Into<String>,
        binding: PromptDeliveryTurnBindingV1,
    ) -> Result<(), ProviderObserverError> {
        let turn_id = turn_id.into();
        if turn_id.is_empty() || turn_id.len() > 256 {
            return Err(ProviderObserverError::InvalidTurn);
        }
        if binding.deadline_unix_ms == 0 {
            return Err(ProviderObserverError::InvalidDeadline);
        }
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        match state.bindings.get(&turn_id) {
            Some(existing) if existing == &binding => Ok(()),
            Some(_) => Err(ProviderObserverError::BindingConflict),
            None => {
                state.bindings.insert(turn_id, binding);
                Ok(())
            }
        }
    }

    pub fn unbind_turn(&self, turn_id: &str) -> Option<PromptDeliveryTurnBindingV1> {
        self.state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .bindings
            .remove(turn_id)
    }

    pub fn drain_results(&self) -> Vec<PromptDeliveryProviderResultV1> {
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        std::mem::take(&mut state.results)
    }

    fn binding_for_turn(&self, turn_id: &str) -> Option<PromptDeliveryTurnBindingV1> {
        self.state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .bindings
            .get(turn_id)
            .cloned()
    }

    fn record(&self, result: PromptDeliveryProviderResultV1) {
        self.state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .results
            .push(result);
    }

    fn begin_sync(
        &self,
        input: &ModelProviderInvocationInput<'_>,
    ) -> Result<ModelProviderPolicyDecision, ModelProviderPolicyError> {
        if input.request_kind != ModelProviderRequestKind::Turn {
            return Ok(ModelProviderPolicyDecision::Allow {
                lease: Box::new(PassthroughLease),
            });
        }
        let Some(binding) = self.binding_for_turn(input.turn_id) else {
            return Ok(ModelProviderPolicyDecision::Allow {
                lease: Box::new(PassthroughLease),
            });
        };
        let request_digest = Digest32::from_str(input.wire_semantic_sha256.as_str())
            .map_err(|error| policy_error("invalid_provider_request_digest", error.to_string()))?;
        let operation_id = StableId::new(input.attempt_id.to_owned())
            .map_err(|error| policy_error("invalid_provider_attempt_id", error.to_string()))?;
        let thread_id = StableId::new(input.thread_id.to_owned())
            .map_err(|error| policy_error("invalid_provider_thread_id", error.to_string()))?;
        let method_id = StableId::new("provider:turn")
            .map_err(|error| policy_error("invalid_provider_method_id", error.to_string()))?;
        let intent = CodexOperationIntent {
            operation_id,
            thread_id,
            method_id,
            payload_digest: request_digest,
            lease_payload_digest: request_digest,
            deadline_ms: binding.deadline_unix_ms,
        };
        let now_ms = current_unix_ms()?;
        if let Err(error) = validate_operation_intent(now_ms, &intent) {
            return Ok(ModelProviderPolicyDecision::Block {
                reason_code: "prompt_delivery_binding_expired".to_owned(),
                message: format!("prompt delivery binding is not live: {error}"),
            });
        }
        Ok(ModelProviderPolicyDecision::Allow {
            lease: Box::new(PromptDeliveryAttemptLease {
                observer: self.clone(),
                turn_id: input.turn_id.to_owned(),
                binding,
                intent,
            }),
        })
    }
}

impl ModelProviderPolicyContributor for PromptDeliveryProviderObserver {
    fn begin<'a>(
        &'a self,
        input: ModelProviderInvocationInput<'a>,
    ) -> ModelProviderPolicyFuture<'a, ModelProviderPolicyDecision> {
        let decision = self.begin_sync(&input);
        Box::pin(std::future::ready(decision))
    }
}

struct PassthroughLease;

impl ModelProviderAttemptLease for PassthroughLease {
    fn finish(
        self: Box<Self>,
        _terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(std::future::ready(Ok(())))
    }
}

struct PromptDeliveryAttemptLease {
    observer: PromptDeliveryProviderObserver,
    turn_id: String,
    binding: PromptDeliveryTurnBindingV1,
    intent: CodexOperationIntent,
}

impl PromptDeliveryAttemptLease {
    fn finish_sync(
        self,
        terminal: ModelProviderTerminal,
    ) -> Result<(), ModelProviderPolicyError> {
        match terminal {
            ModelProviderTerminal::Completed { .. } => {
                self.record_terminal(/*delivered*/ true, None)
            }
            ModelProviderTerminal::Rejected { reason_code } => self.record_terminal(
                /*delivered*/ false,
                Some(reject_reason("provider_rejected")?),
            ).map_err(|error| {
                policy_error(
                    "prompt_delivery_rejected_observation_failed",
                    format!("{error}; provider_reason={}", bounded_reason(&reason_code)),
                )
            }),
            ModelProviderTerminal::NotDispatched { reason_code } => self.record_terminal(
                /*delivered*/ false,
                Some(reject_reason("provider_not_dispatched")?),
            ).map_err(|error| {
                policy_error(
                    "prompt_delivery_not_dispatched_observation_failed",
                    format!("{error}; provider_reason={}", bounded_reason(&reason_code)),
                )
            }),
            ModelProviderTerminal::Indeterminate { reason_code, .. } => {
                self.observer.record(PromptDeliveryProviderResultV1::Indeterminate {
                    turn_id: self.turn_id,
                    compilation_id: self.binding.compilation_id,
                    provider_request_digest: self.intent.payload_digest,
                    reason_code: bounded_reason(&reason_code),
                });
                Ok(())
            }
            ModelProviderTerminal::CompletedUnary { .. } => {
                self.observer.record(PromptDeliveryProviderResultV1::Indeterminate {
                    turn_id: self.turn_id,
                    compilation_id: self.binding.compilation_id,
                    provider_request_digest: self.intent.payload_digest,
                    reason_code: "unexpected_unary_terminal".to_owned(),
                });
                Ok(())
            }
        }
    }

    fn record_terminal(
        self,
        delivered: bool,
        rejected_reason: Option<PromptDeliveryRejectReasonV1>,
    ) -> Result<(), ModelProviderPolicyError> {
        let observation = observe_prompt_delivery_after_admission_v1(
            &self.intent,
            self.binding.compilation_id,
            PromptProviderTerminalObservationV1 {
                terminal_observed: true,
                observed_provider_request_digest: self.intent.payload_digest,
                delivered,
                rejected_reason,
                observed_token_positions: None,
                truncation_observed: false,
            },
        )
        .map_err(|error| policy_error("prompt_delivery_observation_failed", error.to_string()))?;
        self.observer.record(PromptDeliveryProviderResultV1::Observed {
            turn_id: self.turn_id,
            observation,
        });
        Ok(())
    }
}

impl ModelProviderAttemptLease for PromptDeliveryAttemptLease {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move { (*self).finish_sync(terminal) })
    }
}

fn reject_reason(value: &str) -> Result<PromptDeliveryRejectReasonV1, ModelProviderPolicyError> {
    let id = StableId::new(value.to_owned())
        .map_err(|error| policy_error("invalid_prompt_delivery_reject_reason", error.to_string()))?;
    PromptDeliveryRejectReasonV1::new(id)
        .map_err(|error| policy_error("invalid_prompt_delivery_reject_reason", error.to_string()))
}

fn bounded_reason(value: &str) -> String {
    const MAX_REASON_BYTES: usize = 256;
    if value.len() <= MAX_REASON_BYTES {
        return value.to_owned();
    }
    let mut end = MAX_REASON_BYTES;
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    value[..end].to_owned()
}

fn current_unix_ms() -> Result<u64, ModelProviderPolicyError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| policy_error("provider_observer_clock_failed", error.to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|error| policy_error("provider_observer_clock_overflow", error.to_string()))
}

fn policy_error(
    reason_code: impl Into<String>,
    detail: impl Into<String>,
) -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(reason_code, detail)
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_extension_api::ExtensionData;
    use codex_extension_api::ModelProviderSha256Digest;
    use codex_extension_api::ModelProviderTransport;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn invocation<'a>(
        session: &'a ExtensionData,
        thread: &'a ExtensionData,
        turn: &'a ExtensionData,
        request_digest: &'a ModelProviderSha256Digest,
    ) -> ModelProviderInvocationInput<'a> {
        ModelProviderInvocationInput {
            schema_version: codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
            session_store: session,
            thread_store: thread,
            turn_store: turn,
            attempt_id: "provider-attempt:v1:00000000-0000-0000-0000-000000000001",
            request_binding_id: "provider-request:v1:test",
            thread_id: "thread:1",
            turn_id: "turn:1",
            request_kind: ModelProviderRequestKind::Turn,
            provider_id: "openai",
            provider_config_sha256: request_digest,
            model: "gpt-test",
            transport: ModelProviderTransport::Http,
            endpoint_sha256: request_digest,
            logical_request_sha256: request_digest,
            wire_semantic_sha256: request_digest,
            ephemeral_input_sha256: None,
            ephemeral_input_witness_sha256: None,
            previous_response_id_sha256: None,
            generate: true,
        }
    }

    #[test]
    fn unbound_turn_is_passthrough() {
        let observer = PromptDeliveryProviderObserver::new();
        let session = ExtensionData::new("session");
        let thread = ExtensionData::new("thread");
        let turn = ExtensionData::new("turn");
        let request_digest = ModelProviderSha256Digest::parse(digest("wire").to_string())
            .unwrap_or_else(|error| panic!("digest: {error:?}"));
        let decision = observer
            .begin_sync(&invocation(&session, &thread, &turn, &request_digest))
            .unwrap_or_else(|error| panic!("begin: {error:?}"));
        assert!(matches!(decision, ModelProviderPolicyDecision::Allow { .. }));
        assert!(observer.drain_results().is_empty());
    }

    #[tokio::test]
    async fn bound_turn_records_exact_wire_digest_only_after_terminal() {
        let observer = PromptDeliveryProviderObserver::new();
        let now = current_unix_ms().unwrap_or_else(|error| panic!("clock: {error:?}"));
        observer
            .bind_turn(
                "turn:1",
                PromptDeliveryTurnBindingV1 {
                    compilation_id: id("compilation:1"),
                    deadline_unix_ms: now + 30_000,
                },
            )
            .unwrap_or_else(|error| panic!("bind: {error:?}"));
        let session = ExtensionData::new("session");
        let thread = ExtensionData::new("thread");
        let turn = ExtensionData::new("turn");
        let wire = digest("wire");
        let request_digest = ModelProviderSha256Digest::parse(wire.to_string())
            .unwrap_or_else(|error| panic!("digest: {error:?}"));
        let decision = observer
            .begin_sync(&invocation(&session, &thread, &turn, &request_digest))
            .unwrap_or_else(|error| panic!("begin: {error:?}"));
        assert!(observer.drain_results().is_empty());
        let ModelProviderPolicyDecision::Allow { lease } = decision else {
            panic!("bound live turn must be allowed");
        };
        lease
            .finish(ModelProviderTerminal::Completed {
                response_id_sha256: request_digest.clone(),
                response_items_sha256: request_digest.clone(),
                token_usage_sha256: request_digest,
                end_turn: Some(true),
            })
            .await
            .unwrap_or_else(|error| panic!("finish: {error:?}"));
        let results = observer.drain_results();
        let [PromptDeliveryProviderResultV1::Observed { observation, .. }] = results.as_slice()
        else {
            panic!("one terminal observation expected");
        };
        assert_eq!(observation.provider_request_digest, wire);
        assert_eq!(observation.compilation_id, id("compilation:1"));
        assert!(observation.delivered);
    }

    #[tokio::test]
    async fn indeterminate_provider_attempt_never_becomes_delivery_success() {
        let observer = PromptDeliveryProviderObserver::new();
        let now = current_unix_ms().unwrap_or_else(|error| panic!("clock: {error:?}"));
        observer
            .bind_turn(
                "turn:1",
                PromptDeliveryTurnBindingV1 {
                    compilation_id: id("compilation:2"),
                    deadline_unix_ms: now + 30_000,
                },
            )
            .unwrap_or_else(|error| panic!("bind: {error:?}"));
        let session = ExtensionData::new("session");
        let thread = ExtensionData::new("thread");
        let turn = ExtensionData::new("turn");
        let wire = digest("wire:indeterminate");
        let request_digest = ModelProviderSha256Digest::parse(wire.to_string())
            .unwrap_or_else(|error| panic!("digest: {error:?}"));
        let decision = observer
            .begin_sync(&invocation(&session, &thread, &turn, &request_digest))
            .unwrap_or_else(|error| panic!("begin: {error:?}"));
        let ModelProviderPolicyDecision::Allow { lease } = decision else {
            panic!("bound live turn must be allowed");
        };
        lease
            .finish(ModelProviderTerminal::Indeterminate {
                reason_code: "connection_lost_after_send".to_owned(),
                partial_response_sha256: None,
            })
            .await
            .unwrap_or_else(|error| panic!("finish: {error:?}"));
        let results = observer.drain_results();
        assert!(matches!(
            results.as_slice(),
            [PromptDeliveryProviderResultV1::Indeterminate { .. }]
        ));
    }
}
