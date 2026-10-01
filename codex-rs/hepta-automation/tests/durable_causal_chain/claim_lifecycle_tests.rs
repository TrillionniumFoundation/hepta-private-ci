use super::*;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowTransition;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn first_dispatch_intent_requires_live_both_leases_but_unknown_replay_does_not() {
    for (timer_lease_ms, taskflow_lease_ms) in [(10, 30_000), (30_000, 10)] {
        let fixture = Fixture::new();
        let store = AutomationStore::open(&fixture.layout).await.unwrap();
        let task = draft(
            "019153a4-3088-7000-a56a-9b1964f75122",
            AutomationSchedule::Once,
            100,
        );
        store.create_task(&task).await.unwrap();
        let lease = store
            .claim_due(100, 1, timer_lease_ms)
            .await
            .unwrap()
            .unwrap();
        let occurrence = store.materialize_occurrence(&lease, 100).await.unwrap();
        store
            .prepare_occurrence_taskflow(&occurrence, &lease, 100, taskflow_lease_ms)
            .await
            .unwrap();
        assert_eq!(
            store.record_dispatch_uncertain(&lease, 110).await,
            Err(AutomationError::Conflict)
        );
        assert_eq!(store.uncertain_dispatches(1).await.unwrap(), Vec::new());
        store.record_dispatch_uncertain(&lease, 109).await.unwrap();
        store
            .record_dispatch_uncertain(&lease, 200_000)
            .await
            .unwrap();
        assert_eq!(store.uncertain_dispatches(1).await.unwrap().len(), 1);
        assert_eq!(store.claim_due(200_000, 2, 30_000).await.unwrap(), None);
        store.close().await;
    }
}

#[tokio::test]
async fn first_dispatch_intent_rejects_a_quarantined_taskflow_run() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.unwrap();
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75124",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.unwrap();
    let lease = store.claim_due(100, 1, 30_000).await.unwrap().unwrap();
    let occurrence = store.materialize_occurrence(&lease, 100).await.unwrap();
    let dispatch = store
        .prepare_occurrence_taskflow(&occurrence, &lease, 100, 30_000)
        .await
        .unwrap();
    store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                &occurrence.taskflow_run_id,
                "quarantine-before-queue-intent",
                dispatch.fence,
                dispatch.run.revision,
                TaskFlowTransition::Indeterminate {
                    reason: "quarantined before provider contact".to_string(),
                },
                101,
            )
            .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(
        store.record_dispatch_uncertain(&lease, 102).await,
        Err(AutomationError::Conflict)
    );
    assert_eq!(store.uncertain_dispatches(1).await.unwrap(), Vec::new());
    store.close().await;
}

#[tokio::test]
async fn expired_pre_dispatch_claim_settles_its_old_step_before_attempt_rollover() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.unwrap();
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75121",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.unwrap();
    let old = store.claim_due(100, 1, 10).await.unwrap().unwrap();
    let original = store.materialize_occurrence(&old, 100).await.unwrap();
    let dispatch = store
        .prepare_occurrence_taskflow(&original, &old, 100, 10)
        .await
        .unwrap();
    let reclaimed = store.claim_due(111, 1, 30_000).await.unwrap().unwrap();
    assert_eq!(reclaimed.occurrence, old.occurrence);
    assert_eq!(
        store.record_dispatch_uncertain(&old, 111).await,
        Err(AutomationError::Conflict)
    );
    let next = store.materialize_occurrence(&reclaimed, 111).await.unwrap();
    assert_eq!(next.occurrence_id, original.occurrence_id);
    assert_eq!(next.step_attempt, 2);
    let old_step = store
        .read_taskflow_step(&original.taskflow_run_id, "codex_turn", 1, &dispatch.fence)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(old_step.state, TaskFlowStepState::Reconciled);
    assert_eq!(
        old_step.final_outcome,
        Some(TaskFlowReconcileOutcome::Cancelled)
    );
    store
        .prepare_occurrence_taskflow(&next, &reclaimed, 111, 30_000)
        .await
        .unwrap();
    store
        .record_dispatch_uncertain(&reclaimed, 111)
        .await
        .unwrap();
    store
        .record_occurrence_admitted(
            &reclaimed,
            &AutomationQueueReceipt {
                queued_submission_id: "expired.claim.retry".to_string(),
                client_user_message_id: reclaimed.client_user_message_id.clone(),
            },
            112,
        )
        .await
        .unwrap();
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout).await.unwrap();
    let admitted = reopened
        .automation_occurrence(task.task_id, 1)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(admitted.step_attempt, 2);
    assert_eq!(admitted.state, AutomationOccurrenceState::Admitted);
    reopened.close().await;
}

#[tokio::test]
async fn disabling_a_requeued_pre_step_crash_settles_its_local_policy_freeze() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.unwrap();
    let template = draft(
        "019153a4-3088-7000-a56a-9b1964f75125",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&template).await.unwrap();
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(SuccessQueue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .unwrap();
    scheduler.tick(100).await.unwrap();
    let definition = store
        .taskflow_definition("hepta.automation.codex-turn", 1)
        .await
        .unwrap()
        .unwrap();
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75126",
        AutomationSchedule::Once,
        200,
    );
    store.create_task(&task).await.unwrap();
    let lease = store.claim_due(200, 1, 30_000).await.unwrap().unwrap();
    let occurrence = store.materialize_occurrence(&lease, 200).await.unwrap();
    let fence = TaskFlowFence::new(
        lease.task.owner_agent_id.clone(),
        format!("automation.scheduler:{}", task.task_id),
        1,
        1,
        lease.lease_token.clone(),
    )
    .unwrap();
    store
        .create_taskflow_run(
            &occurrence.taskflow_run_id,
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            THREAD_ID,
            200,
        )
        .await
        .unwrap();
    let run = store
        .claim_taskflow_run(&occurrence.taskflow_run_id, &fence, 200, 30_000)
        .await
        .unwrap();
    store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                &occurrence.taskflow_run_id,
                "start-before-step-crash",
                fence.clone(),
                run.revision,
                TaskFlowTransition::Start,
                200,
            )
            .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(store.recover_stale_generation(2, 201).await.unwrap(), 1);
    assert_eq!(
        store
            .taskflow_run(&occurrence.taskflow_run_id)
            .await
            .unwrap()
            .unwrap()
            .state,
        TaskFlowRunState::Queued
    );
    assert_eq!(
        store
            .read_taskflow_step(&occurrence.taskflow_run_id, "codex_turn", 1, &fence)
            .await
            .unwrap(),
        None
    );
    store
        .set_enabled(task.task_id, false, None, 202)
        .await
        .unwrap();
    assert_eq!(
        store
            .automation_occurrence(task.task_id, 1)
            .await
            .unwrap()
            .unwrap()
            .state,
        AutomationOccurrenceState::Cancelled
    );
    assert_eq!(
        store
            .taskflow_run(&occurrence.taskflow_run_id)
            .await
            .unwrap()
            .unwrap()
            .state,
        TaskFlowRunState::Cancelled
    );
    assert_eq!(
        store
            .set_schedule_policy(
                task.task_id,
                1,
                AutomationMissedRunPolicy::Coalesce,
                AutomationOverlapPolicy::Allow,
                203,
            )
            .await
            .unwrap()
            .revision,
        2
    );
    store.close().await;
}

#[tokio::test]
async fn schedule_retirement_before_dispatch_intent_revokes_provider_admission() {
    for retirement in [
        AutomationTaskState::Disabled,
        AutomationTaskState::Cancelled,
    ] {
        let fixture = Fixture::new();
        let store = AutomationStore::open(&fixture.layout).await.unwrap();
        let task = draft(
            "019153a4-3088-7000-a56a-9b1964f75120",
            AutomationSchedule::Once,
            100,
        );
        store.create_task(&task).await.unwrap();
        let lease = store.claim_due(100, 1, 30_000).await.unwrap().unwrap();
        let occurrence = store.materialize_occurrence(&lease, 100).await.unwrap();
        store
            .prepare_occurrence_taskflow(&occurrence, &lease, 100, 30_000)
            .await
            .unwrap();
        match retirement {
            AutomationTaskState::Disabled => {
                store
                    .set_enabled(task.task_id, false, None, 101)
                    .await
                    .unwrap();
            }
            AutomationTaskState::Cancelled => {
                store.cancel_task(task.task_id, 101).await.unwrap();
            }
            AutomationTaskState::Enabled | AutomationTaskState::Completed => unreachable!(),
        }
        assert_eq!(
            store.record_dispatch_uncertain(&lease, 102).await,
            Err(AutomationError::Conflict)
        );
        assert_eq!(store.uncertain_dispatches(1).await.unwrap(), Vec::new());
        assert_eq!(store.recover_stale_generation(2, 103).await.unwrap(), 1);
        assert_eq!(
            store
                .automation_occurrence(task.task_id, 1)
                .await
                .unwrap()
                .unwrap()
                .state,
            AutomationOccurrenceState::Cancelled
        );
        store.close().await;
    }
}

#[tokio::test]
async fn absence_recovery_rejects_occurrence_claim_fence_drift_before_step_mutation() {
    for mutation in [
        "claim_token = 'new-claim-token'",
        "claim_generation = 2",
        "step_attempt = 2",
    ] {
        let fixture = Fixture::new();
        let store = AutomationStore::open(&fixture.layout).await.expect("store");
        let task = draft(
            "019153a4-3088-7000-a56a-9b1964f75130",
            AutomationSchedule::Once,
            100,
        );
        store.create_task(&task).await.expect("task");
        let scheduler = AutomationScheduler::new(
            store.clone(),
            Arc::new(UnknownQueue),
            1,
            Duration::from_secs(30),
            Duration::from_secs(2),
        )
        .expect("scheduler");
        scheduler.tick(100).await.expect("unknown dispatch");
        let occurrence = store
            .automation_occurrence(task.task_id, 1)
            .await
            .expect("read")
            .expect("occurrence");
        let before = store
            .taskflow_run(&occurrence.taskflow_run_id)
            .await
            .expect("before");
        let sqlite_home = AbsolutePathBuf::from_absolute_path(fixture.layout.automation_root())
            .expect("sqlite home");
        let pool = SqliteConfig::from_sqlite_home(sqlite_home)
            .open_durable_evidence_pool(store.path())
            .await
            .expect("inspection pool");
        // Model a compatibility-claim rollover observed before its TaskFlow
        // fence is established. Absence belongs to the exact old snapshot.
        // The mutation is selected from this test's fixed SQL literals.
        sqlx::query(sqlx::AssertSqlSafe(format!(
            "UPDATE automation_occurrence_lifecycle SET {mutation}"
        )))
        .execute(&pool)
        .await
        .expect("claim drift");
        assert!(matches!(
            store
                .reconcile_uncertain_occurrence_absent(
                    task.task_id,
                    1,
                    &occurrence.client_user_message_id,
                    &Sha256Digest::for_bytes(b"queue absence"),
                    101
                )
                .await,
            Err(AutomationError::Conflict)
        ));
        assert_eq!(
            store
                .taskflow_run(&occurrence.taskflow_run_id)
                .await
                .expect("after"),
            before
        );
        pool.close().await;
    }
}

#[tokio::test]
async fn queue_absence_cannot_cancel_an_independently_started_provider_effect() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75131",
        AutomationSchedule::Once,
        100,
    );
    store.create_task(&task).await.expect("task");
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(UnknownQueue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect("scheduler");
    scheduler.tick(100).await.expect("unknown dispatch");
    let occurrence = store
        .automation_occurrence(task.task_id, 1)
        .await
        .expect("read")
        .expect("occurrence");
    let before = store
        .taskflow_run(&occurrence.taskflow_run_id)
        .await
        .expect("before");
    let sqlite_home =
        AbsolutePathBuf::from_absolute_path(fixture.layout.automation_root()).expect("sqlite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(store.path())
        .await
        .expect("inspection pool");
    let provider_proof = Sha256Digest::for_bytes(b"independent provider absence");
    // Persist the same pre-contact cut used by authorized effects: external
    // contact may have happened although no provider observation was saved.
    sqlx::query(
        "INSERT INTO taskflow_effect_dispatch_attempts
        (owner_agent_id, run_id, step_id, attempt, intent_digest, payload_digest,
         binding_digest, destination_id, authority_epoch, grant_id,
         grant_nonce_digest, record_command_id, started_at_ms, provider_key_version)
        SELECT owner_agent_id, run_id, step_id, attempt, intent_digest, payload_digest,
               ?, 'provider/independent', 1, 'independent-grant', ?, 'independent-contact', 100, 2
        FROM taskflow_step_outbox WHERE event_kind = 'claimed'",
    )
    .bind(provider_proof.as_str())
    .bind(Sha256Digest::for_bytes(b"independent nonce").as_str())
    .execute(&pool)
    .await
    .expect("provider may have been contacted");
    let queue_proof = Sha256Digest::for_bytes(b"queue absence does not prove provider absence");
    assert!(matches!(
        store
            .reconcile_uncertain_occurrence_absent(
                task.task_id,
                1,
                &occurrence.client_user_message_id,
                &queue_proof,
                101
            )
            .await,
        Err(AutomationError::Conflict)
    ));
    assert_eq!(
        store
            .taskflow_run(&occurrence.taskflow_run_id)
            .await
            .expect("unchanged"),
        before
    );
    sqlx::query(
        "INSERT INTO taskflow_effect_dispatch_observations
        (owner_agent_id, run_id, step_id, attempt, observation, evidence_digest, observed_at_ms)
        SELECT owner_agent_id, run_id, step_id, attempt, 'proven_absent', ?, 102
        FROM taskflow_effect_dispatch_attempts",
    )
    .bind(provider_proof.as_str())
    .execute(&pool)
    .await
    .expect("exact provider absence");
    assert!(matches!(
        store
            .reconcile_uncertain_occurrence_absent(
                task.task_id,
                1,
                &occurrence.client_user_message_id,
                &queue_proof,
                103
            )
            .await,
        Err(AutomationError::Conflict)
    ));
    store
        .reconcile_uncertain_occurrence_absent(
            task.task_id,
            1,
            &occurrence.client_user_message_id,
            &provider_proof,
            104,
        )
        .await
        .expect("matching provider proof permits requeue");
    assert_eq!(
        store
            .taskflow_run(&occurrence.taskflow_run_id)
            .await
            .expect("run")
            .expect("run")
            .state,
        TaskFlowRunState::Queued
    );
    pool.close().await;
}
