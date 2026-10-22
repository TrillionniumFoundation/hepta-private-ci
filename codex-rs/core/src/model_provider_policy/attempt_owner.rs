use codex_api::RequestDispatchMetadata;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTerminal;
use std::sync::Arc;
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
    encoded_body_required: bool,
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
        let encoded_body_required = lease.encoded_body_required();
        tokio::spawn(run_owner(lease, dispatch_probe, receiver));
        Self {
            commands,
            encoded_body_required,
        }
    }

    pub(crate) fn encoded_observer(
        &self,
        prior: Option<Arc<dyn codex_api::EncodedRequestBodyObserver>>,
    ) -> Option<Arc<dyn codex_api::EncodedRequestBodyObserver>> {
        self.encoded_body_required().then(|| {
            Arc::new(AttemptBodyObserver {
                commands: self.commands.downgrade(),
                prior,
                called: std::sync::atomic::AtomicBool::new(false),
            }) as Arc<dyn codex_api::EncodedRequestBodyObserver>
        })
    }

    pub(crate) fn encoded_body_required(&self) -> bool {
        self.encoded_body_required
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
    Bind {
        digest: ModelProviderSha256Digest,
        bytes: u64,
        acknowledge: oneshot::Sender<Result<(), ModelProviderPolicyError>>,
    },
    Finish {
        terminal: ModelProviderTerminal,
        acknowledge: oneshot::Sender<Result<(), ModelProviderPolicyError>>,
    },
}

async fn run_owner(
    mut lease: Box<dyn ModelProviderAttemptLease>,
    dispatch_probe: Box<dyn Fn() -> bool + Send + 'static>,
    mut commands: mpsc::UnboundedReceiver<OwnerCommand>,
) {
    while let Some(command) = commands.recv().await {
        match command {
            OwnerCommand::Bind {
                digest,
                bytes,
                acknowledge,
            } => {
                let _ = acknowledge.send(lease.bind_encoded_body_v1(digest, bytes).await);
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

#[derive(Debug)]
struct AttemptBodyObserver {
    commands: mpsc::WeakUnboundedSender<OwnerCommand>,
    prior: Option<Arc<dyn codex_api::EncodedRequestBodyObserver>>,
    called: std::sync::atomic::AtomicBool,
}

impl codex_api::EncodedRequestBodyObserver for AttemptBodyObserver {
    fn observe_encoded_body<'a>(
        &'a self,
        body: &'a [u8],
    ) -> futures::future::BoxFuture<'a, Result<(), String>> {
        Box::pin(async move {
            if self.called.swap(true, std::sync::atomic::Ordering::AcqRel) {
                return Err("encoded request observer is single-use".into());
            }
            if let Some(prior) = &self.prior {
                prior.observe_encoded_body(body).await?;
            }
            let commands = self
                .commands
                .upgrade()
                .ok_or("encoded request owner stopped")?;
            let digest = super::binding::bytes_sha256(body)
                .map_err(|error| error.reason_code().to_string())?;
            let bytes = u64::try_from(body.len()).map_err(|_| "encoded request length overflow")?;
            let (acknowledge, acknowledged) = oneshot::channel();
            commands
                .send(OwnerCommand::Bind {
                    digest,
                    bytes,
                    acknowledge,
                })
                .map_err(|_| "encoded request owner stopped")?;
            // The weak observer must not keep a cancelled operation alive.
            drop(commands);
            acknowledged
                .await
                .map_err(|_| "encoded request owner stopped")?
                .map_err(|error| error.reason_code().to_string())
        })
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
