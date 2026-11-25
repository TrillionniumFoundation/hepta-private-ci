//! Bounded in-process transport controls, not a substitute Root or participant.
use super::*;

fn request() -> PairedTurnRequest {
    PairedTurnRequest {
        turn_id: "retained-turn".into(),
        delivery_id: Digest32::of_bytes(b"retained delivery"),
        study: Digest32::of_bytes(b"frozen study"),
        usage: PairedLearningDataUse::EvaluateOnlyAfterFreeze {
            freeze: Digest32::of_bytes(b"frozen candidate"),
            task: Digest32::of_bytes(b"unexposed task"),
        },
        expected_principal: "original-person".into(),
    }
}

#[tokio::test]
async fn invalid_request_never_occupies_the_original_owner() {
    let (verifier, mut receiver) = channel();
    let mut invalid = request();
    invalid.usage = PairedLearningDataUse::TrainOnFailureAndCorrection {
        failure: Digest32::ZERO,
        correction: Digest32::of_bytes(b"a correction"),
    };
    assert!(verifier.verify(invalid).await.is_err());
    assert!(matches!(
        receiver.try_recv(),
        Err(mpsc::error::TryRecvError::Empty)
    ));
}

#[tokio::test]
async fn occupied_and_closed_original_owners_refuse_without_reconnecting() {
    let (verifier, mut receiver) = channel();
    let verifier = std::sync::Arc::new(verifier);
    let first = {
        let verifier = std::sync::Arc::clone(&verifier);
        tokio::spawn(async move { verifier.verify(request()).await })
    };
    tokio::time::timeout(Duration::from_secs(1), async {
        while verifier.sender.capacity() != 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert!(verifier.verify(request()).await.is_err());
    let pending = receiver.recv().await.unwrap();
    assert!(pending.deadline > Instant::now());
    assert!(
        pending
            .reply
            .send(Err(invalid("original Root refused")))
            .is_ok()
    );
    assert!(first.await.unwrap().is_err());
    drop(receiver);
    assert!(verifier.verify(request()).await.is_err());
}

#[tokio::test]
async fn cancelled_caller_leaves_no_request_to_authorize() {
    let (verifier, mut receiver) = channel();
    let task = tokio::spawn(async move { verifier.verify(request()).await });
    let pending = receiver.recv().await.unwrap();
    task.abort();
    assert!(matches!(task.await, Err(error) if error.is_cancelled()));
    assert!(pending.reply.is_closed());
}

#[tokio::test]
async fn owner_cancellation_interrupts_an_in_progress_verification() {
    let (verifier, mut receiver) = channel();
    let client = tokio::spawn(async move { verifier.verify(request()).await });
    let pending = receiver.recv().await.unwrap();
    let cancellation = CancellationToken::new();
    let owner_token = cancellation.clone();
    let (started, entered) = oneshot::channel();
    let owner = tokio::spawn(async move {
        pending
            .verify_on_owner(&owner_token, async {
                let _ = started.send(());
                // The actual owner wait is exercised; no human proof is invented.
                std::future::pending().await
            })
            .await;
    });
    entered.await.unwrap();
    cancellation.cancel();
    tokio::time::timeout(Duration::from_secs(1), owner)
        .await
        .unwrap()
        .unwrap();
    let result = client.await.unwrap();
    assert!(matches!(result, Err(error) if error.to_string().contains("owner was cancelled")));
}

#[tokio::test]
async fn expired_waiting_request_never_polls_original_verification() {
    let (verifier, mut receiver) = channel();
    let client = tokio::spawn(async move { verifier.verify(request()).await });
    let mut pending = receiver.recv().await.unwrap();
    pending.deadline = Instant::now() - Duration::from_secs(1);
    pending
        .verify_on_owner(&CancellationToken::new(), async {
            panic!("an expired request reached original verification");
        })
        .await;
    let result = client.await.unwrap();
    assert!(matches!(result, Err(error) if error.to_string().contains("deadline elapsed")));
}

#[tokio::test]
async fn caller_exit_releases_an_in_progress_verification_future() {
    struct ReleaseOnDrop(Option<oneshot::Sender<()>>);
    impl Drop for ReleaseOnDrop {
        fn drop(&mut self) {
            if let Some(sender) = self.0.take() {
                let _ = sender.send(());
            }
        }
    }

    let (verifier, mut receiver) = channel();
    let client = tokio::spawn(async move { verifier.verify(request()).await });
    let pending = receiver.recv().await.unwrap();
    let (started, entered) = oneshot::channel();
    let (released, observed) = oneshot::channel();
    let owner = tokio::spawn(async move {
        pending
            .verify_on_owner(&CancellationToken::new(), async {
                let _release = ReleaseOnDrop(Some(released));
                let _ = started.send(());
                std::future::pending().await
            })
            .await;
    });
    entered.await.unwrap();
    client.abort();
    assert!(matches!(client.await, Err(error) if error.is_cancelled()));
    tokio::time::timeout(Duration::from_secs(1), owner)
        .await
        .unwrap()
        .unwrap();
    observed.await.unwrap();
}
