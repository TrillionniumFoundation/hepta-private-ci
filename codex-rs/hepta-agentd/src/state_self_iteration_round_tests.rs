use super::*;
#[tokio::test]
async fn round_status_gate_uses_actual_kernel_root_peer_before_original_owner() {
    let (directory, _registry, state) = super::super::isolation_tests::fixture_with_readiness(true)
        .expect("original Agent fixture");
    let agent = state.identity.agent_id.clone();
    let path = directory.path().join("round-status.sock");
    let state = Arc::new(state);
    let cancel = tokio_util::sync::CancellationToken::new();
    let server = crate::AgentdControlServer::bind(path.clone(), Arc::clone(&state), cancel.clone())
        .await
        .expect("actual control socket");
    let running = tokio::spawn(server.run());
    let client = crate::AgentdClient::new(path, agent, 1).expect("original client");
    let scoped = client
        .self_iteration_round_status(
            codex_hepta_agent_components::types::StableId::new("goal.actual").expect("id"),
            codex_hepta_agent_components::types::Digest32::of_bytes(b"installed policy"),
        )
        .await
        .map(|(_generation, status)| Some(status));
    let current = client
        .self_iteration_current_round()
        .await
        .map(|(_generation, current)| current.map(|value| value.status));
    for result in [scoped, current] {
        match result {
            Err(AgentdError::Protocol(message)) => {
                if unsafe { libc::geteuid() } == 0 {
                    assert!(message.contains("original iteration runtime unavailable"));
                } else {
                    assert!(message.contains("root_peer_required"));
                    assert!(!message.contains("runtime unavailable"));
                }
            }
            other => panic!("an unattached original owner must not yield a round: {other:?}"),
        }
    }
    assert!(state.self_iteration_handle.get().is_none());
    cancel.cancel();
    running
        .await
        .expect("server retirement")
        .expect("server completion");
}
