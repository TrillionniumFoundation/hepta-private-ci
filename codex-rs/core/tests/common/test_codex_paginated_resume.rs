//! Resume explicit paginated fixtures through the existing store-owned model
//! context API, rather than the legacy full-rollout history reader.

use std::path::PathBuf;
use std::sync::Arc;

use codex_core::{NewThread, ThreadManager};
use codex_core::config::Config;
use codex_history::{InitialHistory, ResumedHistory};
use codex_login::AuthManager;
use codex_protocol::mcp::ClientMcpExtensions;
use codex_protocol::protocol::ThreadHistoryMode;
use codex_thread_store::{LoadThreadHistoryParams, ReadThreadByRolloutPathParams, ThreadStore};

pub(super) async fn resume(
    manager: &ThreadManager,
    store: &dyn ThreadStore,
    config: Config,
    rollout_path: PathBuf,
    auth_manager: Arc<AuthManager>,
    client_mcp_extensions: ClientMcpExtensions,
) -> anyhow::Result<NewThread> {
    let metadata = store.read_thread_by_rollout_path(ReadThreadByRolloutPathParams {
        rollout_path: rollout_path.clone(), include_archived: true, include_history: false,
    }).await?;
    anyhow::ensure!(metadata.history_mode == ThreadHistoryMode::Paginated,
        "explicit paginated fixture cannot resume another persisted history mode");
    let context = store.load_latest_model_context(LoadThreadHistoryParams {
        thread_id: metadata.thread_id, include_archived: true,
    }).await?;
    anyhow::ensure!(context.thread_id == metadata.thread_id,
        "store returned another thread's model context");
    Ok(manager.resume_thread_with_history(config, InitialHistory::Resumed(ResumedHistory {
        conversation_id: metadata.thread_id, history: Arc::new(context.items), rollout_path: Some(rollout_path),
    }), auth_manager, /*parent_trace*/ None, client_mcp_extensions).await?)
}
