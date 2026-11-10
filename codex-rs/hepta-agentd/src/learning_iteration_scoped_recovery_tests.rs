//! Frozen scope remains mandatory on read-only recovery and ordinary delivery.
//! The signed observations below are fixtures, not independent learning evidence.

use super::*;
use crate::learning_iteration_channel_scoped_v2;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn scoped_readback_rechecks_training_for_every_completed_decision_without_work() {
    let mutations: [Option<fn(&mut CellCompatibilityBundleV1)>; 2] = [
        None,
        Some(|candidate| candidate.components.base = digest("outside-frozen-base")),
    ];
    for decision in [
        Decision::EvaluatedNoUpdate,
        Decision::ProposedNoUpdate,
        Decision::Update,
    ] {
        for mutation in mutations {
            let daemon = AgentdFixture::new();
            let request = iteration_request(&daemon);
            let mut ports = recovery_ports(decision, Trust::Independent);
            let scope = ok(FrozenLearningScopeV2::freeze(
                &request,
                &ports.owners(),
                LearningUpdateScopeV2::Cell,
                digest("test-rule"),
            ));
            ports.scope_binding = Some(scope.binding());
            ports.training_mutation = mutation;
            let ports = Arc::new(ports);
            let snapshot = completed_snapshot(request.clone(), &ports, decision).await;
            install_checkpoint(&ports, &snapshot);
            let (_, owner) = ok(learning_iteration_channel_scoped_v2(
                daemon.identity.agent_id.clone(),
                /*spawn_generation*/ 1,
                ports.owners(),
                ports.clone(),
                ports.verifier.clone(),
                /*capacity*/ 2,
                scope,
            ));
            let recovered = owner
                .process_readback(&daemon.state(), request, || Ok(60))
                .await;
            if mutation.is_some() {
                assert!(matches!(
                    recovered,
                    Err(LearningIterationRuntimeErrorV1::Validation(
                        LearningIterationError::UpdateScopeMismatch
                    ))
                ));
                assert!(ok(ports.attested.lock()).is_empty());
            } else {
                assert_eq!(ok(recovered), snapshot);
                assert!(!ok(ports.attested.lock()).is_empty());
            }
            assert_no_work_or_checkpoint(&ports, &snapshot);
        }
    }
}

#[tokio::test]
async fn scoped_readback_and_delivery_refuse_a_rebound_request_before_owner_work() {
    let daemon = AgentdFixture::new();
    let request = iteration_request(&daemon);
    let decision = Decision::EvaluatedNoUpdate;
    let mut ports = recovery_ports(decision, Trust::Independent);
    let scope = ok(FrozenLearningScopeV2::freeze(
        &request,
        &ports.owners(),
        LearningUpdateScopeV2::Cell,
        digest("test-rule"),
    ));
    ports.scope_binding = Some(scope.binding());
    let ports = Arc::new(ports);
    let mut changed = request;
    changed.budget.maximum_training_steps += 1;
    // The checkpoint and requested input agree with each other, but neither
    // may replace the original frozen request admitted by this owner.
    let snapshot = completed_snapshot(changed.clone(), &ports, decision).await;
    install_checkpoint(&ports, &snapshot);
    let (_, owner) = ok(learning_iteration_channel_scoped_v2(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.owners(),
        ports.clone(),
        ports.verifier.clone(),
        /*capacity*/ 2,
        scope,
    ));
    assert!(matches!(
        owner
            .process_readback(&daemon.state(), changed.clone(), || Ok(60))
            .await,
        Err(LearningIterationRuntimeErrorV1::Validation(
            LearningIterationError::UpdateScopeMismatch
        ))
    ));
    assert!(owner.with_circuit_learning_delivery(changed).is_err());
    assert_no_work_or_checkpoint(&ports, &snapshot);
    assert!(ok(ports.attested.lock()).is_empty());
}
