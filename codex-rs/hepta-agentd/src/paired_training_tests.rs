//! Required-owner cancellation controls. Synthetic request metadata and a
//! pending future only: these tests do not fabricate a journal or human grant.
use super::*;
use pretty_assertions::assert_eq;

fn pending() -> (
    PendingTraining,
    oneshot::Receiver<Result<PairedTrainingReadResult, AgentdError>>,
) {
    let (reply, response) = oneshot::channel();
    (
        PendingTraining {
            request: PairedPreparationRequest {
                original: PairedTurnRequest {
                    turn_id: "synthetic-owner-turn".into(),
                    delivery_id: Digest32::of_bytes(b"synthetic delivery"),
                    study: Digest32::of_bytes(b"synthetic study"),
                    expected_principal: "synthetic-person".into(),
                    usage: PairedLearningDataUse::TrainOnFailureAndCorrection {
                        failure: Digest32::of_bytes(b"failure"),
                        correction: Digest32::of_bytes(b"correction"),
                    },
                },
                operation: Digest32::of_bytes(b"synthetic operation"),
                materials: Digest32::of_bytes(b"synthetic materials"),
            },
            deadline: Instant::now() + Duration::from_secs(1),
            reply,
            preparing: Arc::new(AtomicBool::new(true)),
        },
        response,
    )
}

struct Released(Option<oneshot::Sender<()>>);
impl Drop for Released {
    fn drop(&mut self) {
        if let Some(sender) = self.0.take() {
            let _ = sender.send(());
        }
    }
}

#[tokio::test]
async fn paired_training_required_owner_cancel_drops_read_and_returns_unknown() {
    let (pending, response) = pending();
    let delivery = pending.request.original.delivery_id;
    let cancellation = CancellationToken::new();
    let original = cancellation.clone();
    let (started_tx, started_rx) = oneshot::channel();
    let (released_tx, released_rx) = oneshot::channel();
    let owned = Released(Some(released_tx));
    let task = tokio::spawn(async move {
        pending
            .complete_on_owner(&original, async move {
                let _owned = owned;
                started_tx.send(()).unwrap();
                std::future::pending().await
            })
            .await
    });
    tokio::time::timeout(Duration::from_secs(2), started_rx)
        .await
        .unwrap()
        .unwrap();
    cancellation.cancel();
    tokio::time::timeout(Duration::from_secs(2), task)
        .await
        .unwrap()
        .unwrap();
    tokio::time::timeout(Duration::from_secs(2), released_rx)
        .await
        .unwrap()
        .unwrap();
    let value = response.await.unwrap().unwrap();
    let PairedTrainingReadResult::Unknown { original_delivery } = value else {
        panic!("cancelled owner cannot return a read result");
    };
    assert_eq!(original_delivery, delivery);
}

#[tokio::test]
async fn paired_training_caller_abort_drops_the_active_read_without_retry() {
    let (pending, response) = pending();
    let original = CancellationToken::new();
    let (started_tx, started_rx) = oneshot::channel();
    let (released_tx, released_rx) = oneshot::channel();
    let owned = Released(Some(released_tx));
    let task = tokio::spawn(async move {
        pending
            .complete_on_owner(&original, async move {
                let _owned = owned;
                started_tx.send(()).unwrap();
                std::future::pending().await
            })
            .await
    });
    tokio::time::timeout(Duration::from_secs(2), started_rx)
        .await
        .unwrap()
        .unwrap();
    drop(response);
    tokio::time::timeout(Duration::from_secs(2), task)
        .await
        .unwrap()
        .unwrap();
    tokio::time::timeout(Duration::from_secs(2), released_rx)
        .await
        .unwrap()
        .unwrap();
}

#[path = "paired_training_readiness_tests.rs"]
mod readiness;
