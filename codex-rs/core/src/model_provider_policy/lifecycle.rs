use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionRegistry;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderTerminal;
use std::sync::Arc;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

const BLOCKED_CLEANUP_REASON: &str = "model_provider_policy_blocked";
const ERROR_CLEANUP_REASON: &str = "model_provider_policy_begin_failed";
const OWNER_DROPPED_CLEANUP_REASON: &str = "model_provider_policy_begin_cancelled";

/// Result of aggregating all active model-provider policy contributors.
///
/// `NoPolicy` remains distinct from `Allow`: callers can preserve the ordinary
/// provider fast path when no contributor is active.
pub(crate) enum ModelProviderPolicyBegin {
    NoPolicy,
    Allow {
        lease: Box<dyn ModelProviderAttemptLease>,
    },
    Block {
        reason_code: String,
        message: String,
    },
}

/// Exact policy contributors active before any asynchronous request composition.
pub(crate) struct ActiveModelProviderPolicies {
    contributors: Vec<Arc<dyn codex_extension_api::ModelProviderPolicyContributor>>,
}

impl ActiveModelProviderPolicies {
    pub(crate) fn is_empty(&self) -> bool {
        self.contributors.is_empty()
    }
}

/// Freezes policy activation so extension awaits cannot change this attempt's gate set.
pub(crate) fn active_model_provider_policies<C: Sync>(
    registry: &ExtensionRegistry<C>,
    thread_store: &ExtensionData,
) -> ActiveModelProviderPolicies {
    ActiveModelProviderPolicies {
        contributors: registry
            .model_provider_policy_contributors()
            .iter()
            .filter(|contributor| contributor.is_active(thread_store))
            .cloned()
            .collect(),
    }
}

/// Returns whether constructing a provider-policy binding is necessary.
pub(crate) fn has_active_model_provider_policy<C: Sync>(
    registry: &ExtensionRegistry<C>,
    thread_store: &ExtensionData,
) -> bool {
    registry
        .model_provider_policy_contributors()
        .iter()
        .any(|contributor| contributor.is_active(thread_store))
}

/// Runs active provider-policy contributors in registration order.
///
/// Every acquired lease is either returned as one opaque, single-use
/// composite lease or completed as `NotDispatched` before a later block/error
/// is returned. Cleanup and terminal failures fail closed and are surfaced.
pub(crate) async fn begin_model_provider_policy<C: Sync>(
    registry: &ExtensionRegistry<C>,
    input: ModelProviderInvocationInput<'_>,
) -> Result<ModelProviderPolicyBegin, ModelProviderPolicyError> {
    let active = active_model_provider_policies(registry, input.thread_store);
    begin_active_model_provider_policy(active, input).await
}

/// Runs only the contributors captured by `active_model_provider_policies`.
pub(crate) async fn begin_active_model_provider_policy(
    active: ActiveModelProviderPolicies,
    input: ModelProviderInvocationInput<'_>,
) -> Result<ModelProviderPolicyBegin, ModelProviderPolicyError> {
    let supervisor = LeaseSupervisor::new();
    let mut lease_count = 0usize;

    for contributor in active.contributors {
        match contributor.begin(copy_input(&input)).await {
            Ok(ModelProviderPolicyDecision::Allow { lease }) => {
                supervisor.add(lease)?;
                lease_count += 1;
            }
            Ok(ModelProviderPolicyDecision::Block {
                reason_code,
                message,
            }) => {
                let block = format!("{reason_code}: {message}");
                supervisor
                    .finish(
                        ModelProviderTerminal::NotDispatched {
                            reason_code: BLOCKED_CLEANUP_REASON.to_string(),
                        },
                        "model_provider_policy_block_cleanup_failed",
                    )
                    .await
                    .map_err(|cleanup| {
                        ModelProviderPolicyError::new(
                            "model_provider_policy_block_and_cleanup_failed",
                            format!(
                                "policy blocked ({block}); cleanup failed ({})",
                                cleanup.detail()
                            ),
                        )
                    })?;
                return Ok(ModelProviderPolicyBegin::Block {
                    reason_code,
                    message,
                });
            }
            Err(error) => {
                if lease_count == 0 {
                    return Err(error);
                }
                let origin = format!("{}: {}", error.reason_code(), error.detail());
                supervisor
                    .finish(
                        ModelProviderTerminal::NotDispatched {
                            reason_code: ERROR_CLEANUP_REASON.to_string(),
                        },
                        "model_provider_policy_error_cleanup_failed",
                    )
                    .await
                    .map_err(|cleanup| {
                        ModelProviderPolicyError::new(
                            "model_provider_policy_begin_and_cleanup_failed",
                            format!(
                                "begin failed ({origin}); cleanup failed ({})",
                                cleanup.detail()
                            ),
                        )
                    })?;
                return Err(error);
            }
        }
    }

    if lease_count == 0 {
        Ok(ModelProviderPolicyBegin::NoPolicy)
    } else {
        Ok(ModelProviderPolicyBegin::Allow {
            lease: Box::new(CompositeModelProviderAttemptLease { supervisor }),
        })
    }
}

struct CompositeModelProviderAttemptLease {
    supervisor: LeaseSupervisor,
}

impl ModelProviderAttemptLease for CompositeModelProviderAttemptLease {
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

struct LeaseSupervisor {
    commands: mpsc::UnboundedSender<LeaseCommand>,
}

impl LeaseSupervisor {
    fn new() -> Self {
        let (commands, receiver) = mpsc::unbounded_channel();
        tokio::spawn(run_lease_supervisor(receiver));
        Self { commands }
    }

    fn add(
        &self,
        lease: Box<dyn ModelProviderAttemptLease>,
    ) -> Result<(), ModelProviderPolicyError> {
        self.commands.send(LeaseCommand::Add(lease)).map_err(|_| {
            ModelProviderPolicyError::new(
                "model_provider_policy_lease_supervisor_stopped",
                "provider policy lease supervisor stopped during contributor aggregation",
            )
        })
    }

    async fn finish(
        self,
        terminal: ModelProviderTerminal,
        aggregate_reason_code: &'static str,
    ) -> Result<(), ModelProviderPolicyError> {
        let (acknowledge, acknowledged) = oneshot::channel();
        self.commands
            .send(LeaseCommand::Finish {
                terminal,
                aggregate_reason_code,
                acknowledge,
            })
            .map_err(|_| {
                ModelProviderPolicyError::new(
                    "model_provider_policy_lease_supervisor_stopped",
                    "provider policy lease supervisor stopped before terminal ownership transfer",
                )
            })?;
        acknowledged.await.map_err(|_| {
            ModelProviderPolicyError::new(
                "model_provider_policy_lease_supervisor_stopped",
                "provider policy lease supervisor stopped before acknowledging terminal cleanup",
            )
        })?
    }
}

enum LeaseCommand {
    Add(Box<dyn ModelProviderAttemptLease>),
    Finish {
        terminal: ModelProviderTerminal,
        aggregate_reason_code: &'static str,
        acknowledge: oneshot::Sender<Result<(), ModelProviderPolicyError>>,
    },
}

async fn run_lease_supervisor(mut commands: mpsc::UnboundedReceiver<LeaseCommand>) {
    let mut leases = Vec::new();
    while let Some(command) = commands.recv().await {
        match command {
            LeaseCommand::Add(lease) => leases.push(lease),
            LeaseCommand::Finish {
                terminal,
                aggregate_reason_code,
                acknowledge,
            } => {
                let _ =
                    acknowledge.send(finish_leases(leases, terminal, aggregate_reason_code).await);
                return;
            }
        }
    }

    if leases.is_empty() {
        return;
    }
    if let Err(error) = finish_leases(
        leases,
        ModelProviderTerminal::NotDispatched {
            reason_code: OWNER_DROPPED_CLEANUP_REASON.to_string(),
        },
        "model_provider_policy_cancelled_cleanup_failed",
    )
    .await
    {
        tracing::warn!(
            reason_code = error.reason_code(),
            detail = error.detail(),
            "failed to close provider policy leases after begin cancellation"
        );
    }
}

async fn finish_leases(
    leases: Vec<Box<dyn ModelProviderAttemptLease>>,
    terminal: ModelProviderTerminal,
    aggregate_reason_code: &'static str,
) -> Result<(), ModelProviderPolicyError> {
    let mut failures = Vec::new();
    for lease in leases {
        if let Err(error) = lease.finish(terminal.clone()).await {
            failures.push(format!("{}: {}", error.reason_code(), error.detail()));
        }
    }

    if failures.is_empty() {
        Ok(())
    } else {
        Err(ModelProviderPolicyError::new(
            aggregate_reason_code,
            failures.join("; "),
        ))
    }
}

fn copy_input<'a>(input: &ModelProviderInvocationInput<'a>) -> ModelProviderInvocationInput<'a> {
    ModelProviderInvocationInput {
        schema_version: input.schema_version,
        session_store: input.session_store,
        thread_store: input.thread_store,
        turn_store: input.turn_store,
        attempt_id: input.attempt_id,
        request_binding_id: input.request_binding_id,
        thread_id: input.thread_id,
        turn_id: input.turn_id,
        request_kind: input.request_kind,
        provider_id: input.provider_id,
        provider_config_sha256: input.provider_config_sha256,
        model: input.model,
        transport: input.transport,
        endpoint_sha256: input.endpoint_sha256,
        logical_request_sha256: input.logical_request_sha256,
        wire_semantic_sha256: input.wire_semantic_sha256,
        ephemeral_input_sha256: input.ephemeral_input_sha256,
        ephemeral_input_witness_sha256: input.ephemeral_input_witness_sha256,
        previous_response_id_sha256: input.previous_response_id_sha256,
        generate: input.generate,
    }
}

#[cfg(test)]
#[path = "lifecycle_tests.rs"]
mod tests;
