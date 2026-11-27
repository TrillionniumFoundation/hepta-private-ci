//! Original-role authentication controls with explicit signing fixtures.
//! Native optimizer evidence is exercised separately by the Q24 owner tests.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningTrainingNoUpdateReasonV2;
use codex_hepta_learning_artifacts::LearningTrainingNoUpdateV2;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;

use super::*;
use crate::learning_iteration_channel_scoped_v2;

pub(super) async fn trainer_no_update_snapshot(
    request: LearningIterationRequestV1,
    ports: &IterationPorts,
) -> LearningIterationSnapshotV1 {
    let mut coordinator = ok(LearningIterationCoordinatorV1::new(request, ports.owners()));
    for stage in [
        LearningIterationStageV1::Experience,
        LearningIterationStageV1::Dataset,
    ] {
        let receipt = ok(ports.execute_stage(coordinator.snapshot(), stage).await);
        ok(coordinator.record(receipt, 50));
    }
    let retained_bundle = ok(coordinator.snapshot().request.selected_bundle.digest());
    record_observation(
        &mut coordinator,
        LearningIterationObservationV1::TrainingNoUpdateV2(LearningTrainingNoUpdateV2 {
            retained_bundle,
            dataset: digest("test-dataset"),
            update_rule: digest("test-rule"),
            steps: 2,
            milliseconds: 1,
            reason: LearningTrainingNoUpdateReasonV2::QuantizedWeightsUnchanged,
        }),
    );
    assert!(coordinator.candidate().is_none());
    record_observation(
        &mut coordinator,
        LearningIterationObservationV1::Selection {
            candidate_bundle: retained_bundle,
            selection_digest: digest("fixture-retained-selection"),
        },
    );
    let request = &coordinator.snapshot().request;
    let state_partition = CellStatePartitionV1 {
        principal_id: request.principal_id.clone(),
        agent_id: request.agent_id.clone(),
        cell_id: request.cell_id.clone(),
        run_id: id("run:trainer-no-update-fresh-use"),
    };
    record_observation(
        &mut coordinator,
        LearningIterationObservationV1::RetainedModelNextUse {
            retained_bundle,
            state_partition,
            checkpoint_digest: digest("fixture-fresh-checkpoint"),
            selection_digest: digest("fixture-retained-selection"),
            committed_step_receipt: digest("fixture-actual-step"),
            task_owner_publication: digest("fixture-publication"),
        },
    );
    coordinator.snapshot().clone()
}

fn scoped_runtime(
    daemon: &AgentdFixture,
    ports: &Arc<IterationPorts>,
    scope: FrozenLearningScopeV2,
) -> crate::LearningIterationRuntimeBootstrapV1 {
    ok(learning_iteration_channel_scoped_v2(
        daemon.identity.agent_id.clone(),
        1,
        ports.owners(),
        ports.clone(),
        ports.verifier.clone(),
        2,
        scope,
    ))
    .1
}

#[tokio::test]
async fn trainer_no_update_recovery_authenticates_generator_selector_and_observer_without_evaluator()
 {
    for fault in [
        "none",
        "selector-controller",
        "observer-controller",
        "revoked-observer",
        "training-signature",
        "selection-signature",
    ] {
        let daemon = AgentdFixture::new();
        let trust = match fault {
            "selector-controller" => Trust::SharedSelectorController,
            "observer-controller" => Trust::SharedController,
            "revoked-observer" => Trust::RevokedEvaluator,
            _ => Trust::Independent,
        };
        let mut ports = recovery_ports(Decision::EvaluatedNoUpdate, trust);
        let request = iteration_request(&daemon);
        let scope = ok(FrozenLearningScopeV2::freeze(
            &request,
            &ports.owners(),
            LearningUpdateScopeV2::Cell,
            digest("test-rule"),
        ));
        ports.scope_binding = Some(scope.binding());
        let ports = Arc::new(ports);
        let snapshot = trainer_no_update_snapshot(request, &ports).await;
        install_checkpoint(&ports, &snapshot);
        *ok(ports.corrupt_stage.lock()) = match fault {
            "training-signature" => Some(LearningIterationStageV1::Training),
            "selection-signature" => Some(LearningIterationStageV1::Selection),
            _ => None,
        };
        let result = scoped_runtime(&daemon, &ports, scope)
            .process_readback(&daemon.state(), snapshot.request.clone(), || Ok(60))
            .await;
        if fault == "none" {
            assert_eq!(ok(result), snapshot);
            for stage in [
                LearningIterationStageV1::Training,
                LearningIterationStageV1::Selection,
                LearningIterationStageV1::NextUse,
            ] {
                assert!(ok(ports.attested.lock()).contains(&stage));
            }
        } else {
            assert!(matches!(
                result,
                Err(LearningIterationRuntimeErrorV1::Evidence(_))
            ));
        }
        assert!(!ok(ports.attested.lock()).contains(&LearningIterationStageV1::Evaluation));
        assert!(!ok(ports.attested.lock()).contains(&LearningIterationStageV1::Proposal));
        assert_no_work_or_checkpoint(&ports, &snapshot);
    }
}

#[tokio::test]
async fn trainer_no_update_legacy_or_unfrozen_restore_fails_before_requesting_signatures() {
    for scoped in [false, true] {
        let daemon = AgentdFixture::new();
        let request = iteration_request(&daemon);
        let mut ports = recovery_ports(Decision::EvaluatedNoUpdate, Trust::Independent);
        let scope = ok(FrozenLearningScopeV2::freeze(
            &request,
            &ports.owners(),
            LearningUpdateScopeV2::Cell,
            digest("different-original-rule"),
        ));
        if scoped {
            ports.scope_binding = Some(scope.binding());
        }
        let ports = Arc::new(ports);
        let snapshot = trainer_no_update_snapshot(request, &ports).await;
        install_checkpoint(&ports, &snapshot);
        let runtime = if scoped {
            scoped_runtime(&daemon, &ports, scope)
        } else {
            runtime(&daemon, &ports)
        };
        assert!(
            runtime
                .process_readback(&daemon.state(), snapshot.request.clone(), || Ok(60))
                .await
                .is_err()
        );
        assert!(ok(ports.attested.lock()).is_empty());
        assert_no_work_or_checkpoint(&ports, &snapshot);
    }
}
