//! Source registration is a bounded membership check before original owner reads.
//! These platform-neutral fixtures intentionally attach no Objective owner:
//! reaching its refusal is not a successful source join, evaluation or adoption.

use pretty_assertions::assert_eq;

use super::*;

#[tokio::test]
async fn original_source_scope_rejects_missing_unregistered_and_foreign_agent() {
    let daemon = AgentdFixture::new();
    let state = ok(AgentdState::new(
        daemon.identity.clone(),
        daemon.registry.clone(),
        /*event_capacity*/ 16,
    ));
    let request = iteration_request(&daemon);
    let refused_scope = Err(
        "invalid agentd configuration: AuthBus text: learning source differs from the original daemon scope"
            .to_owned(),
    );
    assert_eq!(
        state
            .require_circuit_learning_source(&request)
            .await
            .map_err(|error| error.to_string()),
        refused_scope,
    );
    let later = id("run:registered-later");
    ok(state.attach_circuit_learning_sources(vec![
        request.source_run_id.clone(),
        later.clone(),
    ]));
    let mut unregistered = request.clone();
    unregistered.source_run_id = id("run:unregistered");
    let mut foreign_agent = request;
    foreign_agent.agent_id = id("agent:foreign");
    foreign_agent.source_run_id = later;
    for invalid in [unregistered, foreign_agent] {
        assert_eq!(
            state
                .require_circuit_learning_source(&invalid)
                .await
                .map_err(|error| error.to_string()),
            refused_scope,
        );
    }
}

#[tokio::test]
async fn registered_sources_at_any_position_still_require_original_owner() {
    let daemon = AgentdFixture::new();
    let state = ok(AgentdState::new(
        daemon.identity.clone(),
        daemon.registry.clone(),
        /*event_capacity*/ 16,
    ));
    let mut request = iteration_request(&daemon);
    let sources = vec![request.source_run_id.clone(), id("run:registered-later")];
    ok(state.attach_circuit_learning_sources(sources.clone()));
    for source in sources {
        request.source_run_id = source;
        assert_eq!(
            state
                .require_circuit_learning_source(&request)
                .await
                .map_err(|error| error.to_string()),
            Err(
                "invalid agentd configuration: AuthBus text: original learning Objective owner is unavailable"
                    .to_owned(),
            ),
        );
    }
}
