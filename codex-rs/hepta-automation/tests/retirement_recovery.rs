//! Real owner-store recovery must retain retirement and immutable dispatch evidence.
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationLease;
use codex_hepta_automation::AutomationQueueReceipt;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTaskState;
use codex_hepta_automation::TimerPhase;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

type TestResult = Result<(), Box<dyn std::error::Error>>;

async fn leased_store() -> Result<
    (
        tempfile::TempDir,
        HeptaAgentLayout,
        AutomationStore,
        AutomationLease,
    ),
    Box<dyn std::error::Error>,
> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let record = registry.register(AgentManifest::new(
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?)?;
    let store = AutomationStore::open(&record.layout).await?;
    store
        .create_task(&AutomationTaskDraft::new(
            "019153a4-3088-7e03-a56a-9b1964f75ddd",
            "bounded owner work",
            AutomationSchedule::FixedInterval { interval_ms: 5_000 },
            /*first_run_at_ms*/ 100,
            /*created_at_ms*/ 1,
        ))
        .await?;
    let lease = store
        .claim_due(
            /*now_ms*/ 100, /*generation*/ 1, /*lease_duration_ms*/ 60_000,
        )
        .await?
        .ok_or("missing initial lease")?;
    Ok((temp, record.layout, store, lease))
}

fn receipt(lease: &AutomationLease) -> AutomationQueueReceipt {
    AutomationQueueReceipt {
        queued_submission_id: "observed.queue.receipt".to_string(),
        client_user_message_id: lease.client_user_message_id.clone(),
    }
}

#[tokio::test]
async fn unknown_dispatch_cannot_be_released_as_a_pre_dispatch_retry() -> TestResult {
    let (_temp, layout, store, lease) = leased_store().await?;
    store
        .record_dispatch_uncertain(&lease, /*observed_at_ms*/ 101)
        .await?;
    assert_eq!(
        store.release_for_retry(&lease).await,
        Err(AutomationError::Conflict)
    );
    store.close().await;
    let reopened = AutomationStore::open(&layout).await?;
    assert_eq!(reopened.uncertain_dispatches(/*limit*/ 10).await?.len(), 1);
    assert_eq!(
        reopened
            .recover_stale_generation(/*current_generation*/ 2)
            .await?,
        0
    );
    assert_eq!(
        reopened
            .claim_due(
                /*now_ms*/ 100_000, /*generation*/ 2, /*lease_duration_ms*/ 100
            )
            .await?,
        None
    );
    reopened.close().await;
    Ok(())
}

#[derive(Clone, Copy, Debug)]
enum ReleasePath {
    PreDispatchRetry,
    StaleGeneration,
    BeforeAdmission,
    NegativeObservation,
}

#[tokio::test]
async fn all_release_paths_preserve_disable_and_cancel_across_restart() -> TestResult {
    for retirement in [
        AutomationTaskState::Disabled,
        AutomationTaskState::Cancelled,
    ] {
        for release in [
            ReleasePath::PreDispatchRetry,
            ReleasePath::StaleGeneration,
            ReleasePath::BeforeAdmission,
            ReleasePath::NegativeObservation,
        ] {
            let (_temp, layout, store, lease) = leased_store().await?;
            if matches!(
                release,
                ReleasePath::BeforeAdmission | ReleasePath::NegativeObservation
            ) {
                store
                    .record_dispatch_uncertain(&lease, /*observed_at_ms*/ 101)
                    .await?;
            }
            let task_id = lease.task.task_id;
            let retired = match retirement {
                AutomationTaskState::Disabled => {
                    store
                        .set_enabled(
                            task_id, /*enabled*/ false, /*resume_at_ms*/ None,
                            /*now_ms*/ 102,
                        )
                        .await?
                }
                AutomationTaskState::Cancelled => {
                    store.cancel_task(task_id, /*now_ms*/ 102).await?
                }
                AutomationTaskState::Enabled | AutomationTaskState::Completed => unreachable!(),
            };
            match release {
                ReleasePath::PreDispatchRetry => store.release_for_retry(&lease).await?,
                ReleasePath::StaleGeneration => {
                    assert_eq!(
                        store
                            .recover_stale_generation(/*current_generation*/ 2)
                            .await?,
                        1
                    );
                }
                ReleasePath::BeforeAdmission => {
                    store.abort_dispatch_before_admission(&lease).await?
                }
                ReleasePath::NegativeObservation => {
                    store
                        .release_uncertain_for_retry(
                            task_id,
                            lease.occurrence,
                            &lease.client_user_message_id,
                        )
                        .await?
                }
            }
            store.close().await;
            let reopened = AutomationStore::open(&layout).await?;
            assert_eq!(reopened.task(task_id).await?, Some(retired));
            assert_eq!(
                reopened
                    .claim_due(
                        /*now_ms*/ 100_000, /*generation*/ 2,
                        /*lease_duration_ms*/ 100,
                    )
                    .await?,
                None
            );
            if retirement == AutomationTaskState::Disabled {
                reopened
                    .set_enabled(
                        task_id,
                        /*enabled*/ true,
                        /*resume_at_ms*/ Some(200_000),
                        /*now_ms*/ 103,
                    )
                    .await?;
                let resumed = reopened
                    .claim_due(
                        /*now_ms*/ 200_000, /*generation*/ 2,
                        /*lease_duration_ms*/ 100,
                    )
                    .await?
                    .ok_or("missing resumed lease")?;
                assert_eq!(resumed.scheduled_for_ms, 200_000, "{release:?}");
                assert_eq!(resumed.occurrence, lease.occurrence + 1, "{release:?}");
                assert_ne!(resumed.client_user_message_id, lease.client_user_message_id);
            } else {
                assert_eq!(
                    reopened
                        .set_enabled(
                            task_id,
                            /*enabled*/ true,
                            /*resume_at_ms*/ Some(200_000),
                            /*now_ms*/ 103,
                        )
                        .await,
                    Err(AutomationError::Conflict)
                );
            }
            reopened.close().await;
        }
    }
    Ok(())
}

#[tokio::test]
async fn receipt_replay_retains_later_control_decisions_and_rejects_substitution() -> TestResult {
    let (_temp, layout, store, lease) = leased_store().await?;
    store
        .record_dispatch_uncertain(&lease, /*observed_at_ms*/ 101)
        .await?;
    let receipt = receipt(&lease);
    let observed = store
        .reconcile_dispatch(
            lease.task.task_id,
            lease.occurrence,
            &receipt,
            /*submitted_at_ms*/ 102,
        )
        .await?;
    assert_eq!(observed.next_run_at_ms, Some(5_100));
    let cancelled = store
        .cancel_task(lease.task.task_id, /*now_ms*/ 103)
        .await?;
    store.close().await;
    let reopened = AutomationStore::open(&layout).await?;
    let replayed = reopened
        .reconcile_dispatch(
            lease.task.task_id,
            lease.occurrence,
            &receipt,
            /*submitted_at_ms*/ 10_000,
        )
        .await?;
    assert_eq!(replayed, cancelled);
    let mut substituted = receipt.clone();
    substituted.queued_submission_id = "different.queue.receipt".to_string();
    assert_eq!(
        reopened
            .reconcile_dispatch(
                lease.task.task_id,
                lease.occurrence,
                &substituted,
                /*submitted_at_ms*/ 10_001,
            )
            .await,
        Err(AutomationError::Conflict)
    );
    substituted = receipt;
    substituted.client_user_message_id = "different.client".to_string();
    assert_eq!(
        reopened
            .reconcile_dispatch(
                lease.task.task_id,
                lease.occurrence,
                &substituted,
                /*submitted_at_ms*/ 10_002,
            )
            .await,
        Err(AutomationError::Conflict)
    );
    assert_eq!(reopened.task(lease.task.task_id).await?, Some(cancelled));
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn reopen_rejects_mismatched_durable_receipt_copies() -> TestResult {
    // These three fixed corruption fixtures do not require dynamic SQL.
    for statement in [
        "UPDATE automation_dispatch_outcomes SET client_user_message_id = 'substituted.client'",
        "UPDATE automation_dispatch_outcomes SET queued_submission_id = 'substituted.queue'",
        "UPDATE automation_dispatch_outcomes SET submitted_at_ms = submitted_at_ms + 1",
    ] {
        let (_temp, layout, store, lease) = leased_store().await?;
        store
            .record_dispatch_uncertain(&lease, /*observed_at_ms*/ 101)
            .await?;
        store
            .reconcile_dispatch(
                lease.task.task_id,
                lease.occurrence,
                &receipt(&lease),
                /*submitted_at_ms*/ 102,
            )
            .await?;
        let path = store.path().to_path_buf();
        store.close().await;
        let pool = SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(
            layout.automation_root().to_path_buf(),
        )?)
        .open_durable_evidence_pool(&path)
        .await?;
        sqlx::query(statement).execute(&pool).await?;
        pool.close().await;
        assert!(matches!(
            AutomationStore::open(&layout).await,
            Err(AutomationError::Corrupt)
        ));
    }
    Ok(())
}


#[tokio::test]
async fn timer_quiescence_is_durable_and_unknown_work_blocks_handoff() -> TestResult {
    let (_temp, layout, store, lease) = leased_store().await?;
    let stopped = store.quiesce_timer().await?;
    assert_eq!(stopped.phase, TimerPhase::Draining);
    assert_eq!(stopped.leased_occurrences, 1);
    assert!(!stopped.can_handoff());
    assert_eq!(store.claim_due(100_000, 2, 100).await?, None);
    assert_eq!(store.handoff_timer().await.err(), Some(AutomationError::Conflict));

    store.record_dispatch_uncertain(&lease, 101).await?;
    store.close().await;
    let reopened = AutomationStore::open(&layout).await?;
    assert_eq!(reopened.timer_status().await?.uncertain_dispatches, 1);
    assert_eq!(reopened.recover_stale_generation(2).await?, 0);
    assert_eq!(reopened.handoff_timer().await.err(), Some(AutomationError::Conflict));

    reopened
        .reconcile_dispatch(lease.task.task_id, lease.occurrence, &receipt(&lease), 102)
        .await?;
    assert!(reopened.timer_status().await?.can_handoff());
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn timer_handoff_fences_predecessor_and_preserves_occurrence_identity() -> TestResult {
    let (_temp, _layout, store, lease) = leased_store().await?;
    store.release_for_retry(&lease).await?;
    store.quiesce_timer().await?;
    let successor = store.handoff_timer().await?;
    assert_eq!(successor.timer_status().await?.writer_epoch, 2);
    assert_eq!(successor.timer_status().await?.phase, TimerPhase::Draining);

    assert_eq!(
        store.claim_due(100, 1, 100).await,
        Err(AutomationError::TimerFenced)
    );
    assert_eq!(
        store
            .create_task(&AutomationTaskDraft::new(
                "019153a4-3088-7e03-a56a-9b1964f75dde",
                "stale create",
                AutomationSchedule::Once,
                100,
                1,
            ))
            .await,
        Err(AutomationError::TimerFenced)
    );

    successor.resume_timer().await?;
    let next = successor
        .claim_due(100, 2, 100)
        .await?
        .ok_or("missing handoff lease")?;
    assert_eq!(next.client_user_message_id, lease.client_user_message_id);
    assert_eq!(next.occurrence, lease.occurrence);
    store.close().await;
    successor.close().await;
    Ok(())
}

#[tokio::test]
async fn repeated_timer_handoffs_keep_writer_epoch_monotone() -> TestResult {
    let (_temp, layout, mut store, lease) = leased_store().await?;
    store.release_for_retry(&lease).await?;
    for expected_epoch in 2..=9 {
        store.quiesce_timer().await?;
        let successor = store.handoff_timer().await?;
        store.close().await;
        successor.close().await;
        store = AutomationStore::open(&layout).await?;
        let status = store.timer_status().await?;
        assert_eq!(status.writer_epoch, expected_epoch);
        assert_eq!(status.phase, TimerPhase::Draining);
        store.resume_timer().await?;
    }
    store.close().await;
    Ok(())
}
