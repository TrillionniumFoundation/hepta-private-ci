use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_api::EncodedRequestBodyObserver;
use codex_api::EncodedRequestTerminal;
use codex_api::verify_responses_developer_context;
use codex_hepta_types::Digest32;

use crate::PromptRuntimeAttachmentV1;
use crate::PromptRuntimeFinalRequestV2;
use crate::PromptRuntimeHost;
use crate::PromptRuntimeHostError;
use crate::PromptRuntimeRequestKindV2;
use crate::PromptRuntimeTerminalOutcomeV1;
use crate::PromptRuntimeTransportV2;

/// Complete secret-free binding installed by the provider-policy callback for
/// one physical attempt before Core renders and observes the exact HTTP body.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeExactAttemptV2 {
    pub thread_id: String,
    pub turn_id: String,
    pub attempt_id: String,
    pub request_binding_id: String,
    pub request_kind: PromptRuntimeRequestKindV2,
    pub provider_id: String,
    pub provider_config_digest: Digest32,
    pub model: String,
    pub transport: PromptRuntimeTransportV2,
    pub endpoint_digest: Digest32,
    pub logical_request_digest: Digest32,
    pub provider_wire_semantic_digest: Digest32,
    pub ephemeral_input_digest: Option<Digest32>,
    pub ephemeral_input_witness_digest: Option<Digest32>,
    pub previous_response_id_digest: Option<Digest32>,
    pub generate: bool,
}

impl PromptRuntimeExactAttemptV2 {
    pub fn validate(&self) -> Result<(), PromptRuntimeHostError> {
        for (name, value) in [
            ("thread_id", self.thread_id.as_str()),
            ("turn_id", self.turn_id.as_str()),
            ("attempt_id", self.attempt_id.as_str()),
            ("request_binding_id", self.request_binding_id.as_str()),
            ("provider_id", self.provider_id.as_str()),
            ("model", self.model.as_str()),
        ] {
            if value.is_empty() || value.len() > 512 || value.as_bytes().contains(&0) {
                return Err(PromptRuntimeHostError::new(
                    "prompt_runtime_exact_attempt_invalid",
                    format!("{name} is not a bounded identity"),
                ));
            }
        }
        for (name, digest) in [
            ("provider_config", self.provider_config_digest),
            ("endpoint", self.endpoint_digest),
            ("logical_request", self.logical_request_digest),
            ("provider_wire_semantic", self.provider_wire_semantic_digest),
        ] {
            if digest.is_zero() {
                return Err(PromptRuntimeHostError::new(
                    "prompt_runtime_exact_attempt_invalid",
                    format!("{name} digest is empty"),
                ));
            }
        }
        match (
            self.ephemeral_input_digest,
            self.ephemeral_input_witness_digest,
        ) {
            (Some(input), Some(witness)) if !input.is_zero() && !witness.is_zero() => {}
            (None, None) => {}
            _ => {
                return Err(PromptRuntimeHostError::new(
                    "prompt_runtime_exact_attempt_invalid",
                    "ephemeral input and witness digests must be present together",
                ));
            }
        }
        if self
            .previous_response_id_digest
            .is_some_and(Digest32::is_zero)
        {
            return Err(PromptRuntimeHostError::new(
                "prompt_runtime_exact_attempt_invalid",
                "previous response digest is empty",
            ));
        }
        if self.request_kind != PromptRuntimeRequestKindV2::Turn
            || self.transport != PromptRuntimeTransportV2::Http
            || !self.generate
        {
            return Err(PromptRuntimeHostError::new(
                "prompt_runtime_exact_attempt_invalid",
                "exact context delivery requires a generating HTTP turn",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum ExactBodyPhase {
    Empty,
    Bound(PromptRuntimeExactAttemptV2),
    Proving {
        attempt: PromptRuntimeExactAttemptV2,
        request_digest: Digest32,
    },
    Proven {
        attempt: PromptRuntimeExactAttemptV2,
        request_digest: Digest32,
    },
    Blocked,
}

/// The in-flight claim is made before the first await. Cancellation or host
/// failure cannot roll it back: the owner may already have persisted pre-send.
/// Indeterminate/abandoned observations never authorize another physical send.
pub(crate) struct PromptRuntimeExactBodyObserver {
    host: PromptRuntimeHost,
    attachment: PromptRuntimeAttachmentV1,
    phase: Mutex<ExactBodyPhase>,
}

impl PromptRuntimeExactBodyObserver {
    pub(crate) fn new(host: PromptRuntimeHost, attachment: PromptRuntimeAttachmentV1) -> Self {
        Self {
            host,
            attachment,
            phase: Mutex::new(ExactBodyPhase::Empty),
        }
    }

    pub(crate) fn bind_attempt(
        &self,
        attempt: PromptRuntimeExactAttemptV2,
    ) -> Result<(), PromptRuntimeHostError> {
        attempt.validate()?;
        if attempt.model != self.attachment.model {
            return Err(PromptRuntimeHostError::new(
                "prompt_runtime_exact_attempt_scope_mismatch",
                "attempt model does not match the staged attachment",
            ));
        }
        let mut phase = self.phase.lock().map_err(|_| {
            PromptRuntimeHostError::new("prompt_runtime_exact_state_poisoned", "reopen required")
        })?;
        match &*phase {
            ExactBodyPhase::Empty => {
                *phase = ExactBodyPhase::Bound(attempt);
                Ok(())
            }
            ExactBodyPhase::Bound(existing) if existing == &attempt => Ok(()),
            ExactBodyPhase::Bound(_)
            | ExactBodyPhase::Proving { .. }
            | ExactBodyPhase::Proven { .. }
            | ExactBodyPhase::Blocked => Err(PromptRuntimeHostError::new(
                "prompt_runtime_exact_attempt_conflict",
                "another physical attempt remains unresolved",
            )),
        }
    }

    pub(crate) fn cancel_attempt(&self, attempt: &PromptRuntimeExactAttemptV2) {
        // Only an attempt which has not entered the owner callback can be
        // cancelled locally. A poisoned or in-flight state stays fail-closed.
        if let Ok(mut phase) = self.phase.lock()
            && matches!(&*phase, ExactBodyPhase::Bound(existing) if existing == attempt)
        {
            *phase = ExactBodyPhase::Empty;
        }
    }

    fn begin_body(&self, request_digest: Digest32) -> Result<PromptRuntimeExactAttemptV2, String> {
        let mut phase = self.phase.lock().map_err(|_| "context_state_poisoned")?;
        let ExactBodyPhase::Bound(attempt) = &*phase else {
            return Err("context_attempt_not_available".to_owned());
        };
        let attempt = attempt.clone();
        *phase = ExactBodyPhase::Proving {
            attempt: attempt.clone(),
            request_digest,
        };
        Ok(attempt)
    }

    fn finish_body(
        &self,
        attempt: &PromptRuntimeExactAttemptV2,
        request_digest: Digest32,
    ) -> Result<(), String> {
        let mut phase = self.phase.lock().map_err(|_| "context_state_poisoned")?;
        match &*phase {
            ExactBodyPhase::Proving {
                attempt: existing,
                request_digest: expected,
            } if existing == attempt && *expected == request_digest => {
                *phase = ExactBodyPhase::Proven {
                    attempt: attempt.clone(),
                    request_digest,
                };
                Ok(())
            }
            ExactBodyPhase::Empty
            | ExactBodyPhase::Bound(_)
            | ExactBodyPhase::Proving { .. }
            | ExactBodyPhase::Proven { .. }
            | ExactBodyPhase::Blocked => Err("context_proof_state_changed".to_owned()),
        }
    }

    /// Advance only after the attempt-owning lease has persisted its exact
    /// terminal and compatibility projection. Transport notifications have no
    /// attempt identity and must never release or poison a later attempt.
    pub(crate) fn record_terminal(
        &self,
        attempt: &PromptRuntimeExactAttemptV2,
        outcome: PromptRuntimeTerminalOutcomeV1,
    ) -> Result<(), String> {
        let mut phase = self.phase.lock().map_err(|_| "context_state_poisoned")?;
        let existing = match &*phase {
            ExactBodyPhase::Bound(existing)
            | ExactBodyPhase::Proving {
                attempt: existing, ..
            }
            | ExactBodyPhase::Proven {
                attempt: existing, ..
            } => existing,
            ExactBodyPhase::Empty | ExactBodyPhase::Blocked => {
                return Err("context_terminal_requires_reconciliation".to_owned());
            }
        };
        if existing != attempt {
            return Err("context_terminal_attempt_mismatch".to_owned());
        }
        match outcome {
            PromptRuntimeTerminalOutcomeV1::Indeterminate => {
                *phase = ExactBodyPhase::Blocked;
                Ok(())
            }
            PromptRuntimeTerminalOutcomeV1::Delivered
            | PromptRuntimeTerminalOutcomeV1::Rejected
            | PromptRuntimeTerminalOutcomeV1::NotDispatched => {
                if matches!(&*phase, ExactBodyPhase::Proven { .. })
                    || (outcome == PromptRuntimeTerminalOutcomeV1::NotDispatched
                        && matches!(&*phase, ExactBodyPhase::Bound(_)))
                {
                    *phase = ExactBodyPhase::Empty;
                    Ok(())
                } else {
                    Err("context_terminal_requires_reconciliation".to_owned())
                }
            }
        }
    }
}

impl fmt::Debug for PromptRuntimeExactBodyObserver {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptRuntimeExactBodyObserver")
            .field(
                "attachment_digest",
                &self.attachment.context_attachment_digest,
            )
            .finish_non_exhaustive()
    }
}

fn check_deadline(now_unix_ms: u64, deadline_ms: u64) -> Result<(), String> {
    if now_unix_ms == 0 || deadline_ms == 0 || now_unix_ms >= deadline_ms {
        return Err("context_attachment_expired".to_owned());
    }
    Ok(())
}

fn current_unix_ms() -> Result<u64, String> {
    let duration = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "context_clock_unavailable")?;
    u64::try_from(duration.as_millis()).map_err(|_| "context_clock_unavailable".to_owned())
}

impl EncodedRequestBodyObserver for PromptRuntimeExactBodyObserver {
    fn observe_encoded_body<'a>(
        &'a self,
        body: &'a [u8],
    ) -> Pin<Box<dyn Future<Output = Result<(), String>> + Send + 'a>> {
        Box::pin(async move {
            self.attachment
                .validate()
                .map_err(|_| "context_attachment_invalid")?;
            let [fragment] = self.attachment.developer_fragments.as_slice() else {
                return Err("context_canonical_bundle_required".to_owned());
            };
            if fragment.content_digest != self.attachment.context_payload_digest {
                return Err("context_canonical_bundle_mismatch".to_owned());
            }
            verify_responses_developer_context(body, &self.attachment.model, &fragment.text)
                .map_err(str::to_owned)?;
            check_deadline(current_unix_ms()?, self.attachment.deadline_ms)?;
            let request_digest = Digest32::of_bytes(body);
            let attempt = self.begin_body(request_digest)?;
            let request = PromptRuntimeFinalRequestV2 {
                attachment: self.attachment.clone(),
                attempt: attempt.clone(),
                canonical_request: body.to_vec(),
            };
            self.host
                .observe_final_request(request)
                .await
                .map_err(|_| "context_final_request_rejected".to_owned())?;
            // Tokenization and durable I/O may have crossed the exclusive
            // expiry boundary. Do not release the body in that case. The
            // durable owner must reconcile any claim already recorded.
            check_deadline(current_unix_ms()?, self.attachment.deadline_ms)?;
            self.finish_body(&attempt, request_digest)
        })
    }

    fn observe_terminal<'a>(
        &'a self,
        _terminal: EncodedRequestTerminal,
    ) -> Pin<Box<dyn Future<Output = Result<(), String>> + Send + 'a>> {
        // This API intentionally carries no attempt identity. The same
        // physical provider lease records an identity-bound terminal after
        // durable host acceptance; callbacks here are notification-only.
        Box::pin(async { Ok(()) })
    }
}

#[cfg(test)]
#[path = "exact_body_tests.rs"]
mod tests;
