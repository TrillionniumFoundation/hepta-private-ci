#![allow(clippy::expect_used, reason = "native owner fixture assertions")]

use std::sync::Arc;
use std::time::Duration;

use codex_hepta_automation::AutomationAdmission;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFuture;
use codex_hepta_automation::AutomationQueueReceipt;
use codex_hepta_automation::AutomationRuntimePolicyV1;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationScheduler;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTaskId;
use codex_hepta_automation::AutomationTurnQueue;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
    store: AutomationStore,
}

impl Fixture {
    async fn new(count: u64) -> Self {
        let temp = tempfile::tempdir().expect("temporary root");
        let root = temp.path().canonicalize().expect("canonical root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let manifest = AgentManifest::new(
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner"),
            WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register").layout;
        let store = AutomationStore::open(&layout).await.expect("store");
        for index in 0..count {
            let mut draft = AutomationTaskDraft::new(
                "019153a4-3088-7e03-a56a-9b1964f75ddd",
                "polling progress must not mutate business timestamps",
                AutomationSchedule::Once,
                100,
                1,
            );
            draft.task_id =
                AutomationTaskId::parse(&format!("019153a4-3088-7000-a56a-{index:012x}"))
                    .expect("task ID");
            store.create_task(&draft).await.expect("task");
        }
        Self {
            _temp: temp,
            layout,
            store,
        }
    }

    async fn admit(&self) {
        let scheduler = AutomationScheduler::new(
            self.store.clone(),
            Arc::new(Queue),
            1,
            Duration::from_secs(30),
            Duration::from_secs(2),
        )
        .expect("scheduler");
        let policy = AutomationRuntimePolicyV1 {
            admission_budget_per_cycle: 64,
            ..AutomationRuntimePolicyV1::default()
        };
        scheduler
            .tick_batch(&policy, || Ok(100))
            .await
            .expect("admit");
    }
}

struct Queue;

impl AutomationTurnQueue for Queue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            Ok(AutomationQueueReceipt {
                queued_submission_id: format!("accepted:{}", admission.task_id),
                client_user_message_id: admission.client_user_message_id,
            })
        })
    }
}

#[tokio::test]
async fn ninth_pending_occurrence_is_reached_after_reopen_without_business_updates() {
    let fixture = Fixture::new(9).await;
    fixture.admit().await;
    let before = fixture
        .store
        .pending_occurrence_work(16)
        .await
        .expect("pending");
    assert_eq!(before.len(), 9);
    let keys: Vec<_> = before
        .iter()
        .map(|work| (work.occurrence.task_id, work.occurrence.occurrence))
        .collect();
    let first = fixture
        .store
        .reserve_recovery_selection(8)
        .await
        .expect("page");
    assert!(first.uncertain.is_empty());
    assert_eq!(first.pending, keys[..8].to_vec());
    fixture.store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    assert_eq!(
        reopened
            .reserve_recovery_selection(8)
            .await
            .expect("next page")
            .pending,
        keys[8..].to_vec()
    );
    assert_eq!(
        reopened
            .pending_occurrence_work(16)
            .await
            .expect("business records"),
        before
    );
    assert_eq!(
        reopened
            .reserve_recovery_selection(8)
            .await
            .expect("new sweep")
            .pending,
        keys[..8].to_vec()
    );
    reopened.close().await;
}

#[tokio::test]
async fn independent_handles_reserve_disjoint_pages_before_wrap() {
    let fixture = Fixture::new(20).await;
    fixture.admit().await;
    let independent = AutomationStore::open(&fixture.layout)
        .await
        .expect("independent pool");
    let (left, right) = tokio::join!(
        fixture.store.reserve_recovery_selection(8),
        independent.reserve_recovery_selection(8),
    );
    let left = left.expect("left page").pending;
    let right = right.expect("right page").pending;
    assert_eq!(left.len(), 8);
    assert_eq!(right.len(), 8);
    assert!(left.iter().all(|key| !right.contains(key)));
    assert_eq!(
        fixture
            .store
            .pending_occurrence_work(32)
            .await
            .expect("pending")
            .len(),
        20
    );
    independent.close().await;
    fixture.store.close().await;
}

#[tokio::test]
async fn predecessor_timer_cannot_mutate_recovery_progress() {
    let fixture = Fixture::new(2).await;
    fixture.store.quiesce_timer().await.expect("drain");
    let successor = fixture.store.handoff_timer().await.expect("handoff");
    assert_eq!(
        fixture.store.reserve_recovery_selection(8).await,
        Err(AutomationError::TimerFenced)
    );
    assert!(
        successor
            .reserve_recovery_selection(8)
            .await
            .expect("current epoch")
            .pending
            .is_empty()
    );
    successor.close().await;
    fixture.store.close().await;
}
