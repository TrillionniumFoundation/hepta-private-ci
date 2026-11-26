use super::*;
use crate::plasticity_runtime::current_artifacts::fixture_current_reader;
use crate::plasticity_runtime::current_artifacts::fixture_verified_registry;
use codex_hepta_agent_components::learning_artifacts::ArtifactEvent;
use codex_hepta_agent_components::learning_artifacts::StateChange;

fn retired_view(fixture: &ClockFixture, policy: &str) -> ArtifactRegistry {
    // The admitted proposal still has the original model/registry snapshot.
    // Only the separate CURRENT source observes this later owner transition.
    let mut current = fixture.owner.artifacts.clone();
    current
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("current:withdraw-policy"),
            artifact_id: id(policy),
            evaluator_id: id("current:independent-evaluator"),
            reason_digest: digest("current:withdrawal-reason"),
        }))
        .expect("current policy withdrawal");
    current
}

async fn rejected_without_writes(fixture: ClockFixture, topology: bool) {
    let before = persistent_bytes(&fixture.files);
    let generation = fixture
        .state
        .current_generation()
        .expect("original generation");
    let cancellation = CancellationToken::new();
    let task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    let unavailable = if topology {
        matches!(
            fixture
                .state
                .submit_topology_plasticity_v1(fixture.topology, 50)
                .await,
            Err(PlasticityRuntimeCallErrorV1::Unavailable)
        )
    } else {
        matches!(
            fixture
                .state
                .submit_parameter_plasticity_v1(fixture.parameter, 50)
                .await,
            Err(PlasticityRuntimeCallErrorV1::Unavailable)
        )
    };
    cancellation.cancel();
    task.await.expect("owner join").expect("owner shutdown");
    assert!(unavailable, "missing or changed CURRENT was admitted");
    assert_eq!(persistent_bytes(&fixture.files), before);
    assert_eq!(
        fixture.state.current_generation().expect("same generation"),
        generation
    );
}

#[tokio::test]
async fn parameter_withdrawn_current_update_rule_cannot_reuse_frozen_admission() {
    let mut fixture = clock_fixture(|| Ok(50));
    let current = retired_view(&fixture, "policy:update-rule");
    fixture.owner.current_artifacts = Some(fixture_current_reader(move |_| {
        fixture_verified_registry(&current)
    }));
    rejected_without_writes(fixture, false).await;
}

#[tokio::test]
async fn topology_withdrawn_current_mutation_policy_cannot_reuse_frozen_admission() {
    let mut fixture = clock_fixture(|| Ok(50));
    let current = retired_view(&fixture, "policy:mutation");
    fixture.owner.current_artifacts = Some(fixture_current_reader(move |_| {
        fixture_verified_registry(&current)
    }));
    rejected_without_writes(fixture, true).await;
}

#[tokio::test]
async fn missing_current_source_refuses_parameter_and_topology_without_new_history() {
    for topology in [false, true] {
        let mut fixture = clock_fixture(|| Ok(50));
        fixture.owner.current_artifacts = None;
        rejected_without_writes(fixture, topology).await;
    }
}

#[tokio::test]
async fn unreadable_current_source_never_falls_back_to_the_frozen_snapshot() {
    let mut fixture = clock_fixture(|| Ok(50));
    fixture.owner.current_artifacts = Some(fixture_current_reader(|_| {
        Err("original protected CURRENT unavailable".to_string())
    }));
    rejected_without_writes(fixture, false).await;
}

#[tokio::test]
async fn current_head_expiry_during_final_refresh_refuses_before_append() {
    let mut fixture = clock_fixture(|| Ok(50));
    // Verified CURRENT expires inclusively at 1000. Include all blocking
    // refresh time in the final host sample; the producer's time stays 50.
    fixture.owner.guard_elapsed_ms = |_| 951;
    rejected_without_writes(fixture, false).await;
}
