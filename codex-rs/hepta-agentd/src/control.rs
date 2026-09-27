use std::future::pending;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use tokio::task::JoinHandle;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::ProcessRuntimeCodexExecutorV1;

#[path = "control_base.rs"]
mod base;

const RUNTIME_CODEX_DRAIN_GRACE: Duration = Duration::from_secs(2);

type OwnerTask = JoinHandle<Result<(), AgentdError>>;

/// Control transport plus the daemon-owned runtime.codex lifecycle.
///
/// The legacy transport remains unchanged inside `base`; this wrapper gives the
/// process executor one structured owner task and deliberately keeps the socket
/// alive while that owner interrupts and reconciles an in-flight worker.
pub(crate) struct AgentdControlServer {
    inner: base::AgentdControlServer,
    identity: AgentdIdentity,
    shutdown: CancellationToken,
    control_shutdown: CancellationToken,
}

impl AgentdControlServer {
    pub(crate) async fn bind(
        socket_path: PathBuf,
        state: Arc<AgentdState>,
        shutdown: CancellationToken,
    ) -> Result<Self, AgentdError> {
        let identity = state.identity().clone();
        let control_shutdown = CancellationToken::new();
        let inner = base::AgentdControlServer::bind(
            socket_path,
            state,
            control_shutdown.clone(),
        )
        .await?;
        Ok(Self {
            inner,
            identity,
            shutdown,
            control_shutdown,
        })
    }

    pub(crate) async fn run(self) -> Result<(), AgentdError> {
        let mut control = tokio::spawn(self.inner.run());
        let mut owner = ProcessRuntimeCodexExecutorV1::agentd_supervisor_installed().then(|| {
            let identity = self.identity.clone();
            let shutdown = self.shutdown.clone();
            tokio::spawn(async move {
                ProcessRuntimeCodexExecutorV1::run_installed_agentd_supervisor(identity, shutdown)
                    .await
            })
        });

        tokio::select! {
            control_result = &mut control => {
                self.shutdown.cancel();
                let owner_result = drain_owner(&mut owner).await;
                join_result(control_result, "agentd control server")?;
                owner_result
            }
            owner_result = wait_owner(&mut owner) => {
                self.control_shutdown.cancel();
                let control_result = control.await;
                owner_result?;
                join_result(control_result, "agentd control server")
            }
            () = self.shutdown.cancelled() => {
                let owner_result = drain_owner(&mut owner).await;
                self.control_shutdown.cancel();
                let control_result = control.await;
                owner_result?;
                join_result(control_result, "agentd control server")
            }
        }
    }
}

async fn wait_owner(owner: &mut Option<OwnerTask>) -> Result<(), AgentdError> {
    match owner.as_mut() {
        Some(owner) => join_result(owner.await, "runtime.codex supervisor"),
        None => pending().await,
    }
}

async fn drain_owner(owner: &mut Option<OwnerTask>) -> Result<(), AgentdError> {
    let Some(owner) = owner.as_mut() else {
        return Ok(());
    };
    match timeout(RUNTIME_CODEX_DRAIN_GRACE, &mut *owner).await {
        Ok(result) => join_result(result, "runtime.codex supervisor"),
        Err(_) => {
            owner.abort();
            let _ = owner.await;
            Err(AgentdError::Protocol(
                "runtime.codex supervisor did not drain within the bounded shutdown grace"
                    .to_string(),
            ))
        }
    }
}

fn join_result(
    result: Result<Result<(), AgentdError>, tokio::task::JoinError>,
    label: &str,
) -> Result<(), AgentdError> {
    match result {
        Ok(result) => result,
        Err(error) => Err(AgentdError::Protocol(format!(
            "{label} task failed: {error}"
        ))),
    }
}
