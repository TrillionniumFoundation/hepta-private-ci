//! Root observation of the installed original plasticity owner, never a proposal.
use super::*;
impl AgentdState {
    pub(crate) async fn plasticity_completed_proposal(
        &self,
        proposal_id: String,
    ) -> Result<crate::AgentdPayload, AgentdError> {
        let id = codex_hepta_agent_components::types::StableId::new(&proposal_id)
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        let producer = self.plasticity_runtime.get().ok_or_else(|| {
            AgentdError::Invalid("original plasticity runtime unavailable".into())
        })?;
        let row = producer
            .runtime_handle()
            .observe_completed_proposal(id)
            .await
            .map_err(|error| {
                AgentdError::Invalid(format!("original plasticity observation: {error}"))
            })?;
        let observation_hex = row.map(|bytes| crate::client::encode_hex(&bytes));
        Ok(crate::AgentdPayload::PlasticityCompletedProposal {
            proposal_id,
            observation_hex,
        })
    }
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;
    #[tokio::test]
    async fn completed_plasticity_inspection_authenticates_kernel_root_before_missing_owner() {
        let (directory, _registry, state) =
            super::super::isolation_tests::fixture_with_readiness(true)
                .expect("original actual Agent fixture");
        let path = directory.path().join("plasticity-observation.sock");
        let agent = state.identity.agent_id.clone();
        let state = Arc::new(state);
        let cancel = tokio_util::sync::CancellationToken::new();
        let server =
            crate::AgentdControlServer::bind(path.clone(), Arc::clone(&state), cancel.clone())
                .await
                .expect("actual original socket");
        let running = tokio::spawn(server.run());
        let client = crate::AgentdClient::new(path, agent, 1).expect("client");
        let result = client
            .plasticity_completed_proposal(
                codex_hepta_agent_components::types::StableId::new("actual.proposal").expect("id"),
            )
            .await;
        match result {
            Err(AgentdError::Protocol(message)) => {
                if unsafe { libc::geteuid() } == 0 {
                    assert!(message.contains("original plasticity runtime unavailable"));
                } else {
                    assert!(message.contains("root_peer_required"));
                    assert!(!message.contains("runtime unavailable"));
                }
            }
            other => panic!("missing original writer cannot produce completed facts: {other:?}"),
        }
        cancel.cancel();
        running
            .await
            .expect("actual socket retirement")
            .expect("completion");
    }
}
