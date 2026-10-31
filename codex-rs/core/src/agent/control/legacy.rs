use super::*;
use crate::agent::registry::AgentRegistration;
use crate::codex_thread::CodexThread;
#[cfg(test)]
use crate::lifecycle_test_diagnostics::record;
use codex_protocol::error::CodexErrorDetails;
use codex_thread_store::PersistContext;

impl AgentControl {
    /// Submit a shutdown request for a live agent without marking it explicitly closed in
    /// persisted spawn-edge state.
    pub(crate) async fn shutdown_live_agent(&self, agent_id: ThreadId) -> CodexResult<String> {
        #[cfg(test)]
        record(agent_id, format_args!("shutdown lookup begin"));
        let state = self.upgrade()?;
        let registration = self.state.registration_for_thread(agent_id);
        let thread = match state.get_thread(agent_id).await {
            Ok(thread) => thread,
            Err(error) => {
                if matches!(error.details(), CodexErrorDetails::ThreadNotFound(_))
                    && let Some(registration) = registration
                {
                    let _transition = self.transitions.lock(agent_id).await;
                    state
                        .retire_cold_agent_if_unloaded(agent_id, || {
                            self.release_cold_registration(agent_id, &registration)
                        })
                        .await;
                }
                return Err(error);
            }
        };
        let stopped = shutdown_captured_runtime(&state, thread).await?;
        let _transition = self.transitions.lock(agent_id).await;
        #[cfg(test)]
        record(agent_id, format_args!("shutdown registry removal begin"));
        let _ = state
            .retire_runtime_if_current(agent_id, &stopped.thread, || {
                self.forget_v2_residency(agent_id);
                self.state.release_spawned_thread(agent_id);
            })
            .await;
        #[cfg(test)]
        record(agent_id, format_args!("shutdown live agent returned"));
        stopped.submission
    }

    /// Mark `agent_id` as explicitly closed in persisted spawn-edge state, then shut down the
    /// agent and any live descendants reached from the in-memory tree.
    pub(crate) async fn close_agent(&self, agent_id: ThreadId) -> CodexResult<String> {
        let state = self.upgrade()?;
        // Persist and retire under one per-agent transition, but release it before
        // visiting descendants. Persistence failure must leave the whole tree live.
        let transition = self.transitions.lock(agent_id).await;
        let registration = self.state.registration_for_thread(agent_id);
        let thread = state.get_thread(agent_id).await;
        let persist_close = match &thread {
            Ok(thread) => !thread.config_snapshot().await.ephemeral,
            Err(error) if matches!(error.details(), CodexErrorDetails::ThreadNotFound(_)) => {
                registration.is_some()
            }
            Err(_) => false,
        };
        if persist_close && let Some(agent_graph_store) = state.agent_graph_store() {
            agent_graph_store
                .set_thread_spawn_edge_status(
                    agent_id,
                    codex_agent_graph_store::ThreadSpawnEdgeStatus::Closed,
                )
                .await
                .map_err(|err| {
                    CodexErr::Fatal(format!(
                        "failed to persist thread-spawn edge status for {agent_id}: {err}"
                    ))
                })?;
        }
        let descendant_ids = self.live_thread_spawn_descendants(agent_id).await?;
        let result = async {
            match thread {
                Ok(thread) => {
                    let stopped = shutdown_captured_runtime(&state, thread).await?;
                    if state
                        .retire_runtime_if_current(agent_id, &stopped.thread, || {
                            self.forget_v2_residency(agent_id);
                            self.state.release_spawned_thread(agent_id);
                        })
                        .await
                        .is_none()
                        && !state
                            .retire_cold_agent_if_unloaded(agent_id, || {
                                // Another exact-owner error handler may already have
                                // retired A. An absent or still-owned registration is
                                // safe; a different metadata generation is untouched.
                                registration.as_ref().is_some_and(|registration| {
                                    self.release_cold_registration(agent_id, registration)
                                }) || self.state.registration_for_thread(agent_id).is_none()
                            })
                            .await
                    {
                        return Err(CodexErr::InvalidRequest(format!(
                            "agent {agent_id} changed runtime while closing; retry the close"
                        )));
                    }
                    match stopped.submission {
                        Err(error)
                            if registration.is_some()
                                && matches!(
                                    error.details(),
                                    CodexErrorDetails::InternalAgentDied
                                ) =>
                        {
                            Ok(String::new())
                        }
                        result => result,
                    }
                }
                Err(error) if matches!(error.details(), CodexErrorDetails::ThreadNotFound(_)) => {
                    let Some(registration) = registration else {
                        return Err(error);
                    };
                    if state
                        .retire_cold_agent_if_unloaded(agent_id, || {
                            self.release_cold_registration(agent_id, &registration)
                        })
                        .await
                    {
                        Ok(String::new())
                    } else {
                        Err(CodexErr::InvalidRequest(format!(
                            "agent {agent_id} changed ownership while closing; retry the close"
                        )))
                    }
                }
                Err(error) => Err(error),
            }
        }
        .await;
        drop(transition);
        self.shutdown_descendants(descendant_ids).await?;
        result
    }

    /// Shut down `agent_id` and any live descendants reachable from the in-memory spawn tree.
    pub(crate) async fn shutdown_agent_tree(&self, agent_id: ThreadId) -> CodexResult<String> {
        let descendant_ids = self.live_thread_spawn_descendants(agent_id).await?;
        let result = self.shutdown_live_agent(agent_id).await;
        self.shutdown_descendants(descendant_ids).await?;
        result
    }

    fn release_cold_registration(
        &self,
        agent_id: ThreadId,
        registration: &AgentRegistration,
    ) -> bool {
        if !self
            .state
            .release_spawned_thread_if_current(agent_id, registration)
        {
            return false;
        }
        self.forget_v2_residency(agent_id);
        true
    }

    async fn shutdown_descendants(&self, descendant_ids: Vec<ThreadId>) -> CodexResult<()> {
        for descendant_id in descendant_ids {
            match self.shutdown_live_agent(descendant_id).await {
                Ok(_) => {}
                Err(err)
                    if matches!(
                        err.details(),
                        CodexErrorDetails::ThreadNotFound(_) | CodexErrorDetails::InternalAgentDied
                    ) => {}
                Err(err) => return Err(err),
            }
        }
        Ok(())
    }
}

struct TerminatedAgentRuntime {
    thread: Arc<CodexThread>,
    submission: CodexResult<String>,
}

async fn shutdown_captured_runtime(
    state: &ThreadManagerState,
    thread: Arc<CodexThread>,
) -> CodexResult<TerminatedAgentRuntime> {
    #[cfg(test)]
    let agent_id = thread.session.thread_id();
    #[cfg(test)]
    record(agent_id, format_args!("shutdown materialize begin"));
    thread
        .session
        .ensure_rollout_materialized(PersistContext::Standard)
        .await;
    #[cfg(test)]
    record(agent_id, format_args!("shutdown flush begin"));
    thread.session.flush_rollout().await?;
    #[cfg(test)]
    record(agent_id, format_args!("shutdown status check begin"));
    let submission = if matches!(thread.agent_status().await, AgentStatus::Shutdown) {
        Ok(String::new())
    } else {
        #[cfg(test)]
        record(agent_id, format_args!("shutdown submission begin"));
        state
            .send_op_to_runtime(
                thread.as_ref(),
                Op::Shutdown {},
                /*parent_turn_id*/ None,
                /*root_turn_id*/ None,
            )
            .await
    };
    let submission = match submission {
        Err(error) if !matches!(error.details(), CodexErrorDetails::InternalAgentDied) => {
            return Err(error);
        }
        result => result,
    };
    #[cfg(test)]
    record(
        agent_id,
        format_args!(
            "shutdown termination wait begin submission_ok={}",
            submission.is_ok()
        ),
    );
    thread.wait_until_terminated().await;
    #[cfg(test)]
    record(agent_id, format_args!("shutdown termination wait returned"));
    Ok(TerminatedAgentRuntime { thread, submission })
}
