use super::*;
use crate::runtime::test_support::unique_temp_dir;
use codex_protocol::protocol::SessionSource;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;

async fn runtime(home: &std::path::Path) -> std::sync::Arc<StateRuntime> {
    StateRuntime::init(
        crate::SqliteConfig::new_for_testing(home.abs()),
        "test".into(),
    )
    .await
    .unwrap()
}

fn reservation(home: &std::path::Path) -> ThreadCreationReservation {
    ThreadCreationReservation {
        idempotency_key: "original-create".into(),
        parameters_sha256: "a".repeat(64),
        thread_id: ThreadId::default(),
        project_id: None,
        cwd: home.to_owned(),
        thread_source: "null".into(),
    }
}

#[tokio::test]
async fn crash_after_binding_preserves_identity_and_never_admits_another_create()
-> anyhow::Result<()> {
    let home = unique_temp_dir();
    let state = runtime(&home).await;
    let bound = reservation(&home);
    assert_eq!(
        state.reserve_thread_creation(&bound).await?,
        ThreadCreationReserveOutcome::Reserved
    );
    drop(state);
    let cold = runtime(&home).await;
    let mut retried = bound.clone();
    retried.thread_id = ThreadId::default();
    let record = cold
        .read_thread_creation(&bound.idempotency_key)
        .await?
        .unwrap();
    assert_eq!(record.reservation, bound);
    assert_eq!(record.phase, ThreadCreationPhase::Pending);
    assert_eq!(
        cold.reserve_thread_creation(&retried).await?,
        ThreadCreationReserveOutcome::Existing(record)
    );
    assert_eq!(cold.get_thread(bound.thread_id).await?, None);
    Ok(())
}

#[tokio::test]
async fn parameter_or_scope_collision_fails_without_changing_the_original_record()
-> anyhow::Result<()> {
    let home = unique_temp_dir();
    let state = runtime(&home).await;
    let bound = reservation(&home);
    state.reserve_thread_creation(&bound).await?;
    let original = state.read_thread_creation(&bound.idempotency_key).await?;
    let mut changed = bound.clone();
    changed.parameters_sha256 = "b".repeat(64);
    assert!(state.reserve_thread_creation(&changed).await.is_err());
    changed = bound.clone();
    changed.cwd = home.join("other");
    assert!(state.reserve_thread_creation(&changed).await.is_err());
    changed = bound.clone();
    changed.thread_source = "other".into();
    assert!(state.reserve_thread_creation(&changed).await.is_err());
    changed = bound.clone();
    changed.project_id = Some("foreign".into());
    assert!(state.reserve_thread_creation(&changed).await.is_err());
    assert_eq!(
        state.read_thread_creation(&bound.idempotency_key).await?,
        original
    );
    Ok(())
}

#[tokio::test]
async fn simultaneous_reservation_has_one_effect_admission_and_one_fixed_id() -> anyhow::Result<()>
{
    let home = unique_temp_dir();
    let state = runtime(&home).await;
    let first = reservation(&home);
    let mut second = first.clone();
    second.thread_id = ThreadId::default();
    let (left, right) = tokio::join!(
        state.reserve_thread_creation(&first),
        state.reserve_thread_creation(&second)
    );
    let results = [left?, right?];
    assert_eq!(
        results
            .iter()
            .filter(|outcome| matches!(outcome, ThreadCreationReserveOutcome::Reserved))
            .count(),
        1
    );
    let record = state
        .read_thread_creation(&first.idempotency_key)
        .await?
        .unwrap();
    assert!(
        record.reservation.thread_id == first.thread_id
            || record.reservation.thread_id == second.thread_id
    );
    assert!(results.iter().any(|outcome| matches!(outcome, ThreadCreationReserveOutcome::Existing(existing) if existing == &record)));
    Ok(())
}

#[tokio::test]
async fn persist_commit_gap_keeps_prepared_receipt_and_exact_path_after_cold_open()
-> anyhow::Result<()> {
    let home = unique_temp_dir();
    let state = runtime(&home).await;
    let bound = reservation(&home);
    state.reserve_thread_creation(&bound).await?;
    let path = home.join("original.jsonl");
    state
        .bind_thread_creation_rollout(bound.thread_id, &home, "null", &path)
        .await?;
    state
        .prepare_thread_creation_receipt(&bound, "{\"original\":true}")
        .await?;
    tokio::fs::write(&path, "original durable rollout\n").await?;
    drop(state);
    let cold = runtime(&home).await;
    let pending = cold
        .read_thread_creation(&bound.idempotency_key)
        .await?
        .unwrap();
    assert_eq!(pending.phase, ThreadCreationPhase::Pending);
    assert_eq!(pending.rollout_path, Some(path));
    assert_eq!(pending.receipt_json.as_deref(), Some("{\"original\":true}"));
    cold.commit_thread_creation_receipt(&bound).await?;
    drop(cold);
    let cold = runtime(&home).await;
    assert_eq!(
        cold.read_thread_creation(&bound.idempotency_key)
            .await?
            .unwrap()
            .phase,
        ThreadCreationPhase::Created
    );
    Ok(())
}

#[tokio::test]
async fn delete_fence_and_permanent_key_tombstone_reject_late_projection_and_commit()
-> anyhow::Result<()> {
    let home = unique_temp_dir();
    let state = runtime(&home).await;
    let bound = reservation(&home);
    state.reserve_thread_creation(&bound).await?;
    let path = home.join("original.jsonl");
    state
        .bind_thread_creation_rollout(bound.thread_id, &home, "null", &path)
        .await?;
    state.prepare_thread_creation_receipt(&bound, "{}").await?;
    state.delete_threads_strict(&[bound.thread_id]).await?;
    assert!(state.commit_thread_creation_receipt(&bound).await.is_err());
    let metadata =
        crate::ThreadMetadataBuilder::new(bound.thread_id, path, Utc::now(), SessionSource::Cli)
            .build("test");
    assert!(state.insert_thread_if_absent(&metadata).await.is_err());
    assert!(state.upsert_thread(&metadata).await.is_err());
    drop(state);
    let cold = runtime(&home).await;
    let record = cold
        .read_thread_creation(&bound.idempotency_key)
        .await?
        .unwrap();
    assert_eq!(record.phase, ThreadCreationPhase::Deleted);
    let mut retried = bound.clone();
    retried.thread_id = ThreadId::default();
    assert_eq!(
        cold.reserve_thread_creation(&retried).await?,
        ThreadCreationReserveOutcome::Existing(record)
    );
    assert_eq!(cold.get_thread(bound.thread_id).await?, None);
    Ok(())
}

#[tokio::test]
async fn migration_from_previous_state_preserves_rows_and_installs_original_owner_triggers()
-> anyhow::Result<()> {
    let home = unique_temp_dir();
    let state = runtime(&home).await;
    let id = ThreadId::default();
    let metadata = crate::ThreadMetadataBuilder::new(
        id,
        home.join("old.jsonl"),
        Utc::now(),
        SessionSource::Cli,
    )
    .build("test");
    state.upsert_thread(&metadata).await?;
    sqlx::query("DROP TRIGGER thread_creation_deleted_insert")
        .execute(state.pool.as_ref())
        .await?;
    sqlx::query("DROP TRIGGER thread_creation_deleted_update")
        .execute(state.pool.as_ref())
        .await?;
    sqlx::query("DROP TABLE thread_creation_operations")
        .execute(state.pool.as_ref())
        .await?;
    sqlx::query("DELETE FROM _sqlx_migrations WHERE version = 51")
        .execute(state.pool.as_ref())
        .await?;
    let before = state.get_thread(id).await?;
    drop(state);
    let cold = runtime(&home).await;
    assert_eq!(cold.get_thread(id).await?, before);
    assert_eq!(cold.read_thread_creation("absent").await?, None);
    let triggers: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'thread_creation_deleted_%'").fetch_one(cold.pool.as_ref()).await?;
    assert_eq!(triggers, 2);
    Ok(())
}

#[tokio::test]
async fn reserved_abandonment_is_permanent_and_repeated_exact_actions_are_idempotent()
-> anyhow::Result<()> {
    let home = unique_temp_dir();
    let state = runtime(&home).await;
    let bound = reservation(&home);
    state.reserve_thread_creation(&bound).await?;
    assert!(state.abandon_reserved_thread_creation(&bound).await?);
    assert!(state.abandon_reserved_thread_creation(&bound).await?);
    let path = home.join("late.jsonl");
    assert!(
        state
            .bind_thread_creation_rollout(bound.thread_id, &home, "null", &path)
            .await
            .is_err()
    );
    assert!(
        state
            .prepare_thread_creation_receipt(&bound, "{}")
            .await
            .is_err()
    );
    assert!(state.commit_thread_creation_receipt(&bound).await.is_err());
    let metadata =
        crate::ThreadMetadataBuilder::new(bound.thread_id, path, Utc::now(), SessionSource::Cli)
            .build("test");
    assert!(state.insert_thread_if_absent(&metadata).await.is_err());
    assert!(state.upsert_thread(&metadata).await.is_err());
    let mut changed = bound.clone();
    changed.parameters_sha256 = "b".repeat(64);
    assert!(
        state
            .abandon_reserved_thread_creation(&changed)
            .await
            .is_err()
    );
    drop(state);
    let cold = runtime(&home).await;
    let original = cold
        .read_thread_creation(&bound.idempotency_key)
        .await?
        .unwrap();
    assert_eq!(original.phase, ThreadCreationPhase::Abandoned);
    assert_eq!(original.rollout_path, None);
    assert_eq!(original.receipt_json, None);
    assert!(cold.abandon_reserved_thread_creation(&bound).await?);
    changed = bound.clone();
    changed.thread_id = ThreadId::default();
    assert_eq!(
        cold.reserve_thread_creation(&changed).await?,
        ThreadCreationReserveOutcome::Existing(original)
    );
    Ok(())
}

#[tokio::test]
async fn abandon_and_original_lazy_path_binding_have_exactly_one_winner() -> anyhow::Result<()> {
    for _ in 0..8 {
        let home = unique_temp_dir();
        let state = runtime(&home).await;
        let bound = reservation(&home);
        let path = home.join("original.jsonl");
        state.reserve_thread_creation(&bound).await?;
        let (abandoned, binding) = tokio::join!(
            state.abandon_reserved_thread_creation(&bound),
            state.bind_thread_creation_rollout(bound.thread_id, &home, "null", &path)
        );
        let abandoned = abandoned?;
        assert_eq!(abandoned, binding.is_err());
        if abandoned {
            assert_eq!(
                state
                    .read_thread_creation(&bound.idempotency_key)
                    .await?
                    .unwrap()
                    .phase,
                ThreadCreationPhase::Abandoned
            );
        } else {
            // Missing files after a bound path remain unknown, never cancelled.
            assert!(!path.exists());
            let before = state.read_thread_creation(&bound.idempotency_key).await?;
            assert!(!state.abandon_reserved_thread_creation(&bound).await?);
            state.prepare_thread_creation_receipt(&bound, "{}").await?;
            assert!(!state.abandon_reserved_thread_creation(&bound).await?);
            assert_eq!(
                state
                    .read_thread_creation(&bound.idempotency_key)
                    .await?
                    .unwrap()
                    .rollout_path,
                before.unwrap().rollout_path
            );
        }
    }
    Ok(())
}
