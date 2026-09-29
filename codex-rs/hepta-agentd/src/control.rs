use std::path::PathBuf;
use std::sync::Arc;

use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdState;

#[path = "control_base.rs"]
mod base;

/// The bounded local control transport.
///
/// Long-lived runtime owners belong to the daemon's single `RuntimeTasks`
/// supervisor. Keeping this wrapper transport-only prevents the control socket
/// from creating a second runtime.codex owner with an independent drain budget.
pub(crate) struct AgentdControlServer {
    inner: base::AgentdControlServer,
}

impl AgentdControlServer {
    pub(crate) async fn bind(
        socket_path: PathBuf,
        state: Arc<AgentdState>,
        shutdown: CancellationToken,
    ) -> Result<Self, AgentdError> {
        let inner = base::AgentdControlServer::bind(socket_path, state, shutdown).await?;
        Ok(Self { inner })
    }

    pub(crate) async fn run(self) -> Result<(), AgentdError> {
        self.inner.run().await
    }
}
