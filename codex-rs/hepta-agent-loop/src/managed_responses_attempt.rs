//! Cancellation supervision for a caller-admitted provider lease.
//!
//! Mirrors the existing Core provider-attempt ownership contract: a detached
//! supervisor consumes the supplied lease once and retains the original
//! encoded-body observer through both terminal writes, including when the
//! caller is cancelled. It cannot create a lease, permission or dispatch.

use codex_api::EncodedRequestBodyObserver;
use codex_api::EncodedRequestTerminal;
use codex_api::RequestDispatchMetadata;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTerminal;
use codex_hepta_types::Digest32;
use std::sync::Arc;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

use crate::Error;
use crate::ModelRequest;
use crate::ResponsesContinuation;
use crate::ResponsesContinuationOwner;
use crate::Result;
use crate::TurnBinding;

pub(super) struct AttemptOwner {
    commands: mpsc::Sender<TerminalCommand>,
}

struct TerminalCommand {
    policy: ModelProviderTerminal,
    encoded: EncodedRequestTerminal,
    ack: oneshot::Sender<Result<()>>,
}

impl AttemptOwner {
    pub(super) fn new(
        lease: Box<dyn ModelProviderAttemptLease>,
        dispatch: RequestDispatchMetadata,
        observer: Option<Arc<dyn EncodedRequestBodyObserver>>,
    ) -> Self {
        let (commands, mut receiver) = mpsc::channel::<TerminalCommand>(1);
        tokio::spawn(async move {
            let (policy, encoded, ack) = match receiver.recv().await {
                Some(TerminalCommand {
                    policy,
                    encoded,
                    ack,
                }) => (policy, encoded, Some(ack)),
                None => {
                    let (policy, encoded) = unresolved(&dispatch, "native_attempt_owner_dropped");
                    (policy, encoded, None)
                }
            };
            // Both callbacks retain the actual provider observation. A failure
            // in one owner must not prevent the other owner recording it. The
            // caller receives no completion ACK until both writes succeed.
            let policy_result = lease
                .finish(policy)
                .await
                .map_err(|_| Error::Owner("provider lease terminal persistence failed".into()));
            let encoded_result = async {
                let observer =
                    observer.ok_or(Error::Contract("exact encoded request owner absent"))?;
                observer
                    .observe_terminal(encoded)
                    .await
                    .map_err(|_| Error::Owner("encoded request terminal persistence failed".into()))
            }
            .await;
            let result = policy_result.and(encoded_result);
            if result.is_err() {
                tracing::warn!(
                    reason_code = "native_provider_terminal_persistence_failed",
                    "failed to persist all provider terminal observations"
                );
            }
            if let Some(ack) = ack {
                let _ = ack.send(result);
            }
        });
        Self { commands }
    }

    async fn finish(
        self,
        policy: ModelProviderTerminal,
        encoded: EncodedRequestTerminal,
    ) -> Result<()> {
        let (ack, acknowledged) = oneshot::channel();
        self.commands
            .send(TerminalCommand {
                policy,
                encoded,
                ack,
            })
            .await
            .map_err(|_| Error::Owner("provider attempt owner stopped".into()))?;
        acknowledged
            .await
            .map_err(|_| Error::Owner("provider attempt terminal acknowledgment absent".into()))?
    }
}

pub(super) struct CompletionOwner<'a, O> {
    pub(super) continuation_owner: &'a mut O,
    pub(super) attempt: Option<AttemptOwner>,
}

impl<O: ResponsesContinuationOwner> ResponsesContinuationOwner for CompletionOwner<'_, O> {
    async fn retain(
        &mut self,
        binding: &TurnBinding,
        request: &ModelRequest,
        continuation: ResponsesContinuation,
    ) -> Result<Digest32> {
        let response_id = continuation.provider_response_id.clone();
        let terminal = ModelProviderTerminal::Completed {
            response_id_sha256: digest(response_id.as_bytes())?,
            response_items_sha256: canonical_digest(crate::response_items_evidence(
                &continuation.items,
            )?)?,
            token_usage_sha256: canonical_digest(serde_json::json!({
                "token_usage": &continuation.usage,
                "provider_rollout_budget_units": &continuation.provider_rollout_budget_units,
            }))?,
            end_turn: continuation.end_turn,
        };
        // Keep the full provider continuation before emitting any terminal
        // projection. The caller's owner must retain actual usage even if a
        // later loop budget validation rejects the completed output.
        let receipt = self
            .continuation_owner
            .retain(binding, request, continuation)
            .await?;
        if receipt.is_zero() {
            return Err(Error::Contract("continuation owner returned no receipt"));
        }
        self.attempt
            .take()
            .ok_or(Error::Contract("provider lease already finished"))?
            .finish(terminal, EncodedRequestTerminal::Completed { response_id })
            .await?;
        Ok(receipt)
    }
}

impl<O> CompletionOwner<'_, O> {
    pub(super) async fn finish_unresolved(
        &mut self,
        dispatch: &RequestDispatchMetadata,
        reason: &'static str,
    ) -> Result<()> {
        let Some(attempt) = self.attempt.take() else {
            // A terminal pair has already been transferred to the supervisor.
            // Caller cancellation cannot cancel either pending owner write.
            return Ok(());
        };
        let (policy, encoded) = unresolved(dispatch, reason);
        attempt.finish(policy, encoded).await
    }
}

fn unresolved(
    dispatch: &RequestDispatchMetadata,
    reason: &str,
) -> (ModelProviderTerminal, EncodedRequestTerminal) {
    if dispatch.transport_invoked() {
        (
            ModelProviderTerminal::Indeterminate {
                reason_code: reason.to_string(),
                partial_response_sha256: None,
            },
            EncodedRequestTerminal::Indeterminate {
                reason_code: reason.to_string(),
            },
        )
    } else {
        (
            ModelProviderTerminal::NotDispatched {
                reason_code: reason.to_string(),
            },
            EncodedRequestTerminal::Abandoned {
                reason_code: reason.to_string(),
            },
        )
    }
}

fn digest(bytes: &[u8]) -> Result<ModelProviderSha256Digest> {
    ModelProviderSha256Digest::parse(Digest32::of_bytes(bytes).to_string())
        .map_err(|_| Error::Contract("provider terminal digest"))
}

fn canonical_digest(mut value: serde_json::Value) -> Result<ModelProviderSha256Digest> {
    fn sort(value: &mut serde_json::Value) {
        match value {
            serde_json::Value::Object(map) => {
                for item in map.values_mut() {
                    sort(item);
                }
                map.sort_keys();
            }
            serde_json::Value::Array(items) => {
                for item in items {
                    sort(item);
                }
            }
            _ => {}
        }
    }
    sort(&mut value);
    digest(
        &serde_json::to_vec(&value)
            .map_err(|_| Error::Contract("provider terminal serialization"))?,
    )
}

#[cfg(test)]
#[path = "managed_responses_attempt_tests.rs"]
mod tests;
