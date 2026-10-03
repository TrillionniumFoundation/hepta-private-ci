//! Recover the old exact operation through the current kernel-bound original owner.
use super::*;
use codex_hepta_matrixd::chat::wire::ChatRequest;
use codex_hepta_supervisor::SupervisordAgentStatus;

impl RootChatHost {
    pub(super) async fn recover(
        &self,
        scope: &configuration::AgentScope,
        current: &SupervisordAgentStatus,
        binding: NativeChatBinding,
        original_binding: NativeChatBinding,
        request: ChatRequest,
        abandon: bool,
    ) -> Result<NativeChatRootResponse> {
        ensure!(
            binding.agent_id == original_binding.agent_id,
            "foreign original Agent"
        );
        let args = MatrixAgentdConnectArgs::new(
            self.layout
                .agent(&scope.agent_id)
                .agentd_control_socket()
                .to_owned(),
            scope.agent_id.clone(),
            current
                .spawn_generation
                .ok_or_else(|| anyhow::anyhow!("missing current spawn generation"))?,
            env!("CARGO_PKG_VERSION"),
        );
        let uid = self.gateway.agent_workload_uid(&scope.agent_id)?;
        // This recovery connection cannot replace a session slot or grant the
        // old request the current process's mutation fence. Send observes only;
        // CreateOnce may repair its exact original receipt/index, never create.
        let owner = match (&scope.project_id, &scope.managed_project) {
            (Some(id), None) => {
                AgentChatSession::connect_existing_observer_for_agent_process(
                    args,
                    id.clone(),
                    scope.workspace.clone(),
                    request.session_id.clone(),
                    /*connection_generation*/ 1,
                    uid,
                    binding.agent_process_id,
                )
                .await?
            }
            (None, Some(project)) => {
                AgentChatSession::connect_managed_observer_for_agent_process(
                    args,
                    project.clone(),
                    scope.workspace.clone(),
                    request.session_id.clone(),
                    /*connection_generation*/ 1,
                    uid,
                    binding.agent_process_id,
                )
                .await?
            }
            _ => anyhow::bail!("invalid fixed original project"),
        };
        match &request.command {
            codex_hepta_matrixd::chat::wire::ChatCommand::Send { .. } => {
                ensure!(!abandon, "only identified creation can be abandoned");
                let observation = tokio::time::timeout(
                    std::time::Duration::from_secs(10),
                    owner.observe_message(&request),
                )
                .await??;
                Ok(NativeChatRootResponse::Recovered {
                    binding,
                    original_binding,
                    request,
                    observation,
                })
            }
            codex_hepta_matrixd::chat::wire::ChatCommand::CreateOnce { .. } => {
                let observation = tokio::time::timeout(std::time::Duration::from_secs(10), async {
                    if abandon {
                        owner.abandon_creation(&request).await
                    } else {
                        owner.reconcile_creation(&request).await
                    }
                })
                .await??;
                Ok(NativeChatRootResponse::CreationRecovered {
                    binding,
                    original_binding,
                    request,
                    observation,
                })
            }
            _ => anyhow::bail!("operation has no original durable recovery identity"),
        }
    }
}
