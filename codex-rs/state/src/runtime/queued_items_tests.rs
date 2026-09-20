use super::*;
use crate::migrations::QUEUE_MIGRATOR;
use crate::runtime::test_support::test_thread_metadata;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use sqlx::migrate::Migrator;
use std::borrow::Cow;
#[cfg(unix)]
use std::io::Write;
use std::process::Command;

async fn runtime_with_thread() -> (Arc<StateRuntime>, ThreadId) {
    let home = unique_temp_dir();
    let runtime = StateRuntime::init(
        crate::SqliteConfig::new_for_testing(home.as_path().abs()),
        "test-provider".to_string(),
    )
    .await
    .expect("state runtime");
    let thread_id = ThreadId::new();
    let metadata = test_thread_metadata(home.as_path(), thread_id, home.clone());
    runtime.upsert_thread(&metadata).await.unwrap();
    (runtime, thread_id)
}

fn bound_payload(client_id: &str, text: &str) -> String {
    format!(
        r#"{{"UserInput":{{"content":[{{"Text":{{"text":"{text}","text_elements":[]}}}}],"client_id":"{client_id}"}}}}"#
    )
}

fn test_digest(byte: char) -> String {
    std::iter::repeat_n(byte, 64).collect()
}

fn assert_binding_conflict<T>(result: anyhow::Result<T>, context: &str) {
    let error = match result {
        Ok(_) => panic!("{context} unexpectedly succeeded"),
        Err(error) => error,
    };
    assert!(
        error
            .downcast_ref::<QueuedClientBindingConflict>()
            .is_some(),
        "{context} returned an unexpected error: {error:#}"
    );
}

fn assert_delete_seal_trigger(error: impl std::fmt::Display, context: &str) {
    assert!(
        error
            .to_string()
            .contains("thread queue is sealed for deletion"),
        "{context} returned an unexpected SQLite error: {error}"
    );
}

struct RawBinding<'a> {
    client_id: &'a str,
    digest: &'a str,
    state: &'a str,
    queued_item_id: Option<&'a str>,
    turn_id: Option<&'a str>,
    owner_id: Option<&'a str>,
    lease_expires_at_ms: Option<i64>,
    lock_device: Option<i64>,
    lock_inode: Option<i64>,
    revision: i64,
    created_at_ms: i64,
    updated_at_ms: i64,
}

async fn insert_raw_binding(
    runtime: &StateRuntime,
    thread_id: ThreadId,
    binding: RawBinding<'_>,
) -> anyhow::Result<()> {
    sqlx::query(
        "INSERT INTO queued_client_bindings (
            thread_id, client_user_message_id, payload_sha256, state,
            queued_item_id, turn_id, reservation_id, dispatch_owner_id,
            dispatch_lease_expires_at_ms, dispatch_lock_device,
            dispatch_lock_inode, revision, created_at_ms, updated_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, 'reservation', ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(thread_id.to_string())
    .bind(binding.client_id)
    .bind(binding.digest)
    .bind(binding.state)
    .bind(binding.queued_item_id)
    .bind(binding.turn_id)
    .bind(binding.owner_id)
    .bind(binding.lease_expires_at_ms)
    .bind(binding.lock_device)
    .bind(binding.lock_inode)
    .bind(binding.revision)
    .bind(binding.created_at_ms)
    .bind(binding.updated_at_ms)
    .execute(runtime.thread_queue().pool.as_ref())
    .await?;
    Ok(())
}

async fn exact_queued_record(
    runtime: &StateRuntime,
    thread_id: ThreadId,
    client_id: &str,
    digest: &str,
    payload: &str,
) -> QueuedUserSubmissionRecord {
    let QueuedClientBindingReserveOutcome::Reserved(lease) = runtime
        .thread_queue()
        .reserve_client_binding(thread_id, client_id, digest, payload)
        .await
        .unwrap()
    else {
        panic!("new exact identity must reserve");
    };
    let QueuedClientBindingFinalizeOutcome::Queued { record, .. } = runtime
        .thread_queue()
        .finalize_client_binding(QueuedClientBindingFinalizeRequest {
            thread_id,
            client_id: client_id.to_string(),
            payload_sha256: digest.to_string(),
            payload_json: payload.to_string(),
            lease,
            mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
            observed_turn_id: None,
            runtime_capacity: None,
        })
        .await
        .unwrap()
    else {
        panic!("exact reservation must create a queue row");
    };
    record
}

#[tokio::test]
async fn competing_exact_reservations_finalize_one_queue_row() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let other = StateRuntime::init(runtime.sqlite().clone(), "test-provider".to_string())
        .await
        .unwrap();
    let payload = bound_payload("matrix-client", "hello");
    let digest = test_digest('a');

    let (first, second) = tokio::join!(
        runtime.thread_queue().reserve_client_binding(
            thread_id,
            "matrix-client",
            &digest,
            &payload,
        ),
        other
            .thread_queue()
            .reserve_client_binding(thread_id, "matrix-client", &digest, &payload,),
    );
    let QueuedClientBindingReserveOutcome::Reserved(first_lease) = first.unwrap() else {
        panic!("first caller must hold the reservation");
    };
    let QueuedClientBindingReserveOutcome::Reserved(second_lease) = second.unwrap() else {
        panic!("same-payload retry must recover the reservation");
    };
    assert_eq!(first_lease, second_lease);

    let (first, second) = tokio::join!(
        runtime
            .thread_queue()
            .finalize_client_binding(QueuedClientBindingFinalizeRequest {
                thread_id,
                client_id: "matrix-client".to_string(),
                payload_sha256: digest.clone(),
                payload_json: payload.clone(),
                lease: first_lease,
                mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
                observed_turn_id: None,
                runtime_capacity: None,
            },),
        other
            .thread_queue()
            .finalize_client_binding(QueuedClientBindingFinalizeRequest {
                thread_id,
                client_id: "matrix-client".to_string(),
                payload_sha256: digest.clone(),
                payload_json: payload.clone(),
                lease: second_lease,
                mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
                observed_turn_id: None,
                runtime_capacity: None,
            },),
    );
    let outcomes = [first.unwrap(), second.unwrap()];
    assert_eq!(
        1,
        outcomes
            .iter()
            .filter(|outcome| matches!(
                outcome,
                QueuedClientBindingFinalizeOutcome::Queued { created: true, .. }
            ))
            .count()
    );
    assert_eq!(
        1,
        runtime
            .thread_queue()
            .list_page(thread_id, 0, MAX_QUEUE_ITEMS)
            .await
            .unwrap()
            .len()
    );
}

#[tokio::test]
async fn fresh_reconcile_only_missing_removes_its_reservation() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let client_id = "fresh-reconcile-only";
    let digest = test_digest('6');
    let payload = bound_payload(client_id, "observe only");
    let QueuedClientBindingReserveOutcome::Reserved(lease) = runtime
        .thread_queue()
        .reserve_client_binding(thread_id, client_id, &digest, &payload)
        .await
        .unwrap()
    else {
        panic!("fresh exact identity must reserve");
    };
    assert_eq!(
        QueuedClientBindingFinalizeOutcome::Missing,
        runtime
            .thread_queue()
            .finalize_client_binding(QueuedClientBindingFinalizeRequest {
                thread_id,
                client_id: client_id.to_string(),
                payload_sha256: digest.clone(),
                payload_json: payload.clone(),
                lease,
                mode: QueuedClientBindingFinalizeMode::ReconcileOnly,
                observed_turn_id: None,
                runtime_capacity: None,
            })
            .await
            .unwrap()
    );
    let binding_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM queued_client_bindings
         WHERE thread_id = ? AND client_user_message_id = ?",
    )
    .bind(thread_id.to_string())
    .bind(client_id)
    .fetch_one(runtime.thread_queue().pool.as_ref())
    .await
    .unwrap();
    assert_eq!(0, binding_count);
    assert!(
        runtime
            .thread_queue()
            .list_page(thread_id, 0, MAX_QUEUE_ITEMS)
            .await
            .unwrap()
            .is_empty()
    );
}

#[tokio::test]
async fn mixed_allow_and_reconcile_only_runtimes_never_duplicate_a_row() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let other = StateRuntime::init(runtime.sqlite().clone(), "test-provider".to_string())
        .await
        .unwrap();
    let client_id = "mixed-reconcile";
    let digest = test_digest('7');
    let payload = bound_payload(client_id, "mixed modes");
    let QueuedClientBindingReserveOutcome::Reserved(allow_lease) = runtime
        .thread_queue()
        .reserve_client_binding(thread_id, client_id, &digest, &payload)
        .await
        .unwrap()
    else {
        panic!("allow caller must reserve");
    };
    let QueuedClientBindingReserveOutcome::Reserved(reconcile_lease) = other
        .thread_queue()
        .reserve_client_binding(thread_id, client_id, &digest, &payload)
        .await
        .unwrap()
    else {
        panic!("reconcile-only retry must join the reservation");
    };
    let (allow, reconcile_only) = tokio::join!(
        runtime
            .thread_queue()
            .finalize_client_binding(QueuedClientBindingFinalizeRequest {
                thread_id,
                client_id: client_id.to_string(),
                payload_sha256: digest.clone(),
                payload_json: payload.clone(),
                lease: allow_lease,
                mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
                observed_turn_id: None,
                runtime_capacity: None,
            }),
        other
            .thread_queue()
            .finalize_client_binding(QueuedClientBindingFinalizeRequest {
                thread_id,
                client_id: client_id.to_string(),
                payload_sha256: digest.clone(),
                payload_json: payload.clone(),
                lease: reconcile_lease,
                mode: QueuedClientBindingFinalizeMode::ReconcileOnly,
                observed_turn_id: None,
                runtime_capacity: None,
            }),
    );
    for outcome in [allow.unwrap(), reconcile_only.unwrap()] {
        assert!(matches!(
            outcome,
            QueuedClientBindingFinalizeOutcome::Queued { .. }
                | QueuedClientBindingFinalizeOutcome::Missing
        ));
    }
    let rows = runtime
        .thread_queue()
        .list_page(thread_id, 0, MAX_QUEUE_ITEMS)
        .await
        .unwrap();
    assert!(rows.len() <= 1, "mixed modes created duplicate rows");
    if rows.is_empty() {
        let QueuedClientBindingReserveOutcome::Reserved(retry_lease) = runtime
            .thread_queue()
            .reserve_client_binding(thread_id, client_id, &digest, &payload)
            .await
            .unwrap()
        else {
            panic!("AllowIfAbsent retry must reserve after Missing cleanup");
        };
        assert!(matches!(
            runtime
                .thread_queue()
                .finalize_client_binding(QueuedClientBindingFinalizeRequest {
                    thread_id,
                    client_id: client_id.to_string(),
                    payload_sha256: digest,
                    payload_json: payload,
                    lease: retry_lease,
                    mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
                    observed_turn_id: None,
                    runtime_capacity: None,
                })
                .await
                .unwrap(),
            QueuedClientBindingFinalizeOutcome::Queued { .. }
        ));
    }
    assert_eq!(
        1,
        runtime
            .thread_queue()
            .list_page(thread_id, 0, MAX_QUEUE_ITEMS)
            .await
            .unwrap()
            .len()
    );
}

#[tokio::test]
async fn reserved_binding_survives_runtime_crash_and_retry() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let sqlite = runtime.sqlite().clone();
    let client_id = "reservation-crash-retry";
    let digest = test_digest('8');
    let payload = bound_payload(client_id, "retry reservation");
    let QueuedClientBindingReserveOutcome::Reserved(before_crash) = runtime
        .thread_queue()
        .reserve_client_binding(thread_id, client_id, &digest, &payload)
        .await
        .unwrap()
    else {
        panic!("fresh binding must reserve");
    };
    drop(runtime);

    let restarted = StateRuntime::init(sqlite, "test-provider".to_string())
        .await
        .unwrap();
    let QueuedClientBindingReserveOutcome::Reserved(after_crash) = restarted
        .thread_queue()
        .reserve_client_binding(thread_id, client_id, &digest, &payload)
        .await
        .unwrap()
    else {
        panic!("retry must recover the durable reservation");
    };
    assert_eq!(before_crash, after_crash);
    assert!(matches!(
        restarted
            .thread_queue()
            .finalize_client_binding(QueuedClientBindingFinalizeRequest {
                thread_id,
                client_id: client_id.to_string(),
                payload_sha256: digest,
                payload_json: payload,
                lease: after_crash,
                mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
                observed_turn_id: None,
                runtime_capacity: None,
            })
            .await
            .unwrap(),
        QueuedClientBindingFinalizeOutcome::Queued { created: true, .. }
    ));
}

#[tokio::test]
async fn binding_schema_rejects_malformed_digest_owner_revision_turn_and_time() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let valid_digest = test_digest('a');
    let invalid_digest = "A".repeat(64);
    let cases = [
        RawBinding {
            client_id: "bad-digest",
            digest: &invalid_digest,
            state: "queued",
            queued_item_id: Some("item-digest"),
            turn_id: None,
            owner_id: None,
            lease_expires_at_ms: None,
            lock_device: None,
            lock_inode: None,
            revision: 1,
            created_at_ms: 100,
            updated_at_ms: 100,
        },
        RawBinding {
            client_id: "bad-owner",
            digest: &valid_digest,
            state: "dispatching",
            queued_item_id: Some("item-owner"),
            turn_id: None,
            owner_id: Some(""),
            lease_expires_at_ms: Some(200),
            lock_device: Some(1),
            lock_inode: Some(2),
            revision: 1,
            created_at_ms: 100,
            updated_at_ms: 100,
        },
        RawBinding {
            client_id: "bad-revision",
            digest: &valid_digest,
            state: "queued",
            queued_item_id: Some("item-revision"),
            turn_id: None,
            owner_id: None,
            lease_expires_at_ms: None,
            lock_device: None,
            lock_inode: None,
            revision: 0,
            created_at_ms: 100,
            updated_at_ms: 100,
        },
        RawBinding {
            client_id: "bad-turn",
            digest: &valid_digest,
            state: "persisted",
            queued_item_id: None,
            turn_id: Some(""),
            owner_id: None,
            lease_expires_at_ms: None,
            lock_device: None,
            lock_inode: None,
            revision: 1,
            created_at_ms: 100,
            updated_at_ms: 100,
        },
        RawBinding {
            client_id: "bad-time",
            digest: &valid_digest,
            state: "dispatching",
            queued_item_id: Some("item-time"),
            turn_id: None,
            owner_id: Some("owner"),
            lease_expires_at_ms: Some(-1),
            lock_device: Some(1),
            lock_inode: Some(2),
            revision: 1,
            created_at_ms: 100,
            updated_at_ms: 100,
        },
    ];
    for binding in cases {
        assert!(
            insert_raw_binding(runtime.as_ref(), thread_id, binding)
                .await
                .is_err()
        );
    }
}

#[tokio::test]
async fn raw_enqueue_without_exact_binding_succeeds() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let payload = bound_payload("compatibility-client", "legacy queue input");

    let record = runtime
        .thread_queue()
        .enqueue(thread_id, &payload)
        .await
        .expect("raw enqueue must remain available before exact reconciliation");

    assert_eq!(record.thread_id, thread_id);
    assert_eq!(record.payload, payload);
    assert_eq!(
        vec![record],
        runtime
            .thread_queue()
            .list_page(thread_id, 0, MAX_QUEUE_ITEMS)
            .await
            .expect("raw queue row should be readable")
    );
}

#[tokio::test]
async fn raw_enqueue_cannot_cross_an_exact_reservation() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let other = StateRuntime::init(runtime.sqlite().clone(), "test-provider".to_string())
        .await
        .unwrap();
    let payload = bound_payload("matrix-client", "hello");
    let digest = test_digest('d');
    let QueuedClientBindingReserveOutcome::Reserved(lease) = runtime
        .thread_queue()
        .reserve_client_binding(thread_id, "matrix-client", &digest, &payload)
        .await
        .unwrap()
    else {
        panic!("new exact identity must reserve");
    };

    let error = other
        .thread_queue()
        .enqueue(thread_id, &payload)
        .await
        .expect_err("raw enqueue must not bypass a durable reservation");
    assert!(
        error
            .downcast_ref::<QueuedClientBindingConflict>()
            .is_some()
    );
    assert!(
        runtime
            .thread_queue()
            .list_page(thread_id, 0, MAX_QUEUE_ITEMS)
            .await
            .unwrap()
            .is_empty()
    );

    let QueuedClientBindingFinalizeOutcome::Queued {
        record,
        created: true,
    } = runtime
        .thread_queue()
        .finalize_client_binding(QueuedClientBindingFinalizeRequest {
            thread_id,
            client_id: "matrix-client".to_string(),
            payload_sha256: digest.clone(),
            payload_json: payload.clone(),
            lease,
            mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
            observed_turn_id: None,
            runtime_capacity: None,
        })
        .await
        .unwrap()
    else {
        panic!("reserved admission must remain finalizable");
    };
    assert_eq!(
        vec![record],
        runtime
            .thread_queue()
            .list_page(thread_id, 0, MAX_QUEUE_ITEMS)
            .await
            .unwrap()
    );
}

#[tokio::test]
async fn exact_reservation_rejects_conflicting_compatibility_row_in_one_snapshot() {
    let (runtime, thread_id) = runtime_with_thread().await;
    runtime
        .thread_queue()
        .enqueue(thread_id, &bound_payload("matrix-client", "first"))
        .await
        .unwrap();

    let error = runtime
        .thread_queue()
        .reserve_client_binding(
            thread_id,
            "matrix-client",
            &test_digest('b'),
            &bound_payload("matrix-client", "different"),
        )
        .await
        .expect_err("same client id with different content must fail closed");

    assert!(
        error
            .downcast_ref::<QueuedClientBindingConflict>()
            .is_some()
    );
    assert_eq!(
        1,
        runtime
            .thread_queue()
            .list_page(thread_id, 0, MAX_QUEUE_ITEMS)
            .await
            .unwrap()
            .len()
    );
}

#[tokio::test]
async fn persisted_binding_deletes_queue_row_and_blocks_resurrection() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let payload = bound_payload("matrix-client", "hello");
    let digest = test_digest('c');
    let QueuedClientBindingReserveOutcome::Reserved(lease) = runtime
        .thread_queue()
        .reserve_client_binding(thread_id, "matrix-client", &digest, &payload)
        .await
        .unwrap()
    else {
        panic!("new client id must reserve");
    };
    let QueuedClientBindingFinalizeOutcome::Queued { record, .. } = runtime
        .thread_queue()
        .finalize_client_binding(QueuedClientBindingFinalizeRequest {
            thread_id,
            client_id: "matrix-client".to_string(),
            payload_sha256: digest.clone(),
            payload_json: payload.clone(),
            lease,
            mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
            observed_turn_id: None,
            runtime_capacity: None,
        })
        .await
        .unwrap()
    else {
        panic!("reservation must create a queue row");
    };

    assert!(
        runtime
            .thread_queue()
            .mark_client_binding_persisted(
                thread_id,
                "matrix-client",
                &digest,
                &record.id,
                "turn-1",
            )
            .await
            .unwrap()
    );
    assert!(
        runtime
            .thread_queue()
            .list_page(thread_id, 0, MAX_QUEUE_ITEMS)
            .await
            .unwrap()
            .is_empty()
    );
    assert_eq!(
        QueuedClientBindingReserveOutcome::Persisted {
            turn_id: "turn-1".to_string(),
        },
        runtime
            .thread_queue()
            .reserve_client_binding(thread_id, "matrix-client", &digest, &payload)
            .await
            .unwrap()
    );
    assert!(
        runtime
            .thread_queue()
            .enqueue_guarded(thread_id, &payload, "matrix-client", &digest, None)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn raw_update_is_blocked_and_raw_delete_leaves_a_cancelled_tombstone() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let payload = bound_payload("matrix-client", "hello");
    let digest = test_digest('e');
    let QueuedClientBindingReserveOutcome::Reserved(lease) = runtime
        .thread_queue()
        .reserve_client_binding(thread_id, "matrix-client", &digest, &payload)
        .await
        .unwrap()
    else {
        panic!("new exact identity must reserve");
    };
    let QueuedClientBindingFinalizeOutcome::Queued { record, .. } = runtime
        .thread_queue()
        .finalize_client_binding(QueuedClientBindingFinalizeRequest {
            thread_id,
            client_id: "matrix-client".to_string(),
            payload_sha256: digest.clone(),
            payload_json: payload.clone(),
            lease,
            mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
            observed_turn_id: None,
            runtime_capacity: None,
        })
        .await
        .unwrap()
    else {
        panic!("reservation must create a row");
    };

    let update_error = runtime
        .thread_queue()
        .update(
            thread_id,
            &record.id,
            &bound_payload("matrix-client", "mutated"),
        )
        .await
        .expect_err("exact rows must be immutable");
    assert!(
        update_error
            .downcast_ref::<QueuedClientBindingConflict>()
            .is_some()
    );
    let ordinary = runtime
        .thread_queue()
        .enqueue(thread_id, &bound_payload("ordinary-client", "ordinary"))
        .await
        .unwrap();
    let identity_swap_error = runtime
        .thread_queue()
        .update(thread_id, &ordinary.id, &payload)
        .await
        .expect_err("an ordinary row cannot mutate into an exact client identity");
    assert!(
        identity_swap_error
            .downcast_ref::<QueuedClientBindingConflict>()
            .is_some()
    );
    assert!(
        runtime
            .thread_queue()
            .delete(thread_id, &record.id)
            .await
            .unwrap()
    );
    assert_eq!(
        QueuedClientBindingReserveOutcome::Cancelled,
        runtime
            .thread_queue()
            .reserve_client_binding(thread_id, "matrix-client", &digest, &payload)
            .await
            .unwrap()
    );
}

#[tokio::test]
async fn cancel_vs_submit_is_fenced_across_state_runtimes() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let other = StateRuntime::init(runtime.sqlite().clone(), "test-provider".to_string())
        .await
        .unwrap();
    let client_id = "matrix-dispatch";
    let digest = test_digest('f');
    let record = exact_queued_record(
        runtime.as_ref(),
        thread_id,
        client_id,
        &digest,
        &bound_payload(client_id, "dispatch once"),
    )
    .await;

    let process_lock = runtime
        .thread_queue()
        .try_acquire_client_dispatch_lock(thread_id, client_id, &digest)
        .unwrap()
        .expect("first runtime must hold the process lock");
    assert!(
        other
            .thread_queue()
            .try_acquire_client_dispatch_lock(thread_id, client_id, &digest)
            .unwrap()
            .is_none(),
        "a second runtime in the same process must be fenced"
    );
    let QueuedClientDispatchClaimOutcome::Acquired(lease) = runtime
        .thread_queue()
        .claim_client_binding_dispatch(
            &process_lock,
            &record.id,
            "owner-a",
            /*now_ms*/ 100,
            /*lease_expires_at_ms*/ 200,
        )
        .await
        .unwrap()
    else {
        panic!("queued binding must become dispatching");
    };

    let cancel_error = other
        .thread_queue()
        .delete(thread_id, &record.id)
        .await
        .expect_err("cancel must not cross an in-flight exact submit");
    assert!(
        cancel_error
            .downcast_ref::<QueuedClientBindingConflict>()
            .is_some()
    );
    runtime
        .thread_queue()
        .complete_client_binding_dispatch(&process_lock, &lease, "turn-owned")
        .await
        .unwrap();
    assert!(
        runtime
            .thread_queue()
            .list_page(thread_id, 0, MAX_QUEUE_ITEMS)
            .await
            .unwrap()
            .is_empty()
    );
}

#[tokio::test]
async fn expired_time_cannot_take_over_a_live_owner_and_old_revision_is_rejected() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let other = StateRuntime::init(runtime.sqlite().clone(), "test-provider".to_string())
        .await
        .unwrap();
    let client_id = "matrix-expired";
    let digest = test_digest('1');
    let record = exact_queued_record(
        runtime.as_ref(),
        thread_id,
        client_id,
        &digest,
        &bound_payload(client_id, "owner pause"),
    )
    .await;
    let first_lock = runtime
        .thread_queue()
        .try_acquire_client_dispatch_lock(thread_id, client_id, &digest)
        .unwrap()
        .unwrap();
    let QueuedClientDispatchClaimOutcome::Acquired(old_lease) = runtime
        .thread_queue()
        .claim_client_binding_dispatch(&first_lock, &record.id, "old-owner", 100, 110)
        .await
        .unwrap()
    else {
        panic!("first owner must acquire dispatch");
    };

    assert!(
        other
            .thread_queue()
            .try_acquire_client_dispatch_lock(thread_id, client_id, &digest)
            .unwrap()
            .is_none(),
        "lease expiry cannot bypass a paused live owner's OS lock"
    );
    drop(first_lock); // Models positive process-death/release evidence.

    let takeover_lock = other
        .thread_queue()
        .try_acquire_client_dispatch_lock(thread_id, client_id, &digest)
        .unwrap()
        .expect("dead owner released its kernel lock");
    let QueuedClientDispatchClaimOutcome::Expired(expired) = other
        .thread_queue()
        .claim_client_binding_dispatch(&takeover_lock, &record.id, "new-owner", 200, 300)
        .await
        .unwrap()
    else {
        panic!("expired SQLite row must require rollout recovery");
    };
    let QueuedClientDispatchClaimOutcome::Acquired(new_lease) = other
        .thread_queue()
        .recover_expired_client_dispatch(
            &takeover_lock,
            &expired,
            "new-owner",
            /*observed_turn_id*/ None,
            200,
            300,
        )
        .await
        .unwrap()
    else {
        panic!("negative exact scan plus owner-death lock must fence a new attempt");
    };

    assert!(
        runtime
            .thread_queue()
            .authorize_client_binding_dispatch(&takeover_lock, &old_lease, 201, 301)
            .await
            .expect_err("old owner revision must not authorize submit")
            .downcast_ref::<QueuedClientBindingConflict>()
            .is_some()
    );
    assert!(
        runtime
            .thread_queue()
            .complete_client_binding_dispatch(&takeover_lock, &old_lease, "old-turn")
            .await
            .expect_err("old owner revision must not complete")
            .downcast_ref::<QueuedClientBindingConflict>()
            .is_some()
    );
    other
        .thread_queue()
        .complete_client_binding_dispatch(&takeover_lock, &new_lease, "new-turn")
        .await
        .unwrap();
}

#[tokio::test]
async fn expired_dispatch_rollout_evidence_closes_without_resubmission() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let client_id = "matrix-crash-window";
    let digest = test_digest('2');
    let record = exact_queued_record(
        runtime.as_ref(),
        thread_id,
        client_id,
        &digest,
        &bound_payload(client_id, "rollout flushed"),
    )
    .await;
    let old_lock = runtime
        .thread_queue()
        .try_acquire_client_dispatch_lock(thread_id, client_id, &digest)
        .unwrap()
        .unwrap();
    let QueuedClientDispatchClaimOutcome::Acquired(old_lease) = runtime
        .thread_queue()
        .claim_client_binding_dispatch(&old_lock, &record.id, "crashed-owner", 10, 20)
        .await
        .unwrap()
    else {
        panic!("old owner must acquire dispatch");
    };
    drop(old_lock); // Core rollout flushed, then the process died before DB CAS.

    let recovery_lock = runtime
        .thread_queue()
        .try_acquire_client_dispatch_lock(thread_id, client_id, &digest)
        .unwrap()
        .unwrap();
    let QueuedClientDispatchClaimOutcome::Expired(expired) = runtime
        .thread_queue()
        .claim_client_binding_dispatch(&recovery_lock, &record.id, "recovery", 30, 40)
        .await
        .unwrap()
    else {
        panic!("crashed dispatch must expose recovery token");
    };
    assert_eq!(old_lease.revision, expired.revision);
    assert_eq!(
        QueuedClientDispatchClaimOutcome::Persisted {
            turn_id: "durable-turn".to_string()
        },
        runtime
            .thread_queue()
            .recover_expired_client_dispatch(
                &recovery_lock,
                &expired,
                "recovery",
                Some("durable-turn"),
                30,
                40,
            )
            .await
            .unwrap()
    );
    assert!(
        runtime
            .thread_queue()
            .list_page(thread_id, 0, MAX_QUEUE_ITEMS)
            .await
            .unwrap()
            .is_empty()
    );
    assert_eq!(
        QueuedClientBindingReserveOutcome::Persisted {
            turn_id: "durable-turn".to_string()
        },
        runtime
            .thread_queue()
            .reserve_client_binding(
                thread_id,
                client_id,
                &digest,
                &bound_payload(client_id, "rollout flushed"),
            )
            .await
            .unwrap()
    );
}

#[tokio::test]
async fn subtree_delete_seal_is_atomic_across_threads_and_idempotent() {
    let (runtime, first_thread_id) = runtime_with_thread().await;
    let second_thread_id = ThreadId::new();
    let first_record = runtime
        .thread_queue()
        .enqueue(first_thread_id, r#"{"kind":"ordinary"}"#)
        .await
        .unwrap();
    let client_id = "matrix-seal-atomic";
    let digest = test_digest('8');
    let second_record = exact_queued_record(
        runtime.as_ref(),
        second_thread_id,
        client_id,
        &digest,
        &bound_payload(client_id, "atomic subtree seal"),
    )
    .await;
    let process_lock = runtime
        .thread_queue()
        .try_acquire_client_dispatch_lock(second_thread_id, client_id, &digest)
        .unwrap()
        .unwrap();
    let QueuedClientDispatchClaimOutcome::Acquired(dispatch_lease) = runtime
        .thread_queue()
        .claim_client_binding_dispatch(
            &process_lock,
            &second_record.id,
            "seal-blocking-owner",
            100,
            200,
        )
        .await
        .unwrap()
    else {
        panic!("second thread must hold an exact dispatch");
    };

    assert_binding_conflict(
        runtime
            .thread_queue()
            .seal_thread_queues_for_deletion(&[first_thread_id, second_thread_id])
            .await,
        "subtree seal with one active dispatch",
    );
    let fence_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM queued_thread_deletion_fences")
        .fetch_one(runtime.thread_queue().pool.as_ref())
        .await
        .unwrap();
    assert_eq!(0, fence_count, "a failed batch must not partially seal");
    let queue_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM queued_items WHERE thread_id IN (?, ?)")
            .bind(first_thread_id.to_string())
            .bind(second_thread_id.to_string())
            .fetch_one(runtime.thread_queue().pool.as_ref())
            .await
            .unwrap();
    assert_eq!(2, queue_count, "a failed batch must not delete queue rows");
    let binding_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM queued_client_bindings WHERE thread_id IN (?, ?)")
            .bind(first_thread_id.to_string())
            .bind(second_thread_id.to_string())
            .fetch_one(runtime.thread_queue().pool.as_ref())
            .await
            .unwrap();
    assert_eq!(
        1, binding_count,
        "a failed batch must not delete exact bindings"
    );
    assert_eq!(
        first_record.id,
        runtime
            .thread_queue()
            .list_page(first_thread_id, 0, 1)
            .await
            .unwrap()[0]
            .id
    );

    runtime
        .thread_queue()
        .release_client_binding_dispatch(&process_lock, &dispatch_lease)
        .await
        .unwrap();
    runtime
        .thread_queue()
        .seal_thread_queues_for_deletion(&[first_thread_id, second_thread_id, first_thread_id])
        .await
        .unwrap();
    let original_fences: Vec<(String, String)> = sqlx::query_as(
        "SELECT thread_id, deletion_id FROM queued_thread_deletion_fences
         WHERE thread_id IN (?, ?) ORDER BY thread_id",
    )
    .bind(first_thread_id.to_string())
    .bind(second_thread_id.to_string())
    .fetch_all(runtime.thread_queue().pool.as_ref())
    .await
    .unwrap();
    assert_eq!(2, original_fences.len());
    assert_eq!(
        1,
        original_fences
            .iter()
            .map(|(_, deletion_id)| deletion_id)
            .collect::<std::collections::HashSet<_>>()
            .len(),
        "one atomic batch must share one deletion identity"
    );
    let remaining_rows: i64 = sqlx::query_scalar(
        "SELECT
            (SELECT COUNT(*) FROM queued_items WHERE thread_id IN (?, ?)) +
            (SELECT COUNT(*) FROM queued_client_bindings WHERE thread_id IN (?, ?))",
    )
    .bind(first_thread_id.to_string())
    .bind(second_thread_id.to_string())
    .bind(first_thread_id.to_string())
    .bind(second_thread_id.to_string())
    .fetch_one(runtime.thread_queue().pool.as_ref())
    .await
    .unwrap();
    assert_eq!(0, remaining_rows);

    runtime
        .thread_queue()
        .seal_thread_queues_for_deletion(&[second_thread_id, first_thread_id])
        .await
        .unwrap();
    let repeated_fences: Vec<(String, String)> = sqlx::query_as(
        "SELECT thread_id, deletion_id FROM queued_thread_deletion_fences
         WHERE thread_id IN (?, ?) ORDER BY thread_id",
    )
    .bind(first_thread_id.to_string())
    .bind(second_thread_id.to_string())
    .fetch_all(runtime.thread_queue().pool.as_ref())
    .await
    .unwrap();
    assert_eq!(original_fences, repeated_fences);
}

#[tokio::test]
async fn durable_delete_operation_recovers_exact_closure_across_presealed_overlap() {
    let (runtime, parent_thread_id) = runtime_with_thread().await;
    let child_thread_id = ThreadId::new();
    runtime
        .thread_queue()
        .seal_thread_queues_for_deletion(&[child_thread_id])
        .await
        .unwrap();
    let child_deletion_id: String = sqlx::query_scalar(
        "SELECT deletion_id FROM queued_thread_deletion_fences WHERE thread_id = ?",
    )
    .bind(child_thread_id.to_string())
    .fetch_one(runtime.thread_queue().pool.as_ref())
    .await
    .unwrap();

    runtime
        .thread_queue()
        .seal_thread_subtree_for_deletion(parent_thread_id, &[parent_thread_id, child_thread_id])
        .await
        .unwrap();

    assert_eq!(
        runtime
            .thread_queue()
            .thread_deletion_operation_members(parent_thread_id)
            .await
            .unwrap(),
        Some(vec![parent_thread_id, child_thread_id])
    );
    let child_deletion_id_after_overlap: String = sqlx::query_scalar(
        "SELECT deletion_id FROM queued_thread_deletion_fences WHERE thread_id = ?",
    )
    .bind(child_thread_id.to_string())
    .fetch_one(runtime.thread_queue().pool.as_ref())
    .await
    .unwrap();
    assert_eq!(child_deletion_id, child_deletion_id_after_overlap);

    runtime
        .thread_queue()
        .seal_thread_subtree_for_deletion(parent_thread_id, &[parent_thread_id, child_thread_id])
        .await
        .unwrap();
    assert_binding_conflict(
        runtime
            .thread_queue()
            .seal_thread_subtree_for_deletion(parent_thread_id, &[parent_thread_id])
            .await,
        "same root with a different durable delete closure",
    );

    sqlx::query(
        "UPDATE queued_thread_deletion_operation_members
         SET operation_id = 'corrupt-operation-id'
         WHERE root_thread_id = ? AND member_thread_id = ?",
    )
    .bind(parent_thread_id.to_string())
    .bind(child_thread_id.to_string())
    .execute(runtime.thread_queue().pool.as_ref())
    .await
    .unwrap();
    let corrupt_error = runtime
        .thread_queue()
        .thread_deletion_operation_members(parent_thread_id)
        .await
        .expect_err("mixed operation identities must fail closed");
    assert!(
        corrupt_error
            .to_string()
            .contains("multiple operation identities"),
        "unexpected corruption error: {corrupt_error}"
    );
}

#[tokio::test]
async fn delete_seal_fences_current_and_legacy_queue_writers() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let queue = runtime.thread_queue();
    let ordinary = queue
        .enqueue(thread_id, r#"{"kind":"ordinary-before-seal"}"#)
        .await
        .unwrap();
    let exact_client_id = "matrix-sealed-claim";
    let exact_digest = test_digest('9');
    let exact = exact_queued_record(
        runtime.as_ref(),
        thread_id,
        exact_client_id,
        &exact_digest,
        &bound_payload(exact_client_id, "claim after seal"),
    )
    .await;
    let process_lock = queue
        .try_acquire_client_dispatch_lock(thread_id, exact_client_id, &exact_digest)
        .unwrap()
        .unwrap();
    let reserved_client_id = "matrix-sealed-finalize";
    let reserved_digest = test_digest('a');
    let reserved_payload = bound_payload(reserved_client_id, "finalize after seal");
    let QueuedClientBindingReserveOutcome::Reserved(reservation) = queue
        .reserve_client_binding(
            thread_id,
            reserved_client_id,
            &reserved_digest,
            &reserved_payload,
        )
        .await
        .unwrap()
    else {
        panic!("pre-seal exact identity must reserve");
    };

    queue
        .seal_thread_queues_for_deletion(&[thread_id])
        .await
        .unwrap();

    assert_binding_conflict(
        queue
            .enqueue(thread_id, r#"{"kind":"new-after-seal"}"#)
            .await,
        "enqueue after delete seal",
    );
    assert_binding_conflict(
        queue
            .reserve_client_binding(
                thread_id,
                "matrix-new-after-seal",
                &test_digest('b'),
                &bound_payload("matrix-new-after-seal", "reserve after seal"),
            )
            .await,
        "reserve after delete seal",
    );
    assert_binding_conflict(
        queue
            .finalize_client_binding(QueuedClientBindingFinalizeRequest {
                thread_id,
                client_id: reserved_client_id.to_string(),
                payload_sha256: reserved_digest,
                payload_json: reserved_payload,
                lease: reservation,
                mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
                observed_turn_id: None,
                runtime_capacity: None,
            })
            .await,
        "finalize after delete seal",
    );
    assert_binding_conflict(
        queue
            .claim_client_binding_dispatch(&process_lock, &exact.id, "sealed-claim-owner", 100, 200)
            .await,
        "dispatch claim after delete seal",
    );
    assert_binding_conflict(
        queue
            .update(thread_id, &ordinary.id, r#"{"kind":"updated"}"#)
            .await,
        "update after delete seal",
    );
    assert_binding_conflict(
        queue.reorder(thread_id, &[]).await,
        "reorder after delete seal",
    );

    let raw_insert_error = sqlx::query(
        "INSERT INTO queued_items
            (id, thread_id, payload_json, queue_order, created_at_ms, updated_at_ms)
         VALUES ('legacy-sealed-insert', ?, '{}', 0, 0, 0)",
    )
    .bind(thread_id.to_string())
    .execute(queue.pool.as_ref())
    .await
    .unwrap_err();
    assert_delete_seal_trigger(raw_insert_error, "legacy queued-item insert");

    let unsealed_thread_id = ThreadId::new();
    let legacy_row = queue
        .enqueue(unsealed_thread_id, r#"{"kind":"legacy-update-source"}"#)
        .await
        .unwrap();
    let raw_update_error = sqlx::query("UPDATE queued_items SET thread_id = ? WHERE id = ?")
        .bind(thread_id.to_string())
        .bind(&legacy_row.id)
        .execute(queue.pool.as_ref())
        .await
        .unwrap_err();
    assert_delete_seal_trigger(raw_update_error, "legacy queued-item update");

    let raw_binding_insert_error = insert_raw_binding(
        runtime.as_ref(),
        thread_id,
        RawBinding {
            client_id: "legacy-sealed-binding",
            digest: &test_digest('c'),
            state: "cancelled",
            queued_item_id: None,
            turn_id: None,
            owner_id: None,
            lease_expires_at_ms: None,
            lock_device: None,
            lock_inode: None,
            revision: 1,
            created_at_ms: 0,
            updated_at_ms: 0,
        },
    )
    .await
    .unwrap_err();
    assert_delete_seal_trigger(raw_binding_insert_error, "legacy binding insert");

    let legacy_client_id = "legacy-binding-update-source";
    let legacy_digest = test_digest('d');
    exact_queued_record(
        runtime.as_ref(),
        unsealed_thread_id,
        legacy_client_id,
        &legacy_digest,
        &bound_payload(legacy_client_id, "legacy binding update"),
    )
    .await;
    let raw_binding_update_error = sqlx::query(
        "UPDATE queued_client_bindings SET thread_id = ?
         WHERE thread_id = ? AND client_user_message_id = ?",
    )
    .bind(thread_id.to_string())
    .bind(unsealed_thread_id.to_string())
    .bind(legacy_client_id)
    .execute(queue.pool.as_ref())
    .await
    .unwrap_err();
    assert_delete_seal_trigger(raw_binding_update_error, "legacy binding update");
}

#[cfg(unix)]
#[tokio::test]
async fn sigkill_releases_exact_dispatch_lock_but_requires_durable_recovery() {
    const CHILD_MODE: &str = "HEPTA_QUEUE_OWNER_CRASH_CHILD";
    const CHILD_HOME: &str = "HEPTA_QUEUE_OWNER_CRASH_HOME";
    const CHILD_THREAD: &str = "HEPTA_QUEUE_OWNER_CRASH_THREAD";
    const CHILD_ITEM: &str = "HEPTA_QUEUE_OWNER_CRASH_ITEM";
    const CHILD_READY: &str = "HEPTA_QUEUE_OWNER_CRASH_READY";
    const CLIENT_ID: &str = "matrix-real-owner-crash";
    const OWNER_ID: &str = "sigkill-owner";
    const LEASE_EXPIRES_AT_MS: i64 = 110;
    let digest = test_digest('e');

    if std::env::var_os(CHILD_MODE).is_some() {
        let home = PathBuf::from(std::env::var(CHILD_HOME).expect("child home"));
        let thread_id =
            ThreadId::from_string(std::env::var(CHILD_THREAD).expect("child thread").as_str())
                .expect("child thread id");
        let item_id = std::env::var(CHILD_ITEM).expect("child queue item");
        let ready_path = PathBuf::from(std::env::var(CHILD_READY).expect("child ready path"));
        let runtime = StateRuntime::init(
            crate::SqliteConfig::new_for_testing(home.as_path().abs()),
            "test-provider".to_string(),
        )
        .await
        .expect("child state runtime");
        let process_lock = runtime
            .thread_queue()
            .try_acquire_client_dispatch_lock(thread_id, CLIENT_ID, &digest)
            .expect("child lock attempt")
            .expect("child must own the exact process lock");
        let QueuedClientDispatchClaimOutcome::Acquired(lease) = runtime
            .thread_queue()
            .claim_client_binding_dispatch(
                &process_lock,
                &item_id,
                OWNER_ID,
                100,
                LEASE_EXPIRES_AT_MS,
            )
            .await
            .expect("child dispatch claim")
        else {
            panic!("child must durably claim exact dispatch");
        };

        let temporary_ready_path = ready_path.with_extension(format!("tmp-{}", std::process::id()));
        let mut ready_file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary_ready_path)
            .expect("create child ready evidence");
        writeln!(ready_file, "{}", lease.revision).unwrap();
        writeln!(ready_file, "{}", lease.lease_expires_at_ms).unwrap();
        writeln!(ready_file, "{}", lease.lock_nonce).unwrap();
        writeln!(ready_file, "{}", lease.lock_device).unwrap();
        writeln!(ready_file, "{}", lease.lock_inode).unwrap();
        ready_file.sync_all().expect("sync child ready evidence");
        drop(ready_file);
        fs::rename(&temporary_ready_path, &ready_path).expect("publish child ready evidence");

        let _owned_authority = (process_lock, lease);
        std::future::pending::<()>().await;
        unreachable!("owner-crash child must be killed by its parent");
    }

    let (runtime, thread_id) = runtime_with_thread().await;
    let record = exact_queued_record(
        runtime.as_ref(),
        thread_id,
        CLIENT_ID,
        &digest,
        &bound_payload(CLIENT_ID, "real owner crash"),
    )
    .await;
    let ready_path = runtime.sqlite().home().join("owner-crash-ready");
    let mut child = Command::new(std::env::current_exe().expect("current test executable"))
        .arg("--exact")
        .arg("runtime::queued_items::tests::sigkill_releases_exact_dispatch_lock_but_requires_durable_recovery")
        .arg("--nocapture")
        .env(CHILD_MODE, "1")
        .env(CHILD_HOME, runtime.sqlite().home())
        .env(CHILD_THREAD, thread_id.to_string())
        .env(CHILD_ITEM, &record.id)
        .env(CHILD_READY, &ready_path)
        .spawn()
        .expect("spawn owner-crash child");
    let ready_contents = match tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            if let Ok(contents) = fs::read_to_string(&ready_path)
                && contents.lines().count() == 5
            {
                break contents;
            }
            assert!(
                child.try_wait().expect("poll owner-crash child").is_none(),
                "owner-crash child exited before publishing ready evidence"
            );
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await
    {
        Ok(contents) => contents,
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            panic!("owner-crash child did not publish ready evidence in time");
        }
    };
    let fields = ready_contents.lines().collect::<Vec<_>>();
    let stale_revision = fields[0].parse::<i64>().unwrap();
    let stale_lease_expires_at_ms = fields[1].parse::<i64>().unwrap();
    let stale_lock_nonce = fields[2].to_string();
    let stale_lock_device = fields[3].parse::<i64>().unwrap();
    let stale_lock_inode = fields[4].parse::<i64>().unwrap();

    assert!(
        runtime
            .thread_queue()
            .try_acquire_client_dispatch_lock(thread_id, CLIENT_ID, &digest)
            .unwrap()
            .is_none(),
        "a live child process must retain the kernel dispatch lock past lease expiry"
    );
    child.kill().expect("SIGKILL owner-crash child");
    let status = child.wait().expect("reap owner-crash child");
    use std::os::unix::process::ExitStatusExt;
    assert_eq!(Some(9), status.signal(), "child must die by SIGKILL");

    let recovery_lock = runtime
        .thread_queue()
        .try_acquire_client_dispatch_lock(thread_id, CLIENT_ID, &digest)
        .unwrap()
        .expect("kernel must release the exact lock when the child dies");
    let QueuedClientDispatchClaimOutcome::Expired(expired) = runtime
        .thread_queue()
        .claim_client_binding_dispatch(&recovery_lock, &record.id, "recovery-owner", 200, 300)
        .await
        .unwrap()
    else {
        panic!("owner death plus wall-clock expiry must still require durable recovery");
    };
    assert_eq!(OWNER_ID, expired.previous_owner_id);
    assert_eq!(stale_revision, expired.revision);

    let stale_lease = QueuedClientDispatchLease {
        thread_id,
        client_id: CLIENT_ID.to_string(),
        payload_sha256: digest.clone(),
        queued_item_id: record.id.clone(),
        owner_id: OWNER_ID.to_string(),
        revision: stale_revision,
        lease_expires_at_ms: stale_lease_expires_at_ms,
        lock_nonce: stale_lock_nonce,
        lock_device: stale_lock_device,
        lock_inode: stale_lock_inode,
    };
    assert_binding_conflict(
        runtime
            .thread_queue()
            .complete_client_binding_dispatch(&recovery_lock, &stale_lease, "stale-turn")
            .await,
        "dead owner's completion",
    );
    assert_binding_conflict(
        runtime
            .thread_queue()
            .release_client_binding_dispatch(&recovery_lock, &stale_lease)
            .await,
        "dead owner's release",
    );

    let QueuedClientDispatchClaimOutcome::Acquired(recovered_lease) = runtime
        .thread_queue()
        .recover_expired_client_dispatch(
            &recovery_lock,
            &expired,
            "recovery-owner",
            /* exact negative rollout scan */ None,
            200,
            300,
        )
        .await
        .unwrap()
    else {
        panic!("only explicit expired-dispatch recovery may grant a successor attempt");
    };
    runtime
        .thread_queue()
        .complete_client_binding_dispatch(
            &recovery_lock,
            &recovered_lease,
            "turn-after-owner-crash",
        )
        .await
        .unwrap();
    assert_eq!(
        QueuedClientBindingReserveOutcome::Persisted {
            turn_id: "turn-after-owner-crash".to_string()
        },
        runtime
            .thread_queue()
            .reserve_client_binding(
                thread_id,
                CLIENT_ID,
                &digest,
                &bound_payload(CLIENT_ID, "real owner crash"),
            )
            .await
            .unwrap()
    );
}

#[tokio::test]
async fn cross_process_dispatch_lock_requires_kernel_owner_release() {
    const CHILD_MODE: &str = "HEPTA_QUEUE_DISPATCH_LOCK_CHILD_MODE";
    const CHILD_HOME: &str = "HEPTA_QUEUE_DISPATCH_LOCK_CHILD_HOME";
    const CHILD_THREAD: &str = "HEPTA_QUEUE_DISPATCH_LOCK_CHILD_THREAD";
    const CHILD_ITEM: &str = "HEPTA_QUEUE_DISPATCH_LOCK_CHILD_ITEM";
    const CLIENT_ID: &str = "matrix-cross-process";
    let digest = test_digest('3');

    if let Ok(mode) = std::env::var(CHILD_MODE) {
        let home = PathBuf::from(std::env::var(CHILD_HOME).expect("child home"));
        let thread_id =
            ThreadId::from_string(std::env::var(CHILD_THREAD).expect("child thread").as_str())
                .expect("child thread id");
        let item_id = std::env::var(CHILD_ITEM).expect("child queue item");
        let runtime = StateRuntime::init(
            crate::SqliteConfig::new_for_testing(home.as_path().abs()),
            "test-provider".to_string(),
        )
        .await
        .expect("child state runtime");
        let process_lock = runtime
            .thread_queue()
            .try_acquire_client_dispatch_lock(thread_id, CLIENT_ID, &digest)
            .expect("child lock attempt");
        match mode.as_str() {
            "blocked" => assert!(
                process_lock.is_none(),
                "child must not bypass a live parent's kernel lock"
            ),
            "expired" => {
                let process_lock = process_lock.expect("released parent lock must be acquirable");
                assert!(matches!(
                    runtime
                        .thread_queue()
                        .claim_client_binding_dispatch(
                            &process_lock,
                            &item_id,
                            "child-owner",
                            200,
                            300,
                        )
                        .await
                        .expect("child expired claim"),
                    QueuedClientDispatchClaimOutcome::Expired(_)
                ));
            }
            mode => panic!("unknown dispatch-lock child mode `{mode}`"),
        }
        return;
    }

    let (runtime, thread_id) = runtime_with_thread().await;
    let record = exact_queued_record(
        runtime.as_ref(),
        thread_id,
        CLIENT_ID,
        &digest,
        &bound_payload(CLIENT_ID, "cross process"),
    )
    .await;
    let parent_lock = runtime
        .thread_queue()
        .try_acquire_client_dispatch_lock(thread_id, CLIENT_ID, &digest)
        .unwrap()
        .unwrap();
    #[cfg(unix)]
    {
        let lock_path = runtime
            .sqlite()
            .home()
            .join("queue-dispatch-locks")
            .join(dispatch_lock_file_name(thread_id, CLIENT_ID, &digest));
        let directory_mode = std::os::unix::fs::PermissionsExt::mode(
            &fs::metadata(lock_path.parent().unwrap())
                .unwrap()
                .permissions(),
        );
        let file_mode = std::os::unix::fs::PermissionsExt::mode(
            &fs::metadata(&lock_path).unwrap().permissions(),
        );
        assert_eq!(0o700, directory_mode & 0o777);
        assert_eq!(0o600, file_mode & 0o777);
    }
    assert!(matches!(
        runtime
            .thread_queue()
            .claim_client_binding_dispatch(&parent_lock, &record.id, "parent-owner", 100, 110)
            .await
            .unwrap(),
        QueuedClientDispatchClaimOutcome::Acquired(_)
    ));

    let run_child = |mode: &str| {
        let output = Command::new(std::env::current_exe().expect("current test executable"))
            .arg("--exact")
            .arg(
                "runtime::queued_items::tests::cross_process_dispatch_lock_requires_kernel_owner_release",
            )
            .arg("--nocapture")
            .env(CHILD_MODE, mode)
            .env(CHILD_HOME, runtime.sqlite().home())
            .env(CHILD_THREAD, thread_id.to_string())
            .env(CHILD_ITEM, &record.id)
            .output()
            .expect("spawn dispatch-lock child");
        assert!(
            output.status.success(),
            "dispatch-lock child `{mode}` failed\nstdout:\n{}\nstderr:\n{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr),
        );
    };
    run_child("blocked");
    drop(parent_lock);
    run_child("expired");
}

#[cfg(unix)]
#[tokio::test]
async fn dispatch_lock_root_is_canonical_anchored_and_replacement_fails_closed() {
    let parent = unique_temp_dir();
    let real_home = parent.join("real-home");
    let redirected_home = parent.join("redirected-home");
    let configured_home = parent.join("configured-home");
    fs::create_dir_all(&real_home).unwrap();
    fs::create_dir_all(&redirected_home).unwrap();
    std::os::unix::fs::symlink(&real_home, &configured_home).unwrap();

    let runtime = StateRuntime::init(
        crate::SqliteConfig::new_for_testing(configured_home.as_path().abs()),
        "test-provider".to_string(),
    )
    .await
    .unwrap();
    assert_eq!(
        fs::canonicalize(&real_home).unwrap(),
        runtime.sqlite().home()
    );

    fs::remove_file(&configured_home).unwrap();
    std::os::unix::fs::symlink(&redirected_home, &configured_home).unwrap();
    let thread_id = ThreadId::new();
    let client_id = "canonical-lock-root";
    let digest = test_digest('4');
    let process_lock = runtime
        .thread_queue()
        .try_acquire_client_dispatch_lock(thread_id, client_id, &digest)
        .unwrap()
        .unwrap();
    let file_name = dispatch_lock_file_name(thread_id, client_id, &digest);
    assert!(
        real_home
            .join("queue-dispatch-locks")
            .join(&file_name)
            .is_file()
    );
    assert!(
        !redirected_home
            .join("queue-dispatch-locks")
            .join(&file_name)
            .exists(),
        "retargeting the configured parent must not redirect a live runtime"
    );
    drop(process_lock);

    let lock_directory = real_home.join("queue-dispatch-locks");
    let retired_directory = real_home.join("queue-dispatch-locks-retired");
    fs::rename(&lock_directory, &retired_directory).unwrap();
    fs::create_dir(&lock_directory).unwrap();
    let error = StateRuntime::init(
        crate::SqliteConfig::new_for_testing(real_home.as_path().abs()),
        "test-provider".to_string(),
    )
    .await
    .err()
    .expect("a replacement lock-root inode must fail closed");
    assert!(
        error
            .downcast_ref::<QueuedClientBindingConflict>()
            .is_some(),
        "unexpected lock-root replacement error: {error:#}"
    );
}

#[cfg(unix)]
#[tokio::test]
async fn replacing_a_bound_dispatch_lock_file_fails_closed() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let client_id = "replaced-lock-file";
    let digest = test_digest('5');
    let record = exact_queued_record(
        runtime.as_ref(),
        thread_id,
        client_id,
        &digest,
        &bound_payload(client_id, "replace lock file"),
    )
    .await;
    let old_lock = runtime
        .thread_queue()
        .try_acquire_client_dispatch_lock(thread_id, client_id, &digest)
        .unwrap()
        .unwrap();
    let QueuedClientDispatchClaimOutcome::Acquired(lease) = runtime
        .thread_queue()
        .claim_client_binding_dispatch(&old_lock, &record.id, "owner", 100, 200)
        .await
        .unwrap()
    else {
        panic!("exact row must acquire its first file identity");
    };
    runtime
        .thread_queue()
        .release_client_binding_dispatch(&old_lock, &lease)
        .await
        .unwrap();
    let lock_path = runtime
        .sqlite()
        .home()
        .join("queue-dispatch-locks")
        .join(dispatch_lock_file_name(thread_id, client_id, &digest));
    let retired_path = lock_path.with_extension("retired");
    fs::rename(&lock_path, &retired_path).unwrap();
    drop(old_lock);

    let replacement_lock = runtime
        .thread_queue()
        .try_acquire_client_dispatch_lock(thread_id, client_id, &digest)
        .unwrap()
        .unwrap();
    let error = runtime
        .thread_queue()
        .claim_client_binding_dispatch(&replacement_lock, &record.id, "replacement-owner", 300, 400)
        .await
        .expect_err("a replacement file inode must not inherit dispatch authority");
    assert!(
        error
            .downcast_ref::<QueuedClientBindingConflict>()
            .is_some()
    );
}

#[tokio::test]
async fn competing_runtimes_preserve_fifo_queue_order() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let other = StateRuntime::init(runtime.sqlite().clone(), "test-provider".to_string())
        .await
        .unwrap();
    let queue = runtime.thread_queue();
    let other_queue = other.thread_queue();
    let (first, second) = tokio::join!(
        queue.enqueue(thread_id, r#"{"first":true}"#),
        other_queue.enqueue(thread_id, r#"{"second":true}"#),
    );
    let mut expected = vec![first.unwrap(), second.unwrap()];
    expected.sort_by(|first, second| first.id.cmp(&second.id));
    let mut actual = queue
        .list_page(thread_id, /*offset*/ 0, /*limit*/ 2)
        .await
        .unwrap();
    actual.sort_by(|first, second| first.id.cmp(&second.id));
    assert_eq!(expected, actual);
}

#[tokio::test]
async fn ordinary_queue_limit_remains_per_thread_not_database_wide() {
    let (runtime, first_thread_id) = runtime_with_thread().await;
    let second_thread_id = ThreadId::new();
    for index in 0..MAX_QUEUE_ITEMS {
        runtime
            .thread_queue()
            .enqueue(first_thread_id, &format!(r#"{{"index":{index}}}"#))
            .await
            .unwrap();
    }

    runtime
        .thread_queue()
        .enqueue(second_thread_id, r#"{"second_thread":true}"#)
        .await
        .expect("a second thread must not share the first thread's capacity");

    assert_eq!(
        MAX_QUEUE_ITEMS,
        runtime
            .thread_queue()
            .list_page(first_thread_id, /*offset*/ 0, MAX_QUEUE_ITEMS + 1)
            .await
            .unwrap()
            .len()
    );
    assert_eq!(
        1,
        runtime
            .thread_queue()
            .list_page(second_thread_id, /*offset*/ 0, /*limit*/ 2)
            .await
            .unwrap()
            .len()
    );
}

#[tokio::test]
async fn migrating_existing_queue_backfills_thread_revisions() {
    let home = unique_temp_dir();
    tokio::fs::create_dir_all(&home).await.unwrap();
    let sqlite = crate::SqliteConfig::new_for_testing(home.as_path().abs());
    let queue_path = sqlite.queue_db_path();
    let old_queue_migrator = Migrator {
        migrations: Cow::Owned(vec![QUEUE_MIGRATOR.migrations[0].clone()]),
        ignore_missing: false,
        locking: true,
        no_tx: false,
        table_name: QUEUE_MIGRATOR.table_name.clone(),
        create_schemas: QUEUE_MIGRATOR.create_schemas.clone(),
    };
    let pool = sqlite.open_read_write_pool(&queue_path).await.unwrap();
    old_queue_migrator.run(&pool).await.unwrap();

    let thread_id = ThreadId::new();
    let queued = QueuedUserSubmissionRecord {
        id: Uuid::now_v7().to_string(),
        thread_id,
        payload: r#"{"existing":true}"#.to_string(),
    };
    sqlx::query(
        "INSERT INTO queued_items
         (id, thread_id, payload_json, queue_order, created_at_ms, updated_at_ms)
         VALUES (?, ?, ?, 0, 0, 0)",
    )
    .bind(&queued.id)
    .bind(thread_id.to_string())
    .bind(&queued.payload)
    .execute(&pool)
    .await
    .unwrap();
    pool.close().await;

    let runtime = StateRuntime::init(sqlite, "test-provider".to_string())
        .await
        .unwrap();
    let queue = runtime.thread_queue();
    assert_eq!(
        vec![(thread_id, 1)],
        queue
            .changes_since(/*revision*/ 0, &[thread_id])
            .await
            .unwrap()
    );
    assert_eq!(
        vec![queued],
        queue
            .list_page(thread_id, /*offset*/ 0, /*limit*/ 1)
            .await
            .unwrap()
    );
}

#[tokio::test]
async fn queue_revisions_identify_changed_threads_after_updates_and_deletions() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let queue = runtime.thread_queue();
    let first = queue.enqueue(thread_id, r#"{"first":true}"#).await.unwrap();
    let first_revision = queue
        .changes_since(/*revision*/ 0, &[thread_id])
        .await
        .unwrap()[0]
        .1;
    queue
        .update(thread_id, &first.id, r#"{"updated":true}"#)
        .await
        .unwrap();
    let updated_revision = queue
        .changes_since(first_revision, &[thread_id])
        .await
        .unwrap()[0]
        .1;
    let other_thread_id = ThreadId::new();
    queue
        .enqueue(other_thread_id, r#"{"other":true}"#)
        .await
        .unwrap();
    let newly_loaded_changes = queue
        .changes_since(/*revision*/ 0, &[other_thread_id])
        .await
        .unwrap();
    assert_eq!(
        vec![(thread_id, updated_revision), newly_loaded_changes[0]],
        queue
            .changes_since(first_revision, &[thread_id, other_thread_id])
            .await
            .unwrap()
    );
    assert!(queue.delete(thread_id, &first.id).await.unwrap());
    assert!(
        queue
            .changes_since(updated_revision, &[thread_id])
            .await
            .unwrap()
            .iter()
            .any(|(changed_thread, _)| *changed_thread == thread_id)
    );
}

#[tokio::test]
async fn fifo_dispatch_preserves_edits_reordering_and_pagination() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let queue = runtime.thread_queue();
    let first = queue.enqueue(thread_id, r#"{"n":1}"#).await.unwrap();
    let second = queue.enqueue(thread_id, r#"{"n":2}"#).await.unwrap();
    let third = queue.enqueue(thread_id, r#"{"n":3}"#).await.unwrap();

    let updated = queue
        .update(thread_id, &first.id, r#"{"n":"edited"}"#)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(first.id, updated.id);
    let error = queue
        .reorder(thread_id, std::slice::from_ref(&first.id))
        .await
        .unwrap_err();
    assert_eq!(
        std::io::ErrorKind::InvalidInput,
        error.downcast_ref::<std::io::Error>().unwrap().kind()
    );

    let ordered_ids = vec![third.id, first.id, second.id];
    queue.reorder(thread_id, &ordered_ids).await.unwrap();

    let items = queue
        .list_page(thread_id, /*offset*/ 0, /*limit*/ 3)
        .await
        .unwrap();
    let page = queue
        .list_page(thread_id, /*offset*/ 1, /*limit*/ 1)
        .await
        .unwrap();
    assert_eq!(vec![items[1].clone()], page);
    assert_eq!(r#"{"n":"edited"}"#, items[1].payload);

    for item in items {
        assert!(queue.delete(thread_id, &item.id).await.unwrap());
    }
    assert!(
        queue
            .list_page(thread_id, /*offset*/ 0, /*limit*/ 1)
            .await
            .unwrap()
            .is_empty()
    );
}

#[tokio::test]
async fn queue_operations_cannot_mutate_another_threads_messages() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let queue = runtime.thread_queue();
    let first = queue.enqueue(thread_id, r#"{"n":1}"#).await.unwrap();
    let other_thread_id = ThreadId::new();
    let other = queue.enqueue(other_thread_id, r#"{"n":2}"#).await.unwrap();
    let other_id = &other.id;

    assert_eq!(
        None,
        queue
            .update(thread_id, other_id, r#"{"n":3}"#)
            .await
            .unwrap()
    );
    assert!(!queue.delete(thread_id, other_id).await.unwrap());
    assert!(
        queue
            .reorder(thread_id, std::slice::from_ref(other_id))
            .await
            .is_err()
    );
    let (items, other_items) = tokio::join!(
        queue.list_page(thread_id, /*offset*/ 0, /*limit*/ 1),
        queue.list_page(other_thread_id, /*offset*/ 0, /*limit*/ 1),
    );
    assert_eq!(
        (vec![first], vec![other]),
        (items.unwrap(), other_items.unwrap())
    );
}

#[tokio::test]
async fn deleting_a_thread_removes_its_queue() {
    let (runtime, thread_id) = runtime_with_thread().await;
    runtime
        .thread_queue()
        .enqueue(thread_id, r#"{"n":1}"#)
        .await
        .unwrap();

    assert_eq!(1, runtime.delete_thread(thread_id).await.unwrap());
    assert!(
        runtime
            .thread_queue()
            .list_page(thread_id, /*offset*/ 0, /*limit*/ 1)
            .await
            .unwrap()
            .is_empty()
    );
}

#[tokio::test]
async fn concurrent_inserts_enforce_the_queue_limit() {
    let (runtime, thread_id) = runtime_with_thread().await;
    let other = StateRuntime::init(runtime.sqlite().clone(), "test-provider".to_string())
        .await
        .unwrap();

    for _ in 0..MAX_QUEUE_ITEMS - 1 {
        runtime
            .thread_queue()
            .enqueue(thread_id, r#"{"n":1}"#)
            .await
            .unwrap();
    }
    let (first, second) = tokio::join!(
        runtime.thread_queue().enqueue(thread_id, r#"{"n":2}"#),
        other.thread_queue().enqueue(thread_id, r#"{"n":3}"#),
    );
    assert_ne!(first.is_ok(), second.is_ok());
    assert_eq!(
        MAX_QUEUE_ITEMS,
        runtime
            .thread_queue()
            .list_page(thread_id, /*offset*/ 0, /*limit*/ MAX_QUEUE_ITEMS)
            .await
            .unwrap()
            .len()
    );
}

#[tokio::test]
async fn database_capacity_retains_the_per_thread_limit() {
    let (runtime, first_thread_id) = runtime_with_thread().await;
    let second_thread_id = ThreadId::new();
    let capacity = MAX_QUEUE_ITEMS + 1;
    for index in 0..MAX_QUEUE_ITEMS {
        runtime
            .thread_queue()
            .enqueue_with_capacity(
                first_thread_id,
                &format!(r#"{{"index":{index}}}"#),
                capacity,
            )
            .await
            .unwrap();
    }

    let rejected = runtime
        .thread_queue()
        .enqueue_with_capacity(first_thread_id, r#"{"overflow":true}"#, capacity)
        .await
        .expect_err("the per-thread limit must remain active");
    assert_eq!(
        QueueCapacityLimit::Thread,
        rejected
            .downcast_ref::<QueueCapacityExceeded>()
            .expect("typed queue-capacity rejection")
            .limit
    );
    runtime
        .thread_queue()
        .enqueue_with_capacity(second_thread_id, r#"{"other_thread":true}"#, capacity)
        .await
        .expect("another thread can use the final database-wide slot");
}

#[tokio::test]
async fn concurrent_writers_never_exceed_database_capacity_across_threads() {
    const CAPACITY: usize = 3;

    let (runtime, first_thread_id) = runtime_with_thread().await;
    let other = StateRuntime::init(runtime.sqlite().clone(), "test-provider".to_string())
        .await
        .unwrap();
    let second_thread_id = ThreadId::new();
    runtime
        .thread_queue()
        .enqueue_with_capacity(first_thread_id, r#"{"n":1}"#, CAPACITY)
        .await
        .unwrap();
    runtime
        .thread_queue()
        .enqueue_with_capacity(second_thread_id, r#"{"n":2}"#, CAPACITY)
        .await
        .unwrap();

    let (first, second) = tokio::join!(
        runtime
            .thread_queue()
            .enqueue_with_capacity(first_thread_id, r#"{"n":3}"#, CAPACITY,),
        other
            .thread_queue()
            .enqueue_with_capacity(second_thread_id, r#"{"n":4}"#, CAPACITY,),
    );
    assert_ne!(first.is_ok(), second.is_ok());
    let rejected = first.err().or_else(|| second.err()).unwrap();
    assert_eq!(
        QueueCapacityLimit::Runtime,
        rejected
            .downcast_ref::<QueueCapacityExceeded>()
            .expect("typed queue-capacity rejection")
            .limit
    );

    let (first_items, second_items) = tokio::join!(
        runtime.thread_queue().list_page(
            first_thread_id,
            /*offset*/ 0,
            /*limit*/ CAPACITY
        ),
        runtime.thread_queue().list_page(
            second_thread_id,
            /*offset*/ 0,
            /*limit*/ CAPACITY
        ),
    );
    assert_eq!(
        CAPACITY,
        first_items.unwrap().len() + second_items.unwrap().len()
    );
}

#[tokio::test]
async fn isolated_queue_databases_have_independent_capacities() {
    const CAPACITY: usize = 1;

    let (first_runtime, first_thread_id) = runtime_with_thread().await;
    let (second_runtime, second_thread_id) = runtime_with_thread().await;
    let (first, second) = tokio::join!(
        first_runtime.thread_queue().enqueue_with_capacity(
            first_thread_id,
            r#"{"agent":"first"}"#,
            CAPACITY,
        ),
        second_runtime.thread_queue().enqueue_with_capacity(
            second_thread_id,
            r#"{"agent":"second"}"#,
            CAPACITY,
        ),
    );
    assert!(first.is_ok());
    assert!(second.is_ok());

    assert!(
        first_runtime
            .thread_queue()
            .enqueue_with_capacity(first_thread_id, r#"{"overflow":true}"#, CAPACITY)
            .await
            .is_err()
    );
    assert!(
        second_runtime
            .thread_queue()
            .enqueue_with_capacity(second_thread_id, r#"{"overflow":true}"#, CAPACITY)
            .await
            .is_err()
    );
}
