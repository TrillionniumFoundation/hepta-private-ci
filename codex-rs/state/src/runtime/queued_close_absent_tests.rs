use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn original_close_absent_survives_reopen_and_fences_late_admission() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let client = "hepta.authbus:expired-original";
    let digest = test_digest('a');
    let payload = bound_payload(client, "prepared input");
    let QueuedClientBindingReserveOutcome::Reserved(lease) = runtime
        .thread_queue()
        .reserve_client_binding(thread_id, client, &digest, &payload)
        .await
        .unwrap()
    else {
        panic!("original reservation required")
    };
    let outcome = runtime
        .thread_queue()
        .finalize_client_binding(QueuedClientBindingFinalizeRequest {
            thread_id,
            client_id: client.into(),
            payload_sha256: digest.clone(),
            payload_json: payload.clone(),
            lease: lease.clone(),
            mode: QueuedClientBindingFinalizeMode::CloseIfAbsent,
            observed_turn_id: None,
            runtime_capacity: None,
        })
        .await
        .unwrap();
    assert_eq!(outcome, QueuedClientBindingFinalizeOutcome::Cancelled);
    // Reopen the original owner before releasing the old reservation.
    // The stale request retains its exact input and reservation identity.
    let sqlite = runtime.sqlite().clone();
    drop(runtime);
    let runtime = StateRuntime::init(sqlite, "test-provider".into())
        .await
        .unwrap();
    let pool = runtime.thread_queue().pool.clone();
    let durable: String = sqlx::query_scalar("SELECT state FROM queued_client_bindings WHERE thread_id = ? AND client_user_message_id = ?")
        .bind(thread_id.to_string()).bind(client).fetch_one(pool.as_ref()).await.unwrap();
    assert_eq!(durable, "cancelled");
    assert_eq!(
        runtime
            .thread_queue()
            .finalize_client_binding(QueuedClientBindingFinalizeRequest {
                thread_id,
                client_id: client.into(),
                payload_sha256: digest.clone(),
                payload_json: payload.clone(),
                lease,
                mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
                observed_turn_id: None,
                runtime_capacity: None,
            })
            .await
            .unwrap(),
        QueuedClientBindingFinalizeOutcome::Cancelled
    );
    assert!(matches!(
        runtime
            .thread_queue()
            .reserve_client_binding(thread_id, client, &digest, &payload)
            .await
            .unwrap(),
        QueuedClientBindingReserveOutcome::Cancelled
    ));
    assert!(
        runtime
            .thread_queue()
            .list_page(thread_id, 0, MAX_QUEUE_ITEMS)
            .await
            .unwrap()
            .is_empty()
    );
    assert_binding_conflict(
        runtime
            .thread_queue()
            .reserve_client_binding(thread_id, client, &test_digest('b'), &payload)
            .await,
        "changed closed payload",
    );
}

#[tokio::test]
async fn close_absent_preserves_already_queued_or_observed_turn() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let client = "hepta.authbus:already-queued";
    let digest = test_digest('c');
    let payload = bound_payload(client, "existing input");
    let QueuedClientBindingReserveOutcome::Reserved(lease) = runtime
        .thread_queue()
        .reserve_client_binding(thread_id, client, &digest, &payload)
        .await
        .unwrap()
    else {
        panic!("original reservation required")
    };
    let request = QueuedClientBindingFinalizeRequest {
        thread_id,
        client_id: client.into(),
        payload_sha256: digest,
        payload_json: payload,
        lease,
        mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
        observed_turn_id: None,
        runtime_capacity: None,
    };
    let first = runtime
        .thread_queue()
        .finalize_client_binding(request.clone())
        .await
        .unwrap();
    let QueuedClientBindingFinalizeOutcome::Queued { record, .. } = first else {
        panic!("original queued item required")
    };
    let closed = runtime
        .thread_queue()
        .finalize_client_binding(QueuedClientBindingFinalizeRequest {
            mode: QueuedClientBindingFinalizeMode::CloseIfAbsent,
            ..request.clone()
        })
        .await
        .unwrap();
    assert_eq!(
        closed,
        QueuedClientBindingFinalizeOutcome::Queued {
            record,
            created: false
        }
    );
    assert_eq!(
        runtime
            .thread_queue()
            .finalize_client_binding(QueuedClientBindingFinalizeRequest {
                mode: QueuedClientBindingFinalizeMode::CloseIfAbsent,
                observed_turn_id: Some("original-turn".into()),
                ..request
            })
            .await
            .unwrap(),
        QueuedClientBindingFinalizeOutcome::Persisted {
            turn_id: "original-turn".into()
        }
    );
}
