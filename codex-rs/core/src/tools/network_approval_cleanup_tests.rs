use super::*;
use std::sync::mpsc;
use tokio::time::Instant;

fn call_state(service: &NetworkApprovalService) -> (Vec<String>, HashMap<String, String>) {
    let calls = service
        .calls
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    (
        calls.active_calls.keys().cloned().collect(),
        calls.call_outcomes.clone(),
    )
}

#[tokio::test]
async fn held_call_lock_returns_unconfirmed_without_deferred_cleanup() {
    let service = Arc::new(NetworkApprovalService::default());
    register_call_with_default_shell_trigger(&service, "original").await;
    let before = call_state(&service);
    let calls = service.calls.lock().expect("call lock");
    let deadline = Instant::now() + Duration::from_secs(2);
    let (sent, received) = mpsc::channel();
    let worker_service = Arc::clone(&service);
    let worker = std::thread::spawn(move || {
        let result = worker_service.try_unregister_call_until("original", deadline);
        sent.send(result).expect("result receiver");
    });
    let result = received.recv_timeout(Duration::from_secs(2));
    drop(calls);
    worker.join().expect("cleanup worker");
    assert_eq!(result, Ok(false));
    assert_eq!(call_state(&service), before);
}

#[tokio::test]
async fn expired_cleanup_deadline_preserves_exact_registration_and_outcome() {
    let service = NetworkApprovalService::default();
    register_call_with_default_shell_trigger(&service, "original").await;
    service
        .calls
        .lock()
        .expect("call lock")
        .call_outcomes
        .insert("original".to_string(), "original denial".to_string());
    let before = call_state(&service);
    assert!(!service.try_unregister_call_until("original", Instant::now()));
    assert_eq!(call_state(&service), before);
}

#[tokio::test]
async fn cleanup_removes_only_original_registration_and_its_outcome() {
    let service = NetworkApprovalService::default();
    register_call_with_default_shell_trigger(&service, "original").await;
    register_call_with_default_shell_trigger(&service, "replacement").await;
    {
        let mut calls = service.calls.lock().expect("call lock");
        calls
            .call_outcomes
            .insert("original".to_string(), "original denial".to_string());
        calls
            .call_outcomes
            .insert("replacement".to_string(), "replacement denial".to_string());
    }
    assert!(
        service.try_unregister_call_until("original", Instant::now() + Duration::from_secs(2),)
    );
    assert_eq!(
        call_state(&service),
        (
            vec!["replacement".to_string()],
            HashMap::from([("replacement".to_string(), "replacement denial".to_string())]),
        ),
    );
}

#[tokio::test]
async fn missing_registration_cleanup_does_not_remove_replacement() {
    let service = NetworkApprovalService::default();
    register_call_with_default_shell_trigger(&service, "replacement").await;
    let before = call_state(&service);
    assert!(
        service.try_unregister_call_until("original", Instant::now() + Duration::from_secs(2),)
    );
    assert_eq!(call_state(&service), before);
}

#[tokio::test]
async fn poisoned_call_lock_keeps_existing_recovery_semantics() {
    let service = NetworkApprovalService::default();
    register_call_with_default_shell_trigger(&service, "original").await;
    let poisoned = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _calls = service.calls.lock().expect("call lock");
        panic!("poison the call lock");
    }));
    assert!(poisoned.is_err());
    assert!(service.calls.is_poisoned());
    assert!(
        service.try_unregister_call_until("original", Instant::now() + Duration::from_secs(2),)
    );
    assert_eq!(call_state(&service), (Vec::new(), HashMap::new()));
}
