use super::*;
use std::sync::Arc;

use codex_hepta_infer_core::durable_control::native::NativeRequest;
use tokio::sync::Notify;

#[tokio::test]
async fn cancelled_checkout_returns_the_same_journal_owner() {
    let directory = tempfile::tempdir().unwrap();
    let control =
        DurableInferenceControl::open(directory.path().join("native.journal"), 8).unwrap();
    let owner = Arc::new(NativeIntelligenceControlOwnerV1::new(control));
    let expected = NativeRequest {
        request_id: "run.control-owner".to_string(),
        principal_id: "agent.control-owner".to_string(),
        worker_generation: 1,
        model: "model".to_string(),
        payload_digest: "a".repeat(64),
    };
    let reserved = Arc::new(Notify::new());
    let worker_owner = Arc::clone(&owner);
    let worker_reserved = Arc::clone(&reserved);
    let worker_request = expected.clone();
    let worker = tokio::spawn(async move {
        let mut checkout = worker_owner.checkout().unwrap();
        checkout
            .control
            .as_mut()
            .unwrap()
            .reserve_native(worker_request, 1)
            .unwrap();
        worker_reserved.notify_one();
        std::future::pending::<()>().await;
    });
    reserved.notified().await;
    assert!(owner.checkout().is_err(), "live checkout remains exclusive");
    worker.abort();
    assert!(worker.await.unwrap_err().is_cancelled());
    let checkout = owner.checkout().expect("cancellation returns the journal");
    assert_eq!(
        checkout
            .control
            .as_ref()
            .unwrap()
            .native_record("run.control-owner")
            .unwrap()
            .request,
        expected,
    );
    drop(checkout);
    assert!(
        owner.checkout().is_ok(),
        "the same owner can be checked out again"
    );
}
