//! Valid signatures cannot replace the plan frozen by the original owner.

use codex_hepta_learning_artifacts::LearningIterationError;

use super::*;

#[tokio::test]
async fn signed_training_profile_drift_stops_before_evaluator_and_cannot_rebind_restore() {
    let daemon = AgentdFixture::new();
    let state = daemon.state();
    let ports = Arc::new(IterationPorts::new(
        /*proposal*/ None,
        LearningEvaluationDispositionV1::NoUpdate,
    ));
    let (_, owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.owners(),
        ports.clone(),
        ports.verifier.clone(),
        /*capacity*/ 2,
    ));
    // The deterministic trainer still returns its independently signed
    // "frozen-evaluation" lineage. The owner froze a different profile first.
    let mut request = iteration_request(&daemon);
    request.evaluation_profile = digest("owner-preregistered-evaluation");
    assert!(matches!(
        owner.process(&state, request.clone(), || Ok(50)).await,
        Err(LearningIterationRuntimeErrorV1::Validation(
            LearningIterationError::ContextMismatch
        ))
    ));
    let executed = vec![
        LearningIterationStageV1::Experience,
        LearningIterationStageV1::Dataset,
        LearningIterationStageV1::Training,
    ];
    assert_eq!(ok(ports.executed.lock()).clone(), executed);
    assert_eq!(ok(ports.attested.lock()).clone(), executed);
    let saved = ok(ports.checkpoint.lock())
        .clone()
        .expect("dataset checkpoint");
    assert_eq!(saved.request, request);
    assert_eq!(saved.receipts.len(), 2);
    let checkpoint_calls = ok(ports.checkpoint_calls.lock()).clone();
    assert_eq!(checkpoint_calls.len(), 3);

    // A retry with the trainer's preferred profile changes the original
    // operation context. Restore refuses it without any further owner call.
    assert!(matches!(
        owner
            .process(&state, iteration_request(&daemon), || Ok(50))
            .await,
        Err(LearningIterationRuntimeErrorV1::WrongScope)
    ));
    assert_eq!(ok(ports.executed.lock()).clone(), executed);
    assert_eq!(ok(ports.attested.lock()).clone(), executed);
    assert_eq!(ok(ports.checkpoint_calls.lock()).clone(), checkpoint_calls);
    assert_eq!(ok(ports.checkpoint.lock()).clone(), Some(saved));
}
