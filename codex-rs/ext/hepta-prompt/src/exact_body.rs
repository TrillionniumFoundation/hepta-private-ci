use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::Mutex;
use std::sync::PoisonError;

use codex_api::EncodedRequestBodyObserver;
use codex_api::EncodedRequestTerminal;
use codex_hepta_types::Digest32;

use crate::PromptRuntimeAttachmentV1;
use crate::PromptRuntimeFinalRequestV2;
use crate::PromptRuntimeHost;
use crate::PromptRuntimeHostError;

/// Secret-free binding installed by the provider-policy callback for one
/// physical HTTP attempt before Core renders and observes the exact body.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeExactAttemptV2 {
    pub thread_id: String,
    pub turn_id: String,
    pub attempt_id: String,
    pub request_binding_id: String,
    pub provider_id: String,
    pub model: String,
    pub provider_wire_semantic_digest: Digest32,
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
            if value.is_empty() || value.len() > 256 || value.as_bytes().contains(&0) {
                return Err(PromptRuntimeHostError::new(
                    "prompt_runtime_exact_attempt_invalid",
                    format!("{name} is not a bounded identity"),
                ));
            }
        }
        if self.provider_wire_semantic_digest.is_zero() {
            return Err(PromptRuntimeHostError::new(
                "prompt_runtime_exact_attempt_invalid",
                "provider wire semantic digest is empty",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum ExactBodyPhase {
    Empty,
    Bound(PromptRuntimeExactAttemptV2),
    Proven {
        attempt: PromptRuntimeExactAttemptV2,
        request_digest: Digest32,
    },
}

/// Turn-local observer shared between prompt assembly, provider policy, and the
/// canonical HTTP encoder. A body cannot be observed before an attempt is bound,
/// and a proven physical attempt cannot be replayed without a terminal reset.
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
        if attempt.thread_id != self.attachment.compilation_id.as_str()
            && attempt.model != self.attachment.model
        {
            // Thread identity is not expected to equal compilation identity; the
            // compound condition deliberately rejects only a simultaneous model
            // mismatch while preserving opaque thread identifiers.
            return Err(PromptRuntimeHostError::new(
                "prompt_runtime_exact_attempt_scope_mismatch",
                "attempt model does not match the staged attachment",
            ));
        }
        if attempt.model != self.attachment.model {
            return Err(PromptRuntimeHostError::new(
                "prompt_runtime_exact_attempt_scope_mismatch",
                "attempt model does not match the staged attachment",
            ));
        }
        let mut phase = self.phase.lock().unwrap_or_else(PoisonError::into_inner);
        match &*phase {
            ExactBodyPhase::Empty => {
                *phase = ExactBodyPhase::Bound(attempt);
                Ok(())
            }
            ExactBodyPhase::Bound(existing) if existing == &attempt => Ok(()),
            ExactBodyPhase::Bound(_) | ExactBodyPhase::Proven { .. } => Err(
                PromptRuntimeHostError::new(
                    "prompt_runtime_exact_attempt_conflict",
                    "another physical attempt remains unresolved",
                ),
            ),
        }
    }

    fn bound_attempt(&self) -> Result<PromptRuntimeExactAttemptV2, String> {
        let phase = self.phase.lock().unwrap_or_else(PoisonError::into_inner);
        match &*phase {
            ExactBodyPhase::Bound(attempt) => Ok(attempt.clone()),
            ExactBodyPhase::Empty => {
                Err("exact request body was observed before provider policy binding".to_owned())
            }
            ExactBodyPhase::Proven { .. } => {
                Err("exact request body replayed for an unresolved physical attempt".to_owned())
            }
        }
    }

    fn finish_body(
        &self,
        attempt: &PromptRuntimeExactAttemptV2,
        request_digest: Digest32,
    ) -> Result<(), String> {
        let mut phase = self.phase.lock().unwrap_or_else(PoisonError::into_inner);
        match &*phase {
            ExactBodyPhase::Bound(existing) if existing == attempt => {
                *phase = ExactBodyPhase::Proven {
                    attempt: attempt.clone(),
                    request_digest,
                };
                Ok(())
            }
            _ => Err("exact request binding changed during final proof".to_owned()),
        }
    }

    fn clear_terminal(&self) {
        let mut phase = self.phase.lock().unwrap_or_else(PoisonError::into_inner);
        *phase = ExactBodyPhase::Empty;
    }
}

impl fmt::Debug for PromptRuntimeExactBodyObserver {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptRuntimeExactBodyObserver")
            .field("attachment_digest", &self.attachment.context_attachment_digest)
            .finish_non_exhaustive()
    }
}

impl EncodedRequestBodyObserver for PromptRuntimeExactBodyObserver {
    fn observe_encoded_body<'a>(
        &'a self,
        body: &'a [u8],
    ) -> Pin<Box<dyn Future<Output = Result<(), String>> + Send + 'a>> {
        Box::pin(async move {
            let attempt = self.bound_attempt()?;
            let request_digest = Digest32::of_bytes(body);
            let request = PromptRuntimeFinalRequestV2 {
                attachment: self.attachment.clone(),
                attempt: attempt.clone(),
                canonical_request: body.to_vec(),
            };
            self.host
                .observe_final_request(request)
                .await
                .map_err(|error| error.to_string())?;
            self.finish_body(&attempt, request_digest)
        })
    }

    fn observe_terminal<'a>(
        &'a self,
        _terminal: EncodedRequestTerminal,
    ) -> Pin<Box<dyn Future<Output = Result<(), String>> + Send + 'a>> {
        Box::pin(async move {
            self.clear_terminal();
            Ok(())
        })
    }
}
