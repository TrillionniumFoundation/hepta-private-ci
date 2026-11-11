use super::*;
use pretty_assertions::assert_eq;
use std::sync::Mutex;
use std::sync::mpsc;
use std::time::Duration;

struct BlockingIssuer {
    entered: tokio::sync::Notify,
    release: Mutex<mpsc::Receiver<()>>,
}

impl AgentdFinalUseGrantProvider for BlockingIssuer {
    fn signed_grant(&self, _binding: &FinalUseBinding) -> Result<SignedFinalUseGrant, AgentdError> {
        self.entered.notify_one();
        // A failed assertion cannot leave the test runtime waiting forever.
        let _ = self
            .release
            .lock()
            .unwrap()
            .recv_timeout(Duration::from_secs(2));
        Err(AgentdError::Protocol(
            "isolated test issuer denial".to_string(),
        ))
    }
}

fn binding() -> FinalUseBinding {
    FinalUseBinding {
        subject_id: "test-agent".into(),
        destination_id: "test-target".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    }
}

#[tokio::test]
async fn cancelled_waiter_does_not_release_capacity_held_by_the_original_worker() {
    let (release, receiver) = mpsc::channel();
    let issuer = Arc::new(BlockingIssuer {
        entered: tokio::sync::Notify::new(),
        release: Mutex::new(receiver),
    });
    let worker = Arc::new(GrantProviderWorker::new(issuer.clone()));
    let task_worker = Arc::clone(&worker);
    let first = tokio::spawn(async move { task_worker.signed_grant(&binding()).await });
    tokio::time::timeout(Duration::from_secs(1), issuer.entered.notified())
        .await
        .unwrap();
    // This also proves that a slow issuer did not block the current-thread
    // executor: its notification and this cancellation can run concurrently.
    first.abort();
    assert!(first.await.unwrap_err().is_cancelled());
    let overloaded = worker.signed_grant(&binding()).await;
    release.send(()).unwrap();
    assert!(matches!(overloaded, Err(AgentdError::Overloaded { .. })));
    let permit = tokio::time::timeout(
        Duration::from_secs(1),
        Arc::clone(&worker.gate).acquire_owned(),
    )
    .await
    .unwrap()
    .unwrap();
    drop(permit);
    assert_eq!(worker.gate.available_permits(), 1);
}
