use codex_api::RequestDispatchMetadata;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderTerminal;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

const OWNER_DROPPED_BEFORE_DISPATCH: &str = "model_provider_policy_owner_dropped_before_dispatch";
const OWNER_DROPPED_AFTER_DISPATCH: &str = "model_provider_policy_owner_dropped_after_dispatch";

/// Cancellation-safe terminal owner for one admitted physical provider send.
///
/// A detached supervisor owns the policy lease. Dropping this handle closes
/// its command channel and forces exactly one fallback terminal based on the
/// shared dispatch witness; no `Drop` implementation spawns new async work.
#[must_use = "an admitted provider attempt must retain its terminal owner"]
pub(crate) struct ProviderAttemptOwner {
    commands: mpsc::UnboundedSender<OwnerCommand>,
}

impl ProviderAttemptOwner {
    pub(crate) fn new(
        lease: Box<dyn ModelProviderAttemptLease>,
        dispatch_metadata: RequestDispatchMetadata,
    ) -> Self {
        Self::new_with_dispatch_probe(
            lease,
            Box::new(move || dispatch_metadata.transport_invoked()),
        )
    }

    fn new_with_dispatch_probe(
        lease: Box<dyn ModelProviderAttemptLease>,
        dispatch_probe: Box<dyn Fn() -> bool + Send + 'static>,
    ) -> Self {
        let (commands, receiver) = mpsc::unbounded_channel();
        tokio::spawn(run_owner(lease, dispatch_probe, receiver));
        Self { commands }
    }

    pub(crate) async fn finish(
        self,
        terminal: ModelProviderTerminal,
    ) -> Result<(), ModelProviderPolicyError> {
        let (acknowledge, acknowledged) = oneshot::channel();
        self.commands
            .send(OwnerCommand::Finish {
                terminal,
                acknowledge,
            })
            .map_err(|_| owner_stopped_error())?;
        acknowledged.await.map_err(|_| owner_stopped_error())?
    }
}

enum OwnerCommand {
    Finish {
        terminal: ModelProviderTerminal,
        acknowledge: oneshot::Sender<Result<(), ModelProviderPolicyError>>,
    },
}

async fn run_owner(
    lease: Box<dyn ModelProviderAttemptLease>,
    dispatch_probe: Box<dyn Fn() -> bool + Send + 'static>,
    mut commands: mpsc::UnboundedReceiver<OwnerCommand>,
) {
    match commands.recv().await {
        Some(OwnerCommand::Finish {
            terminal,
            acknowledge,
        }) => {
            let _ = acknowledge.send(lease.finish(terminal).await);
        }
        None => {
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
    }
}

fn owner_stopped_error() -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "model_provider_policy_owner_stopped",
        "provider attempt terminal owner stopped before acknowledging completion",
    )
}

#[cfg(test)]
#[path = "attempt_owner_tests.rs"]
mod tests;
