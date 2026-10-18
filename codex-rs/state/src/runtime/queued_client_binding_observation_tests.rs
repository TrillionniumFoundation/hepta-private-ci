type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

use super::*;
use crate::QueuedClientBindingFinalizeMode;
use crate::QueuedClientBindingFinalizeOutcome;
use crate::QueuedClientBindingFinalizeRequest;
use crate::QueuedClientBindingReserveOutcome;
use crate::QueuedClientDispatchClaimOutcome;
use crate::StateRuntime;
use crate::runtime::test_support::test_thread_metadata;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::time::Duration;

async fn runtime_with_thread() -> TestResult<(Arc<StateRuntime>, ThreadId)> {
    let home = unique_temp_dir();
    let runtime = StateRuntime::init(
        crate::SqliteConfig::new_for_testing(home.as_path().abs()),
        "test-provider".to_string(),
    )
    .await?;
    let thread_id = ThreadId::new();
    runtime
        .upsert_thread(&test_thread_metadata(
            home.as_path(),
            thread_id,
            home.clone(),
        ))
        .await?;
    Ok((runtime, thread_id))
}

fn bound_payload(client_id: &str, text: &str) -> TestResult<(String, String)> {
    let content = vec![UserInput::Text {
        text: text.to_string(),
        text_elements: Vec::new(),
    }];
    let digest = user_input_payload_sha256(&content)?;
    let payload = serde_json::json!({
        "UserInput": {"content": content, "client_id": client_id}
    })
    .to_string();
    Ok((payload, digest))
}

async fn queue_exact(
    queue: &SqliteQueueStore,
    thread_id: ThreadId,
    client_id: &str,
    payload: &str,
    digest: &str,
) -> TestResult<QueuedUserSubmissionRecord> {
    let QueuedClientBindingReserveOutcome::Reserved(lease) = queue
        .reserve_client_binding(thread_id, client_id, digest, payload)
        .await?
    else {
        panic!("new identity must reserve");
    };
    let QueuedClientBindingFinalizeOutcome::Queued { record, .. } = queue
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
        .await?
    else {
        panic!("reservation must create a queue row");
    };
    Ok(record)
}

async fn binding_snapshot(queue: &SqliteQueueStore) -> TestResult<Vec<String>> {
    Ok(sqlx::query_scalar(
        "SELECT json_object(
            'thread', thread_id, 'client', client_user_message_id,
            'digest', payload_sha256, 'state', state, 'queue', queued_item_id,
            'turn', turn_id, 'reservation', reservation_id, 'revision', revision,
            'owner', dispatch_owner_id, 'expiry', dispatch_lease_expires_at_ms,
            'device', dispatch_lock_device, 'inode', dispatch_lock_inode,
            'created', created_at_ms, 'updated', updated_at_ms)
         FROM queued_client_bindings ORDER BY thread_id, client_user_message_id",
    )
    .fetch_all(queue.pool.as_ref())
    .await?)
}

async fn force_next_query_to_open_a_cold_connection(
    pool: &sqlx::SqlitePool,
) -> TestResult<Vec<sqlx::pool::PoolConnection<sqlx::Sqlite>>> {
    let mut held = Vec::new();
    for _ in 0..5 {
        held.push(pool.acquire().await?);
    }
    held.pop()
        .ok_or("cold connection fixture has no held connection")?
        .close()
        .await?;
    assert_eq!(pool.size(), 4);
    Ok(held)
}

#[tokio::test]
async fn observation_reads_exact_queue_without_writing_under_another_writer_lock() -> TestResult {
    let (runtime, thread_id) = runtime_with_thread().await?;
    let queue = runtime.thread_queue();
    let (payload, digest) = bound_payload("client-a", "first message")?;
    let record = queue_exact(queue, thread_id, "client-a", &payload, &digest).await?;
    let before = binding_snapshot(queue).await?;
    let writer_pool = runtime
        .sqlite()
        .open_read_write_pool(&runtime.sqlite().queue_db_path())
        .await?;
    let held = force_next_query_to_open_a_cold_connection(queue.pool.as_ref()).await?;
    let mut writer = writer_pool.begin_with("BEGIN IMMEDIATE").await?;
    sqlx::query("UPDATE queued_client_bindings SET updated_at_ms=updated_at_ms+1")
        .execute(&mut *writer)
        .await?;
    let observed = tokio::time::timeout(
        Duration::from_secs(/*secs*/ 1),
        queue.observe_client_binding(thread_id, "client-a", &digest),
    )
    .await??;
    assert_eq!(
        observed,
        Some(QueuedClientBindingObservation::Queued(record))
    );
    assert_eq!(
        queue
            .observe_client_binding(thread_id, "absent-client", &digest)
            .await?,
        None
    );
    assert_eq!(
        queue
            .observe_client_binding(ThreadId::new(), "client-a", &digest)
            .await?,
        None
    );
    assert_eq!(binding_snapshot(queue).await?, before);
    writer.rollback().await?;
    drop(held);
    writer_pool.close().await;
    Ok(())
}

#[tokio::test]
async fn rollout_path_observation_uses_a_cold_connection_under_another_writer_lock() -> TestResult {
    let (runtime, thread_id) = runtime_with_thread().await?;
    let expected = runtime
        .find_rollout_path_by_id(thread_id, /*archived_only*/ None)
        .await?;
    assert!(expected.is_some());
    let writer_pool = runtime
        .sqlite()
        .open_read_write_pool(&runtime.sqlite().state_db_path())
        .await?;
    let held = force_next_query_to_open_a_cold_connection(runtime.pool.as_ref()).await?;
    let mut writer = writer_pool.begin_with("BEGIN IMMEDIATE").await?;
    sqlx::query("UPDATE threads SET rollout_path='uncommitted-path' WHERE id=?")
        .bind(thread_id.to_string())
        .execute(&mut *writer)
        .await?;
    let observed = tokio::time::timeout(
        Duration::from_secs(/*secs*/ 1),
        runtime.find_rollout_path_by_id(thread_id, /*archived_only*/ None),
    )
    .await??;
    assert_eq!(observed, expected);
    writer.rollback().await?;
    assert_eq!(
        runtime
            .find_rollout_path_by_id(thread_id, /*archived_only*/ None)
            .await?,
        expected
    );
    drop(held);
    writer_pool.close().await;
    Ok(())
}

#[tokio::test]
async fn observation_preserves_reservations_and_cancelled_tombstones() -> TestResult {
    let (runtime, thread_id) = runtime_with_thread().await?;
    let queue = runtime.thread_queue();
    let (payload, digest) = bound_payload("reserved-client", "pending admission")?;
    queue
        .reserve_client_binding(thread_id, "reserved-client", &digest, &payload)
        .await?;
    let before = binding_snapshot(queue).await?;
    assert_eq!(
        queue
            .observe_client_binding(thread_id, "reserved-client", &digest)
            .await?,
        Some(QueuedClientBindingObservation::Reserved)
    );
    assert_eq!(binding_snapshot(queue).await?, before);
    let (payload, digest) = bound_payload("cancelled-client", "cancel this")?;
    let record = queue_exact(queue, thread_id, "cancelled-client", &payload, &digest).await?;
    assert!(queue.delete(thread_id, &record.id).await?);
    let before = binding_snapshot(queue).await?;
    assert_eq!(
        queue
            .observe_client_binding(thread_id, "cancelled-client", &digest)
            .await?,
        Some(QueuedClientBindingObservation::Cancelled)
    );
    let (_, wrong_digest) = bound_payload("cancelled-client", "different payload")?;
    assert!(
        queue
            .observe_client_binding(thread_id, "cancelled-client", &wrong_digest)
            .await
            .is_err()
    );
    assert_eq!(binding_snapshot(queue).await?, before);
    assert_eq!(
        queue
            .list_page(thread_id, /*offset*/ 0, /*limit*/ 100)
            .await?,
        Vec::<QueuedUserSubmissionRecord>::new()
    );
    Ok(())
}

#[tokio::test]
async fn observation_rejects_queue_payload_and_client_binding_mismatches() -> TestResult {
    let (runtime, thread_id) = runtime_with_thread().await?;
    let queue = runtime.thread_queue();
    let (payload, digest) = bound_payload("client-a", "original content")?;
    let record = queue_exact(queue, thread_id, "client-a", &payload, &digest).await?;
    let (_, wrong_digest) = bound_payload("client-a", "different content")?;
    assert!(
        queue
            .observe_client_binding(thread_id, "client-a", &wrong_digest)
            .await
            .is_err()
    );
    for (client_id, text) in [
        ("other-client", "original content"),
        ("client-a", "changed"),
    ] {
        let (forged_payload, _) = bound_payload(client_id, text)?;
        sqlx::query("UPDATE queued_items SET payload_json = ? WHERE id = ?")
            .bind(&forged_payload)
            .bind(&record.id)
            .execute(queue.pool.as_ref())
            .await?;
        let before = binding_snapshot(queue).await?;
        assert!(
            queue
                .observe_client_binding(thread_id, "client-a", &digest)
                .await
                .is_err()
        );
        assert_eq!(binding_snapshot(queue).await?, before);
        assert_eq!(
            queue
                .list_page(thread_id, /*offset*/ 0, /*limit*/ 100)
                .await?,
            vec![QueuedUserSubmissionRecord {
                payload: forged_payload,
                ..record.clone()
            }]
        );
    }
    Ok(())
}

#[tokio::test]
async fn observation_reads_live_dispatch_and_persisted_turn_without_consuming_authority()
-> TestResult {
    let (runtime, thread_id) = runtime_with_thread().await?;
    let queue = runtime.thread_queue();
    let (payload, digest) = bound_payload("client-a", "dispatch this")?;
    let record = queue_exact(queue, thread_id, "client-a", &payload, &digest).await?;
    let process_lock = queue
        .try_acquire_client_dispatch_lock(thread_id, "client-a", &digest)?
        .ok_or("original dispatch lock is unavailable")?;
    let QueuedClientDispatchClaimOutcome::Acquired(lease) = queue
        .claim_client_binding_dispatch(
            &process_lock,
            &record.id,
            "dispatch-owner",
            /*now_ms*/ 100,
            /*lease_expires_at_ms*/ 200,
        )
        .await?
    else {
        panic!("exact dispatch must acquire authority");
    };
    let before = binding_snapshot(queue).await?;
    assert_eq!(
        queue
            .observe_client_binding(thread_id, "client-a", &digest)
            .await?,
        Some(QueuedClientBindingObservation::Dispatching(record))
    );
    assert_eq!(binding_snapshot(queue).await?, before);
    queue
        .complete_client_binding_dispatch(&process_lock, &lease, "persisted-turn")
        .await?;
    let before = binding_snapshot(queue).await?;
    assert_eq!(
        queue
            .observe_client_binding(thread_id, "client-a", &digest)
            .await?,
        Some(QueuedClientBindingObservation::Persisted {
            turn_id: "persisted-turn".to_string()
        })
    );
    assert_eq!(binding_snapshot(queue).await?, before);
    Ok(())
}
