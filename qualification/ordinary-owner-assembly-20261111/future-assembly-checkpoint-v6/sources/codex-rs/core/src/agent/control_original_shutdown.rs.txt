//! Route only the existing concrete delegate Session startup through its
//! original manager custody when strict shutdown was enabled.

use super::AgentControl;
use crate::session::SessionIo;
use crate::session::SessionSpawnArgs;
use crate::session::session::Session;
use codex_protocol::error::Result as CodexResult;
use std::sync::Arc;

impl AgentControl {
    pub(crate) async fn spawn_original_delegate_session(
        &self,
        args: SessionSpawnArgs,
    ) -> CodexResult<(Arc<Session>, SessionIo)> {
        match &self.original_shutdown {
            Some(origin) => crate::thread_manager::OriginalSessionShutdownOrigin::spawn_original_delegate(origin, args).await,
            None => Session::spawn(args).await,
        }
    }
}
