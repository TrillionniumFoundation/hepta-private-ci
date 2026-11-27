use super::*;
use crate::learning_iteration_channel_scoped_v2;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn scoped_circuit_enrollment_rejects_rebound_request_before_owner_work() {
    for rebound in [false, true] {
        let daemon = AgentdFixture::new();
        let mut request = iteration_request(&daemon);
        let mut ports = IterationPorts::new(None, LearningEvaluationDispositionV1::NoUpdate);
        let scope = ok(FrozenLearningScopeV2::freeze(
            &request,
            &ports.owners(),
            LearningUpdateScopeV2::Cell,
            digest("test-rule"),
        ));
        ports.scope_binding = Some(scope.binding());
        let ports = Arc::new(ports);
        let (_, owner) = ok(learning_iteration_channel_scoped_v2(
            daemon.identity.agent_id.clone(),
            /*spawn_generation*/ 1,
            ports.owners(),
            ports.clone(),
            ports.verifier.clone(),
            /*capacity*/ 2,
            scope,
        ));
        if rebound {
            request.budget.maximum_training_steps += 1;
        }
        let enrolled = owner.with_circuit_learning_delivery(request.clone());
        if rebound {
            assert!(enrolled.is_err());
        } else {
            let mut enrolled = ok(enrolled);
            assert_eq!(
                ok(enrolled.take_circuit_delivery().ok_or("delivery")).requests,
                vec![request]
            );
        }
        assert!(ok(ports.executed.lock()).is_empty());
        assert!(ok(ports.attested.lock()).is_empty());
        assert!(ok(ports.checkpoint_calls.lock()).is_empty());
        assert!(ok(ports.checkpoint.lock()).is_none());
    }
}

#[tokio::test]
async fn scoped_native_runtime_stops_cross_cadence_training_before_evaluation_or_checkpoint() {
    let changes: [fn(&mut CellCompatibilityBundleV1); 3] = [
        |c| c.components.base = digest("other-base"),
        |c| c.components.organ_adapter = Some(digest("other-organ")),
        |c| c.components.tokenizer = digest("other-tokenizer"),
    ];
    for change in changes {
        let daemon = AgentdFixture::new();
        let request = iteration_request(&daemon);
        let mut ports = IterationPorts::new(None, LearningEvaluationDispositionV1::NoUpdate);
        let scope = ok(FrozenLearningScopeV2::freeze(
            &request,
            &ports.owners(),
            LearningUpdateScopeV2::Cell,
            digest("test-rule"),
        ));
        ports.scope_binding = Some(scope.binding());
        ports.training_mutation = Some(change);
        let ports = Arc::new(ports);
        let (_, owner) = ok(learning_iteration_channel_scoped_v2(
            daemon.identity.agent_id.clone(),
            1,
            ports.owners(),
            ports.clone(),
            ports.verifier.clone(),
            2,
            scope,
        ));
        assert!(matches!(
            owner.process(&daemon.state(), request, || Ok(50)).await,
            Err(LearningIterationRuntimeErrorV1::Validation(
                LearningIterationError::UpdateScopeMismatch
            ))
        ));
        assert_eq!(
            ok(ports.executed.lock()).clone(),
            vec![
                LearningIterationStageV1::Experience,
                LearningIterationStageV1::Dataset,
                LearningIterationStageV1::Training
            ]
        );
        assert_eq!(
            ok(ports.checkpoint.lock())
                .as_ref()
                .map(|s| s.receipts.len()),
            Some(2)
        );
    }
}

#[tokio::test]
async fn scoped_native_no_update_reaches_selection_and_refuses_later_rebound_request() {
    let daemon = AgentdFixture::new();
    let request = iteration_request(&daemon);
    let mut ports = IterationPorts::new(None, LearningEvaluationDispositionV1::NoUpdate);
    let scope = ok(FrozenLearningScopeV2::freeze(
        &request,
        &ports.owners(),
        LearningUpdateScopeV2::Cell,
        digest("test-rule"),
    ));
    assert!(
        learning_iteration_channel_scoped_v2(
            daemon.identity.agent_id.clone(),
            1,
            ports.owners(),
            Arc::new(IterationPorts::new(
                None,
                LearningEvaluationDispositionV1::NoUpdate
            )),
            ports.verifier.clone(),
            2,
            scope.clone()
        )
        .is_err()
    );
    ports.scope_binding = Some(scope.binding());
    let ports = Arc::new(ports);
    assert!(
        learning_iteration_channel_v1(
            daemon.identity.agent_id.clone(),
            1,
            ports.owners(),
            ports.clone(),
            ports.verifier.clone(),
            2
        )
        .is_err()
    );
    let (_, owner) = ok(learning_iteration_channel_scoped_v2(
        daemon.identity.agent_id.clone(),
        1,
        ports.owners(),
        ports.clone(),
        ports.verifier.clone(),
        2,
        scope,
    ));
    assert!(matches!(
        owner
            .process(&daemon.state(), request.clone(), || Ok(50))
            .await,
        Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
            "unexpected downstream stage"
        ))
    ));
    let before = ok(ok(ports.checkpoint.lock())
        .clone()
        .ok_or("missing selection cut"));
    assert_eq!(
        ok(LearningIterationCoordinatorV1::from_snapshot(
            before.clone()
        ))
        .disposition(),
        LearningIterationDispositionV1::NoUpdate
    );
    let executed = ok(ports.executed.lock()).clone();
    let mut changed = request;
    changed.budget.maximum_training_steps += 1;
    assert!(matches!(
        owner.process(&daemon.state(), changed, || Ok(50)).await,
        Err(LearningIterationRuntimeErrorV1::Validation(
            LearningIterationError::UpdateScopeMismatch
        ))
    ));
    assert_eq!(ok(ports.checkpoint.lock()).as_ref(), Some(&before));
    assert_eq!(*ok(ports.executed.lock()), executed);
}

#[tokio::test]
async fn scoped_readback_rechecks_training_before_requesting_any_attestation() {
    let daemon = AgentdFixture::new();
    let request = iteration_request(&daemon);
    let mut original = IterationPorts::new(None, LearningEvaluationDispositionV1::NoUpdate);
    original.training_mutation =
        Some(|candidate| candidate.components.encoder = digest("changed-encoder"));
    let scope = ok(FrozenLearningScopeV2::freeze(
        &request,
        &original.owners(),
        LearningUpdateScopeV2::Cell,
        digest("test-rule"),
    ));
    let original = Arc::new(original);
    let (_, legacy) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        1,
        original.owners(),
        original.clone(),
        original.verifier.clone(),
        2,
    ));
    assert!(matches!(
        legacy
            .process(&daemon.state(), request.clone(), || Ok(50))
            .await,
        Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
            "unexpected downstream stage"
        ))
    ));
    let saved = ok(original.checkpoint.lock()).clone();
    let mut restored = IterationPorts::new(None, LearningEvaluationDispositionV1::NoUpdate);
    restored.scope_binding = Some(scope.binding());
    restored.checkpoint = Mutex::new(saved);
    let restored = Arc::new(restored);
    let (_, scoped) = ok(learning_iteration_channel_scoped_v2(
        daemon.identity.agent_id.clone(),
        1,
        restored.owners(),
        restored.clone(),
        restored.verifier.clone(),
        2,
        scope,
    ));
    assert!(matches!(
        scoped
            .process_readback(&daemon.state(), request, || Ok(50))
            .await,
        Err(LearningIterationRuntimeErrorV1::Validation(
            LearningIterationError::UpdateScopeMismatch
        ))
    ));
    assert!(ok(restored.executed.lock()).is_empty());
    assert!(ok(restored.attested.lock()).is_empty());
    assert!(ok(restored.checkpoint_calls.lock()).is_empty());
}
