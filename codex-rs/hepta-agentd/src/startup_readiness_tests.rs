use codex_hepta_fleet::AgentLifecycle;
use pretty_assertions::assert_eq;

use super::runtime_fixture;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::HealthSnapshot;
use crate::state::CognitiveStoreRequirement;

#[tokio::test]
async fn readiness_preserves_the_selected_cognitive_storage_requirement() {
    for (requirement, expected_ready) in [
        (CognitiveStoreRequirement::OptionalReadOnly, true),
        (CognitiveStoreRequirement::RequiredForWrites, false),
    ] {
        let fixture = runtime_fixture();
        fixture
            .state
            .mark_runtime_prerequisites_ready(requirement)
            .expect("startup prerequisites");
        fixture
            .state
            .mark_app_server_ready()
            .expect("App Server initialized");
        let health = fixture
            .state
            .response(1, fixture.identity.spawn_generation, AgentdMethod::Health)
            .await
            .expect("starting health");
        let expected = HealthSnapshot {
            promotion_ready: expected_ready,
            ready: false,
            fenced: false,
            lifecycle: AgentLifecycle::Starting,
            process_id: std::process::id(),
            workspace: fixture.identity.workspace.clone(),
            home_root: fixture.identity.home_root.clone(),
            run_root: fixture.identity.run_root.clone(),
        };
        assert_eq!(health.payload, AgentdPayload::Health(expected.clone()));

        fixture
            .registry
            .compare_and_transition(
                &fixture.identity.agent_id,
                fixture.identity.spawn_generation,
                AgentLifecycle::Running,
            )
            .expect("supervisor promotion");
        let health = fixture
            .state
            .response(2, fixture.identity.spawn_generation, AgentdMethod::Health)
            .await
            .expect("running health");
        assert_eq!(
            health.payload,
            AgentdPayload::Health(HealthSnapshot {
                ready: expected_ready,
                lifecycle: AgentLifecycle::Running,
                ..expected
            })
        );
        #[cfg(feature = "qualification-cognitive-write")]
        assert!(fixture.state.qualification_turn_authority().is_err());
    }
}
