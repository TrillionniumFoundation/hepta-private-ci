//! Scheduling/ownership controls use a synthetic internal lane, never a human
//! proof, material capability or trained model. The real lane keeps all checks.
use super::*;
use pretty_assertions::assert_eq;

fn fixture() -> (
    OriginalPairedTrainingConsumer,
    oneshot::Sender<PairedPreparationRequest>,
    oneshot::Receiver<OriginalPairedTrainingDelivery>,
    mpsc::Receiver<PendingTraining>,
    PairedPreparationRequest,
) {
    let registration = PairedPreparationRegistration {
        study: Digest32::of_bytes(b"study"),
        enrollment: Digest32::of_bytes(b"enrollment"),
        frozen_materials: Digest32::of_bytes(b"materials"),
        principal_id: "synthetic-human".into(),
        policy_generation: Generation::new(1).unwrap(),
    };
    let request = PairedPreparationRequest {
        original: PairedTurnRequest {
            turn_id: "original-turn".into(),
            delivery_id: Digest32::of_bytes(b"delivery"),
            study: registration.study,
            expected_principal: registration.principal_id.clone(),
            usage: PairedLearningDataUse::TrainOnFailureAndCorrection {
                failure: Digest32::of_bytes(b"failure"),
                correction: Digest32::of_bytes(b"correction"),
            },
        },
        operation: Digest32::of_bytes(b"operation"),
        materials: registration.frozen_materials,
    };
    let (sender, requests) = mpsc::channel(1);
    let training = AgentdPairedTraining {
        sender,
        registration,
    };
    let (hint, receiver) = oneshot::channel();
    let (consumer, delivery) = OriginalPairedTrainingConsumer::new(training, receiver);
    (consumer, hint, delivery, requests, request)
}

#[tokio::test]
async fn paired_consumer_moves_exact_request_and_read_result_then_remains_joined() {
    let (consumer, hint, delivery, mut requests, request) = fixture();
    let cancellation = CancellationToken::new();
    let task = tokio::spawn(consumer.run(cancellation.clone()));
    hint.send(request.clone()).unwrap();
    let pending = requests.recv().await.unwrap();
    assert_eq!(pending.request, request);
    assert!(
        pending
            .reply
            .send(Ok(PairedTrainingReadResult::RetainedReadOnly {
                original_delivery: request.original.delivery_id,
            }))
            .is_ok()
    );
    let actual = delivery.await.unwrap();
    assert_eq!(actual.request, request);
    assert!(
        matches!(actual.result, Ok(PairedTrainingReadResult::RetainedReadOnly { original_delivery }) if original_delivery == request.original.delivery_id)
    );
    assert!(!task.is_finished());
    assert!(matches!(
        requests.try_recv(),
        Err(mpsc::error::TryRecvError::Empty)
    ));
    cancellation.cancel();
    task.await.unwrap().unwrap();
}

#[tokio::test]
async fn paired_consumer_closed_material_owner_never_dispatches_a_read() {
    let (consumer, hint, delivery, mut requests, request) = fixture();
    drop(delivery);
    hint.send(request).unwrap();
    assert!(consumer.run(CancellationToken::new()).await.is_err());
    assert!(matches!(
        requests.try_recv(),
        Err(mpsc::error::TryRecvError::Disconnected)
    ));
}

#[tokio::test]
async fn paired_consumer_owner_loss_cancels_the_original_pending_read() {
    let (consumer, hint, delivery, mut requests, request) = fixture();
    let task = tokio::spawn(consumer.run(CancellationToken::new()));
    hint.send(request).unwrap();
    let pending = requests.recv().await.unwrap();
    drop(delivery);
    assert!(task.await.unwrap().is_err());
    assert!(pending.reply.is_closed());
    assert!(matches!(
        requests.try_recv(),
        Err(mpsc::error::TryRecvError::Disconnected)
    ));
}

#[tokio::test]
async fn paired_consumer_returns_original_refusal_without_new_hint_or_retry() {
    let (consumer, hint, delivery, mut requests, request) = fixture();
    let cancellation = CancellationToken::new();
    let task = tokio::spawn(consumer.run(cancellation.clone()));
    hint.send(request.clone()).unwrap();
    let pending = requests.recv().await.unwrap();
    assert!(
        pending
            .reply
            .send(Err(invalid("synthetic original owner refusal")))
            .is_ok()
    );
    let actual = delivery.await.unwrap();
    assert_eq!(actual.request, request);
    assert!(actual.result.is_err());
    assert!(matches!(
        requests.try_recv(),
        Err(mpsc::error::TryRecvError::Empty)
    ));
    cancellation.cancel();
    task.await.unwrap().unwrap();
}
