//! Owner-store reopen regressions; not a live-effect or kill-9 qualification.
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationLease;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTaskState;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

type TestResult = Result<(), Box<dyn std::error::Error>>;

async fn uncertain_store() -> Result<
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
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let record = registry.register(AgentManifest::new(
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        WorkspaceBinding::new(&workspace, &fleet)?,
        ResourceBudget::local_default(),
    )?)?;
    let store = AutomationStore::open(&record.layout).await?;
    store
        .create_task(&AutomationTaskDraft::new(
            "019153a4-3088-7e03-a56a-9b1964f75ddd",
            "convergence recovery",
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
        .ok_or("missing lease")?;
    let occurrence = store.materialize_occurrence(&lease, 101).await?;
    store
        .prepare_occurrence_taskflow(&occurrence, &lease, 101, 60_000)
        .await?;
    store.record_dispatch_uncertain(&lease, 101).await?;
    Ok((temp, record.layout, store, lease))
}

#[tokio::test]
async fn retirement_preserves_unknown_until_same_identity_absence_is_reconciled() -> TestResult {
    for retirement in [
        AutomationTaskState::Disabled,
        AutomationTaskState::Cancelled,
    ] {
        let (_temp, layout, store, lease) = uncertain_store().await?;
        let task_id = lease.task.task_id;
        match retirement {
            AutomationTaskState::Disabled => {
                store
                    .set_enabled(
                        task_id, /*enabled*/ false, /*resume_at_ms*/ None, 102,
                    )
                    .await?;
            }
            AutomationTaskState::Cancelled => {
                store.cancel_task(task_id, 102).await?;
            }
            AutomationTaskState::Enabled | AutomationTaskState::Completed => unreachable!(),
        }
        store.close().await;
        let recovered = AutomationStore::open(&layout).await?;
        assert_eq!(recovered.uncertain_dispatches(/*limit*/ 10).await?.len(), 1);
        assert_eq!(recovered.recover_stale_generation(2, 100_000).await?, 0);
        assert_eq!(
            recovered.release_for_retry(&lease).await,
            Err(AutomationError::Conflict)
        );
        assert_eq!(recovered.claim_due(100_000, 2, 100).await?, None);
        let proof = Sha256Digest::for_bytes(b"independently-observed-queue-absence");
        assert_eq!(
            recovered
                .reconcile_uncertain_occurrence_absent(
                    task_id,
                    lease.occurrence,
                    "different-client",
                    &proof,
                    100_001,
                )
                .await,
            Err(AutomationError::Conflict)
        );
        assert_eq!(recovered.uncertain_dispatches(/*limit*/ 10).await?.len(), 1);
        recovered
            .reconcile_uncertain_occurrence_absent(
                task_id,
                lease.occurrence,
                &lease.client_user_message_id,
                &proof,
                100_002,
            )
            .await?;
        let resolved = recovered
            .automation_occurrence(task_id, lease.occurrence)
            .await?;
        let retired = recovered
            .task(task_id)
            .await?
            .ok_or("missing retired task")?;
        assert_eq!(retired.state, retirement);
        recovered.close().await;
        let reopened = AutomationStore::open(&layout).await?;
        reopened
            .reconcile_uncertain_occurrence_absent(
                task_id,
                lease.occurrence,
                &lease.client_user_message_id,
                &proof,
                200_000,
            )
            .await?;
        let changed_proof = Sha256Digest::for_bytes(b"different-absence-observation");
        assert_eq!(
            reopened
                .reconcile_uncertain_occurrence_absent(
                    task_id,
                    lease.occurrence,
                    &lease.client_user_message_id,
                    &changed_proof,
                    200_001,
                )
                .await,
            Err(AutomationError::Conflict)
        );
        assert_eq!(
            reopened
                .automation_occurrence(task_id, lease.occurrence)
                .await?,
            resolved
        );
        assert_eq!(reopened.task(task_id).await?, Some(retired));
        assert!(
            reopened
                .uncertain_dispatches(/*limit*/ 10)
                .await?
                .is_empty()
        );
        assert_eq!(reopened.claim_due(200_002, 3, 100).await?, None);
        reopened.close().await;
    }
    Ok(())
}

#[tokio::test]
async fn proven_absence_reclaim_preserves_operation_identity_across_generation() -> TestResult {
    let (_temp, layout, store, lease) = uncertain_store().await?;
    store.close().await;
    let recovered = AutomationStore::open(&layout).await?;
    let proof = Sha256Digest::for_bytes(b"provider-stable-client-lookup-is-absent");
    recovered
        .reconcile_uncertain_occurrence_absent(
            lease.task.task_id,
            lease.occurrence,
            &lease.client_user_message_id,
            &proof,
            100_000,
        )
        .await?;
    recovered.close().await;
    let reopened = AutomationStore::open(&layout).await?;
    let successor = reopened
        .claim_due(
            100_001, /*generation*/ 2, /*lease_duration_ms*/ 60_000,
        )
        .await?
        .ok_or("missing proven-absent reclaim")?;
    assert_eq!(successor.occurrence, lease.occurrence);
    assert_eq!(
        successor.client_user_message_id,
        lease.client_user_message_id
    );
    assert_eq!(successor.schedule_revision, lease.schedule_revision);
    assert_ne!(successor.lease_generation, lease.lease_generation);
    let occurrence = reopened.materialize_occurrence(&successor, 100_002).await?;
    reopened
        .prepare_occurrence_taskflow(&occurrence, &successor, 100_002, 60_000)
        .await?;
    reopened
        .record_dispatch_uncertain(&successor, 100_003)
        .await?;
    assert_eq!(
        reopened.release_for_retry(&successor).await,
        Err(AutomationError::Conflict)
    );
    reopened.close().await;
    let final_reopen = AutomationStore::open(&layout).await?;
    assert_eq!(
        final_reopen.uncertain_dispatches(/*limit*/ 10).await?.len(),
        1
    );
    assert_eq!(final_reopen.claim_due(300_000, 3, 100).await?, None);
    final_reopen.close().await;
    Ok(())
}
