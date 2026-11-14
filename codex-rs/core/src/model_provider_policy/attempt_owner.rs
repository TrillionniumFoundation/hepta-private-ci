use std::fmt;
use std::sync::Arc;

use codex_api::EncodedRequestBodyObserver;
use codex_api::RequestDispatchMetadata;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderTerminal;
use futures::future::BoxFuture;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

const OWNER_DROPPED_BEFORE_DISPATCH: &str = "model_provider_policy_owner_dropped_before_dispatch";
const OWNER_DROPPED_AFTER_DISPATCH: &str = "model_provider_policy_owner_dropped_after_dispatch";

/// Returns the same owned lease when observation completes or is cancelled.
/// No request bytes or asynchronous cleanup are retained by this transfer.
struct ObservationLease {
    lease: Option<Box<dyn ModelProviderAttemptLease>>,
    return_to_owner: Option<oneshot::Sender<Box<dyn ModelProviderAttemptLease>>>,
}

impl Drop for ObservationLease {
    fn drop(&mut self) {
        if let (Some(lease), Some(return_to_owner)) =
            (self.lease.take(), self.return_to_owner.take())
        {
            let _ = return_to_owner.send(lease);
        }
    }
}

struct LeaseFinalRequestObserver {
    commands: mpsc::WeakUnboundedSender<OwnerCommand>,
}

impl fmt::Debug for LeaseFinalRequestObserver {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LeaseFinalRequestObserver")
            .finish_non_exhaustive()
    }
}

impl EncodedRequestBodyObserver for LeaseFinalRequestObserver {
    fn observe_encoded_body<'a>(&'a self, body: &'a [u8]) -> BoxFuture<'a, Result<(), String>> {
        Box::pin(async move {
            let commands = self
                .commands
                .upgrade()
                .ok_or_else(observation_stopped_error)?;
            let (acknowledge, acknowledged) = oneshot::channel();
            commands
                .send(OwnerCommand::ObserveFinalRequest { acknowledge })
                .map_err(|_| observation_stopped_error())?;
            let observation = acknowledged
                .await
                .map_err(|_| observation_stopped_error())?;
            let lease = observation
                .lease
                .as_ref()
                .ok_or_else(observation_stopped_error)?;
            let result = lease
                .observe_final_request(body)
                .await
                .map_err(|error| format!("{}: {}", error.reason_code(), error.detail()));
            drop(observation);
            drop(commands);
            result
        })
    }
}

/// Cancellation-safe terminal owner for one admitted physical provider send.
///
/// A detached supervisor owns the policy lease, lending it only while the
/// final request callback runs. Dropping this handle closes its command channel
/// after any active observation returns the lease and forces exactly one
/// fallback terminal based on the shared dispatch witness. No drop hook
/// spawns new async work.
#[must_use = "an admitted provider attempt must retain its terminal owner"]
pub(crate) struct ProviderAttemptOwner {
    commands: mpsc::UnboundedSender<OwnerCommand>,
}

impl ProviderAttemptOwner {
    pub(crate) fn new(
        lease: Box<dyn ModelProviderAttemptLease>,
        dispatch_metadata: RequestDispatchMetadata,
    ) -> Self {
        let requires_final_request_observation = lease.requires_final_request_observation();
        let dispatch_probe = dispatch_metadata.clone();
        let owner = Self::new_with_dispatch_probe(
            lease,
            Box::new(move || dispatch_probe.transport_invoked()),
        );
        if requires_final_request_observation {
            dispatch_metadata.require_final_request_observation();
        }
        if requires_final_request_observation
            && let Err(error) = dispatch_metadata.install_final_request_observer(Arc::new(
                LeaseFinalRequestObserver {
                    commands: owner.commands.downgrade(),
                },
            ))
        {
            tracing::error!(
                detail = error,
                "provider final-request observer installation invariant failed"
            );
        }
        owner
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
    ObserveFinalRequest {
        acknowledge: oneshot::Sender<ObservationLease>,
    },
    Finish {
        terminal: ModelProviderTerminal,
        acknowledge: oneshot::Sender<Result<(), ModelProviderPolicyError>>,
    },
}

async fn lend_lease_for_observation(
    lease: Box<dyn ModelProviderAttemptLease>,
    acknowledge: oneshot::Sender<ObservationLease>,
) -> Result<Box<dyn ModelProviderAttemptLease>, ModelProviderPolicyError> {
    let (return_to_owner, returned) = oneshot::channel();
    // A failed send drops the transfer and immediately returns the lease.
    // Dropping the receiving future after a successful send does the same.
    let _ = acknowledge.send(ObservationLease {
        lease: Some(lease),
        return_to_owner: Some(return_to_owner),
    });
    returned.await.map_err(|_| owner_stopped_error())
}

async fn run_owner(
    mut lease: Box<dyn ModelProviderAttemptLease>,
    dispatch_probe: Box<dyn Fn() -> bool + Send + 'static>,
    mut commands: mpsc::UnboundedReceiver<OwnerCommand>,
) {
    while let Some(command) = commands.recv().await {
        match command {
            OwnerCommand::ObserveFinalRequest { acknowledge } => {
                match lend_lease_for_observation(lease, acknowledge).await {
                    Ok(returned) => lease = returned,
                    Err(error) => {
                        tracing::warn!(
                            reason_code = error.reason_code(),
                            detail = error.detail(),
                            "provider observation ended without returning its lease"
                        );
                        return;
                    }
                }
            }
            OwnerCommand::Finish {
                terminal,
                acknowledge,
            } => {
                // Reject queued and future observations as soon as the lease is consumed,
                // without making them wait for terminal persistence.
                drop(commands);
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

fn observation_stopped_error() -> String {
    "provider attempt lease was consumed before final request observation".to_owned()
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

#[cfg(test)]
#[path = "attempt_observation_tests.rs"]
mod observation_tests;
