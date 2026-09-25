//! Exercise the existing canonical product caller with real durable Neuron
//! state. The feature/calibration fixtures are not deployment qualification.
use super::*;
use std::sync::Arc;
use std::sync::atomic::Ordering;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn currentness_change_during_model_execution_prevents_durable_preparation() {
    let (value, trust) = signed_fixture();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority.json");
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let control = Arc::clone(&value.neuron_control);
    let owners = value.owners.clone();
    let changed_path = path.clone();
    control.after_execute(move || {
        write_authority_file(&changed_path, &owners, digest("revoked-frontier"))
    });
    let before = control.operation_bytes();
    let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("trust");
    let result = runner
        .prepare(&product_test_coordinator(), value.request, value.inputs)
        .await;
    assert!(matches!(
        result,
        Err(AgentdIntelligenceProductError::Canonical(
            CanonicalIntelligenceError::PortFailure {
                stage: CanonicalStageV1::NeuralSignalCollected,
                class: CanonicalPortFailureClassV1::Rejected,
                ..
            }
        ))
    ));
    assert_eq!(control.calls.load(Ordering::SeqCst), 1);
    assert_eq!(control.operation_bytes(), before);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ood_neuron_result_cannot_become_a_ready_fast_policy() {
    let (value, trust) = signed_fixture();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority.json");
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let control = Arc::clone(&value.neuron_control);
    control.force_ood.store(true, Ordering::SeqCst);
    let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("trust");
    assert!(matches!(
        runner
            .prepare(&product_test_coordinator(), value.request, value.inputs)
            .await,
        Err(AgentdIntelligenceProductError::Canonical(
            CanonicalIntelligenceError::PortFailure {
                stage: CanonicalStageV1::NeuralSignalCollected,
                class: CanonicalPortFailureClassV1::Unavailable,
                ..
            }
        ))
    ));
    assert_eq!(control.calls.load(Ordering::SeqCst), 1);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn repeated_product_invocation_uses_the_same_durable_neuron_result() {
    let (value, trust) = signed_fixture();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority.json");
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let control = Arc::clone(&value.neuron_control);
    let invocation = value.inputs.neuron.clone();
    // Retry the same signed evaluation under the original activated trust.
    // Rebuilding signed_fixture creates a new time-bound trust distribution.
    let signed_evaluation = value.inputs.signed_evaluation.clone();
    let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("trust");
    let first = runner
        .prepare(&product_test_coordinator(), value.request, value.inputs)
        .await
        .expect("first product result");
    let (mut value, _) = signed_fixture();
    value.inputs.neuron = invocation;
    value.inputs.signed_evaluation = signed_evaluation;
    let second = runner
        .prepare(&product_test_coordinator(), value.request, value.inputs)
        .await
        .expect("repeated product result");
    let (
        AgentdIntelligenceProductOutcomeV1::Ready(first),
        AgentdIntelligenceProductOutcomeV1::Ready(second),
    ) = (first, second)
    else {
        panic!("expected ready results");
    };
    assert_eq!(
        first.envelope.neural_receipt_digest,
        second.envelope.neural_receipt_digest
    );
    assert_eq!(control.calls.load(Ordering::SeqCst), 1);
}
