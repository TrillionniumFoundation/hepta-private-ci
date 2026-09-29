#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, value: str) -> None:
    (ROOT / path).write_text(value)


def replace_once(path: str, old: str, new: str) -> None:
    value = read(path)
    count = value.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact match, found {count}: {old[:120]!r}")
    write(path, value.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str, flags: int = 0) -> None:
    value = read(path)
    updated, count = re.subn(pattern, replacement, value, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"{path}: expected one regex match, found {count}: {pattern[:120]!r}")
    write(path, updated)


# ---------------------------------------------------------------------------
# Extension API: add a secret-free, sequence-bound output authorization seam.
# Existing contributors remain source-compatible through the default Allow.
# ---------------------------------------------------------------------------
path = "codex-rs/ext/extension-api/src/contributors/model_provider_policy.rs"
replace_once(
    path,
    """pub enum ModelProviderTerminal {
    Completed {
        response_id_sha256: ModelProviderSha256Digest,
        response_items_sha256: ModelProviderSha256Digest,
        token_usage_sha256: ModelProviderSha256Digest,
        /// Exact provider observation. `None` means the provider omitted the field.
        end_turn: Option<bool>,
    },
    /// Successful unary provider operation with no response id or token usage.
    ///
    /// This is used by endpoints such as remote compaction that return only
    /// response items. Missing fields must not be replaced with synthetic digests.
    CompletedUnary {
        response_items_sha256: ModelProviderSha256Digest,
    },
    Rejected {
        reason_code: String,
    },
    NotDispatched {
        reason_code: String,
    },
    Indeterminate {
        reason_code: String,
        partial_response_sha256: Option<ModelProviderSha256Digest>,
    },
}

/// Opaque, single-use capability for completing one admitted provider attempt.
""",
    """pub enum ModelProviderTerminal {
    Completed {
        response_id_sha256: ModelProviderSha256Digest,
        response_items_sha256: ModelProviderSha256Digest,
        token_usage_sha256: ModelProviderSha256Digest,
        /// Exact provider observation. `None` means the provider omitted the field.
        end_turn: Option<bool>,
    },
    /// Successful unary provider operation with no response id or token usage.
    ///
    /// This is used by endpoints such as remote compaction that return only
    /// response items. Missing fields must not be replaced with synthetic digests.
    CompletedUnary {
        response_items_sha256: ModelProviderSha256Digest,
    },
    Rejected {
        reason_code: String,
    },
    NotDispatched {
        reason_code: String,
    },
    Indeterminate {
        reason_code: String,
        partial_response_sha256: Option<ModelProviderSha256Digest>,
    },
}

/// Secret-free identity of one provider event immediately before Core exposes
/// it to a downstream response-stream consumer.
///
/// The digest is over the versioned, canonical event representation. Raw model
/// output never crosses the extension boundary. `sequence` is strictly
/// monotonic for one physical attempt, including events a policy drops.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelProviderOutputBatch {
    pub sequence: u64,
    pub event_sha256: ModelProviderSha256Digest,
    pub encoded_bytes: u64,
}

impl ModelProviderOutputBatch {
    pub fn validate(&self) -> Result<(), ModelProviderPolicyError> {
        if self.sequence == 0 || self.encoded_bytes == 0 {
            return Err(ModelProviderPolicyError::new(
                "model_provider_output_batch_invalid",
                "provider output batches require non-zero sequence and encoded size",
            ));
        }
        Ok(())
    }
}

/// Per-event release decision. A drop is a truthful local-output fact; it does
/// not claim that the provider request was cancelled or that earlier bytes were
/// unobserved.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ModelProviderOutputDecision {
    Allow,
    Drop {
        reason_code: String,
        message: String,
    },
}

/// Opaque, single-use capability for completing one admitted provider attempt.
""",
)
replace_once(
    path,
    """pub trait ModelProviderAttemptLease: Send {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()>;
}
""",
    """pub trait ModelProviderAttemptLease: Send {
    /// Revalidate one exact event before it becomes observable outside Core.
    ///
    /// The default preserves compatibility for policies that do not own an
    /// output-currentness contract. Security-sensitive contributors override
    /// this method and fail closed.
    fn authorize_output<'a>(
        &'a mut self,
        batch: ModelProviderOutputBatch,
    ) -> ModelProviderPolicyFuture<'a, ModelProviderOutputDecision> {
        Box::pin(async move {
            batch.validate()?;
            Ok(ModelProviderOutputDecision::Allow)
        })
    }

    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()>;
}
""",
)

# ---------------------------------------------------------------------------
# Composite policy supervisor: every acquired lease sees each output batch.
# Any Drop wins; any callback failure fails closed.
# ---------------------------------------------------------------------------
path = "codex-rs/core/src/model_provider_policy/lifecycle.rs"
replace_once(
    path,
    "use codex_extension_api::ModelProviderInvocationInput;\n",
    "use codex_extension_api::ModelProviderInvocationInput;\nuse codex_extension_api::ModelProviderOutputBatch;\nuse codex_extension_api::ModelProviderOutputDecision;\n",
)
replace_once(
    path,
    """impl ModelProviderAttemptLease for CompositeModelProviderAttemptLease {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(
            self.supervisor
                .finish(terminal, "model_provider_policy_terminal_failed"),
        )
    }
}
""",
    """impl ModelProviderAttemptLease for CompositeModelProviderAttemptLease {
    fn authorize_output<'a>(
        &'a mut self,
        batch: ModelProviderOutputBatch,
    ) -> ModelProviderPolicyFuture<'a, ModelProviderOutputDecision> {
        Box::pin(self.supervisor.authorize_output(batch))
    }

    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(
            self.supervisor
                .finish(terminal, "model_provider_policy_terminal_failed"),
        )
    }
}
""",
)
replace_once(
    path,
    """    async fn finish(
        self,
        terminal: ModelProviderTerminal,
        aggregate_reason_code: &'static str,
    ) -> Result<(), ModelProviderPolicyError> {
""",
    """    async fn authorize_output(
        &self,
        batch: ModelProviderOutputBatch,
    ) -> Result<ModelProviderOutputDecision, ModelProviderPolicyError> {
        batch.validate()?;
        let (acknowledge, acknowledged) = oneshot::channel();
        self.commands
            .send(LeaseCommand::AuthorizeOutput { batch, acknowledge })
            .map_err(|_| {
                ModelProviderPolicyError::new(
                    "model_provider_policy_lease_supervisor_stopped",
                    "provider policy lease supervisor stopped before output authorization",
                )
            })?;
        acknowledged.await.map_err(|_| {
            ModelProviderPolicyError::new(
                "model_provider_policy_lease_supervisor_stopped",
                "provider policy lease supervisor stopped before acknowledging output authorization",
            )
        })?
    }

    async fn finish(
        self,
        terminal: ModelProviderTerminal,
        aggregate_reason_code: &'static str,
    ) -> Result<(), ModelProviderPolicyError> {
""",
)
replace_once(
    path,
    """enum LeaseCommand {
    Add(Box<dyn ModelProviderAttemptLease>),
    Finish {
""",
    """enum LeaseCommand {
    Add(Box<dyn ModelProviderAttemptLease>),
    AuthorizeOutput {
        batch: ModelProviderOutputBatch,
        acknowledge: oneshot::Sender<
            Result<ModelProviderOutputDecision, ModelProviderPolicyError>,
        >,
    },
    Finish {
""",
)
replace_once(
    path,
    """        match command {
            LeaseCommand::Add(lease) => leases.push(lease),
            LeaseCommand::Finish {
""",
    """        match command {
            LeaseCommand::Add(lease) => leases.push(lease),
            LeaseCommand::AuthorizeOutput { batch, acknowledge } => {
                let _ = acknowledge.send(authorize_output_leases(&mut leases, batch).await);
            }
            LeaseCommand::Finish {
""",
)
replace_once(
    path,
    """async fn finish_leases(
    leases: Vec<Box<dyn ModelProviderAttemptLease>>,
""",
    """async fn authorize_output_leases(
    leases: &mut [Box<dyn ModelProviderAttemptLease>],
    batch: ModelProviderOutputBatch,
) -> Result<ModelProviderOutputDecision, ModelProviderPolicyError> {
    let mut first_drop = None;
    for lease in leases {
        match lease.authorize_output(batch.clone()).await? {
            ModelProviderOutputDecision::Allow => {}
            decision @ ModelProviderOutputDecision::Drop { .. } => {
                if first_drop.is_none() {
                    first_drop = Some(decision);
                }
            }
        }
    }
    Ok(first_drop.unwrap_or(ModelProviderOutputDecision::Allow))
}

async fn finish_leases(
    leases: Vec<Box<dyn ModelProviderAttemptLease>>,
""",
)

# ---------------------------------------------------------------------------
# Cancellation-safe attempt owner: retain the lease across arbitrarily many
# output authorizations, then finish exactly once.
# ---------------------------------------------------------------------------
path = "codex-rs/core/src/model_provider_policy/attempt_owner.rs"
replace_once(
    path,
    "use codex_extension_api::ModelProviderPolicyError;\n",
    "use codex_extension_api::ModelProviderOutputBatch;\nuse codex_extension_api::ModelProviderOutputDecision;\nuse codex_extension_api::ModelProviderPolicyError;\n",
)
replace_once(
    path,
    """    pub(crate) async fn finish(
        self,
        terminal: ModelProviderTerminal,
    ) -> Result<(), ModelProviderPolicyError> {
""",
    """    pub(crate) async fn authorize_output(
        &self,
        batch: ModelProviderOutputBatch,
    ) -> Result<ModelProviderOutputDecision, ModelProviderPolicyError> {
        batch.validate()?;
        let (acknowledge, acknowledged) = oneshot::channel();
        self.commands
            .send(OwnerCommand::AuthorizeOutput { batch, acknowledge })
            .map_err(|_| owner_stopped_error())?;
        acknowledged.await.map_err(|_| owner_stopped_error())?
    }

    pub(crate) async fn finish(
        self,
        terminal: ModelProviderTerminal,
    ) -> Result<(), ModelProviderPolicyError> {
""",
)
replace_once(
    path,
    """enum OwnerCommand {
    Finish {
""",
    """enum OwnerCommand {
    AuthorizeOutput {
        batch: ModelProviderOutputBatch,
        acknowledge: oneshot::Sender<
            Result<ModelProviderOutputDecision, ModelProviderPolicyError>,
        >,
    },
    Finish {
""",
)
regex_once(
    path,
    r"async fn run_owner\(\n    lease: Box<dyn ModelProviderAttemptLease>,\n    dispatch_probe: Box<dyn Fn\(\) -> bool \+ Send \+ 'static>,\n    mut commands: mpsc::UnboundedReceiver<OwnerCommand>,\n\) \{\n.*?\n\}\n\nfn owner_stopped_error",
    """async fn run_owner(
    mut lease: Box<dyn ModelProviderAttemptLease>,
    dispatch_probe: Box<dyn Fn() -> bool + Send + 'static>,
    mut commands: mpsc::UnboundedReceiver<OwnerCommand>,
) {
    while let Some(command) = commands.recv().await {
        match command {
            OwnerCommand::AuthorizeOutput { batch, acknowledge } => {
                let _ = acknowledge.send(lease.authorize_output(batch).await);
            }
            OwnerCommand::Finish {
                terminal,
                acknowledge,
            } => {
                let _ = acknowledge.send(lease.finish(terminal).await);
                return;
            }
        }
    }

    let terminal = if dispatch_probe() {
        ModelProviderTerminal::Indeterminate {
            reason_code: OWNER_DROPPED_AFTER_DISPATCH.to_string(),
            partial_response_sha256: None,
        }
    } else {
        ModelProviderTerminal::NotDispatched {
            reason_code: OWNER_DROPPED_BEFORE_DISPATCH.to_string(),
        }
    };
    if let Err(error) = lease.finish(terminal).await {
        tracing::warn!(
            reason_code = error.reason_code(),
            detail = error.detail(),
            "failed to persist provider terminal after owner cancellation"
        );
    }
}

fn owner_stopped_error""",
    flags=re.S,
)

# ---------------------------------------------------------------------------
# Response terminal owns the exact monotonically increasing output sequence and
# remembers the first durable Drop for final consumer reporting.
# ---------------------------------------------------------------------------
path = "codex-rs/core/src/model_provider_policy/response_terminal.rs"
replace_once(
    path,
    "use codex_extension_api::ModelProviderPolicyError;\n",
    "use codex_extension_api::ModelProviderOutputBatch;\nuse codex_extension_api::ModelProviderOutputDecision;\nuse codex_extension_api::ModelProviderPolicyError;\nuse codex_extension_api::ModelProviderSha256Digest;\n",
)
replace_once(
    path,
    """pub(crate) struct ProviderResponseTerminal {
    state: TerminalState,
}
""",
    """pub(crate) struct ProviderResponseTerminal {
    state: TerminalState,
    next_output_sequence: u64,
    output_fence: Option<(String, String)>,
}
""",
)
replace_once(
    path,
    """        Self {
            state: match owner {
                Some(owner) => TerminalState::Pending(owner),
                None => TerminalState::Inactive,
            },
        }
""",
    """        Self {
            state: match owner {
                Some(owner) => TerminalState::Pending(owner),
                None => TerminalState::Inactive,
            },
            next_output_sequence: 1,
            output_fence: None,
        }
""",
)
replace_once(
    path,
    """    pub(crate) fn is_pending(&self) -> bool {
        matches!(self.state, TerminalState::Pending(_))
    }

    pub(crate) async fn finish_completed<T: Serialize>(
""",
    """    pub(crate) fn is_pending(&self) -> bool {
        matches!(self.state, TerminalState::Pending(_))
    }

    pub(crate) fn output_fence(&self) -> Option<(&str, &str)> {
        self.output_fence
            .as_ref()
            .map(|(reason_code, message)| (reason_code.as_str(), message.as_str()))
    }

    pub(crate) async fn authorize_output(
        &mut self,
        event_sha256: ModelProviderSha256Digest,
        encoded_bytes: u64,
    ) -> Result<ModelProviderOutputDecision, ModelProviderPolicyError> {
        let sequence = self.next_output_sequence;
        let batch = ModelProviderOutputBatch {
            sequence,
            event_sha256,
            encoded_bytes,
        };
        batch.validate()?;
        let decision = match &self.state {
            TerminalState::Inactive => ModelProviderOutputDecision::Allow,
            TerminalState::Pending(owner) => owner.authorize_output(batch).await?,
            TerminalState::Committed => return Err(already_finished_error()),
            TerminalState::CommitFailed => return Err(commit_failed_error()),
        };
        self.next_output_sequence = self
            .next_output_sequence
            .checked_add(1)
            .ok_or_else(|| {
                ModelProviderPolicyError::new(
                    "model_provider_output_sequence_overflow",
                    "provider output sequence exhausted",
                )
            })?;
        if let ModelProviderOutputDecision::Drop {
            reason_code,
            message,
        } = &decision
            && self.output_fence.is_none()
        {
            self.output_fence = Some((reason_code.clone(), message.clone()));
        }
        Ok(decision)
    }

    pub(crate) async fn finish_completed<T: Serialize>(
""",
)

# ---------------------------------------------------------------------------
# Canonical event serialization and the actual release fence in Core.
# ---------------------------------------------------------------------------
path = "codex-rs/codex-api/src/common.rs"
replace_once(path, "#[derive(Debug)]\npub enum ResponseEvent", "#[derive(Debug, Serialize)]\npub enum ResponseEvent")
replace_once(
    path,
    "#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]\npub struct SafetyBuffering",
    "#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]\npub struct SafetyBuffering",
)

path = "codex-rs/core/src/client.rs"
replace_once(
    path,
    "use codex_extension_api::ModelProviderPolicyError;\n",
    "use codex_extension_api::ModelProviderOutputDecision;\nuse codex_extension_api::ModelProviderPolicyError;\n",
)
replace_once(
    path,
    "use crate::model_provider_policy::begin_model_provider_policy;\n",
    "use crate::model_provider_policy::begin_model_provider_policy;\nuse crate::model_provider_policy::canonical_sha256;\n",
)
replace_once(
    path,
    """            let Some(event) = event else {
                break;
            };
            match event {
""",
    """            let Some(event) = event else {
                break;
            };
            let output_decision = match &event {
                Ok(provider_event) => {
                    let encoded_bytes = match serde_json::to_vec(provider_event) {
                        Ok(value) => u64::try_from(value.len()).unwrap_or(u64::MAX),
                        Err(error) => {
                            let error = model_provider_policy_error(ModelProviderPolicyError::new(
                                "model_provider_output_encoding_failed",
                                format!("failed to encode provider output event: {error}"),
                            ));
                            inference_trace_attempt.record_failed(
                                &error,
                                upstream_request_id,
                                &items_added,
                            );
                            session_telemetry.see_event_completed_failed(&error);
                            let _ = tx_event.send(Err(error)).await;
                            return;
                        }
                    };
                    let event_sha256 = match canonical_sha256(provider_event) {
                        Ok(value) => value,
                        Err(error) => {
                            let error = model_provider_policy_error(error);
                            inference_trace_attempt.record_failed(
                                &error,
                                upstream_request_id,
                                &items_added,
                            );
                            session_telemetry.see_event_completed_failed(&error);
                            let _ = tx_event.send(Err(error)).await;
                            return;
                        }
                    };
                    match provider_terminal
                        .authorize_output(event_sha256, encoded_bytes)
                        .await
                    {
                        Ok(decision) => decision,
                        Err(error) => {
                            let _ = provider_terminal
                                .finish_indeterminate(
                                    "provider_output_authorization_failed",
                                    &items_added,
                                )
                                .await;
                            let error = model_provider_policy_error(error);
                            inference_trace_attempt.record_failed(
                                &error,
                                upstream_request_id,
                                &items_added,
                            );
                            session_telemetry.see_event_completed_failed(&error);
                            let _ = tx_event.send(Err(error)).await;
                            return;
                        }
                    }
                }
                Err(_) => ModelProviderOutputDecision::Allow,
            };
            let output_allowed = matches!(output_decision, ModelProviderOutputDecision::Allow);
            if let ModelProviderOutputDecision::Drop {
                reason_code,
                message,
            } = &output_decision
            {
                tracing::warn!(
                    reason_code,
                    message,
                    "provider output event dropped by current-use fence"
                );
            }
            match event {
""",
)
replace_once(
    path,
    """                    if tx_event
                        .send(Ok(ResponseEvent::OutputItemDone(item)))
                        .await
                        .is_err()
                    {
""",
    """                    if output_allowed
                        && tx_event
                            .send(Ok(ResponseEvent::OutputItemDone(item)))
                            .await
                            .is_err()
                    {
""",
)
replace_once(
    path,
    """                    if let Some(sender) = tx_last_response.take() {
                        let _ = sender.send(LastResponse {
                            response_id: response_id.clone(),
                            items_added: std::mem::take(&mut items_added),
                        });
                    }
                    if tx_event
                        .send(Ok(ResponseEvent::Completed {
                            response_id,
                            token_usage,
                            end_turn,
                        }))
                        .await
                        .is_err()
                    {
                        return;
                    }
                    if provider_terminal_committed {
                        return;
                    }
""",
    """                    if provider_terminal.output_fence().is_none()
                        && let Some(sender) = tx_last_response.take()
                    {
                        let _ = sender.send(LastResponse {
                            response_id: response_id.clone(),
                            items_added: std::mem::take(&mut items_added),
                        });
                    }
                    if let Some((reason_code, message)) = provider_terminal.output_fence() {
                        let error = CodexErr::Fatal(format!(
                            "model provider output fenced [{reason_code}]: {message}"
                        ));
                        inference_trace_attempt.record_failed(
                            &error,
                            upstream_request_id,
                            &items_added,
                        );
                        session_telemetry.see_event_completed_failed(&error);
                        let _ = tx_event.send(Err(error)).await;
                        return;
                    }
                    if output_allowed
                        && tx_event
                            .send(Ok(ResponseEvent::Completed {
                                response_id,
                                token_usage,
                                end_turn,
                            }))
                            .await
                            .is_err()
                    {
                        return;
                    }
                    if provider_terminal_committed {
                        return;
                    }
""",
)
replace_once(
    path,
    """                    if matches!(&event, ResponseEvent::OutputItemAdded(_)) && ttft_ms.is_none() {
""",
    """                    if output_allowed
                        && matches!(&event, ResponseEvent::OutputItemAdded(_))
                        && ttft_ms.is_none()
                    {
""",
)
replace_once(
    path,
    """                    if tx_event.send(Ok(event)).await.is_err() {
""",
    """                    if output_allowed && tx_event.send(Ok(event)).await.is_err() {
""",
)

print("prompt.registry output gate source edits applied")
