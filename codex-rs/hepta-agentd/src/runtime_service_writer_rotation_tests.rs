//! Same-schema real SQLite writer rotation through the public versioned host.
//! No provider effect, cross-schema migration, production activation or future
//! efficacy claim follows from this bounded local integration test.

use std::time::Duration;

use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationOperationReceipt;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::TimerPhase;
use codex_hepta_automation::automation_task_operation_intent;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_operations::DestinationApplyDisposition;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Generation;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::RuntimeTasks;

const NAME: &str = "automation.rotation-fixture";

struct Request {
    draft: AutomationTaskDraft,
    reply: oneshot::Sender<Result<AutomationOperationReceipt, AutomationError>>,
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap()
}

fn draft(prompt: &str) -> AutomationTaskDraft {
    AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        prompt,
        AutomationSchedule::Once,
        20_000,
        10_000,
    )
}

async fn apply(store: &AutomationStore, request: Request) {
    let intent =
        automation_task_operation_intent(store.owner_agent_id(), &request.draft, generation(1))
            .unwrap();
    let result = store
        .create_task_from_operation(&intent, &request.draft)
        .await;
    let _ = request.reply.send(result);
}

fn attach(host: &mut RuntimeTasks, store: AutomationStore, epoch: u64) -> mpsc::Sender<Request> {
    let (send, mut receive) = mpsc::channel::<Request>(4);
    host.spawn_optional_service_generation(
        NAME,
        generation(epoch),
        (epoch > 1).then(|| generation(epoch - 1)),
        move |stop| async move {
            loop {
                tokio::select! {
                    biased;
                    () = stop.cancelled() => {
                        receive.close();
                        while let Some(request) = receive.recv().await {
                            apply(&store, request).await;
                        }
                        return Ok(());
                    }
                    request = receive.recv() => {
                        let Some(request) = request else { return Ok(()); };
                        apply(&store, request).await;
                    }
                }
            }
        },
        || Ok(()),
        || Ok(()), // Only the drained test-local channel route is acknowledged.
    )
    .unwrap();
    send
}

async fn ask(
    send: &mpsc::Sender<Request>,
    draft: AutomationTaskDraft,
) -> AutomationOperationReceipt {
    let (reply, response) = oneshot::channel();
    send.send(Request { draft, reply }).await.unwrap();
    timeout(Duration::from_secs(10), response)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
}

#[tokio::test]
async fn sqlite_writer_rotates_256_times_without_consuming_new_service_identities() {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).unwrap();
    let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    let manifest = AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(workspace, &fleet).unwrap(),
        ResourceBudget::local_default(),
    )
    .unwrap();
    registry.register(manifest).unwrap();
    let layout = fleet.layout().agent(&agent);
    let mut store = AutomationStore::open(&layout).await.unwrap();
    let first_writer = store.clone();
    let original = draft("one durable effect across repeated owner handoff");
    let stop = CancellationToken::new();
    let mut host = RuntimeTasks::new(stop.clone(), Duration::from_secs(2)).unwrap();
    for epoch in 1..=256 {
        assert_eq!(store.timer_status().await.unwrap().writer_epoch, epoch);
        let client = attach(&mut host, store.clone(), epoch);
        let receipt = ask(&client, original.clone()).await;
        if epoch > 1 {
            assert_eq!(
                receipt.disposition,
                DestinationApplyDisposition::AlreadyApplied
            );
            assert!(
                host.retire_optional_generation(NAME, generation(epoch - 1))
                    .await
                    .is_err()
            );
        }
        assert_eq!(store.list_tasks(10).await.unwrap().len(), 1);
        assert!(store.quiesce_timer().await.unwrap().can_handoff());
        host.retire_optional_generation(NAME, generation(epoch))
            .await
            .unwrap();
        assert!(client.is_closed());
        assert_eq!(host.active_count(), 0);
        assert_eq!(host.remaining_admission_slots(), 127);
        assert_eq!(host.service_generations.len(), 1);
        assert_eq!(host.retired_names.len(), 1);
        assert!(!stop.is_cancelled());
        if epoch < 256 {
            let next = store.handoff_timer().await.unwrap();
            assert_eq!(
                next.timer_status().await.unwrap().phase,
                TimerPhase::Draining
            );
            next.resume_timer().await.unwrap();
            let new_effect = draft("stale owner must not create a new effect");
            let intent = automation_task_operation_intent(
                store.owner_agent_id(),
                &new_effect,
                generation(1),
            )
            .unwrap();
            assert_eq!(
                store.create_task_from_operation(&intent, &new_effect).await,
                Err(AutomationError::TimerFenced)
            );
            store = next;
        }
    }
    assert_eq!(
        store.retire_timer().await.unwrap().phase,
        TimerPhase::Retired
    );
    host.shutdown().await;
    store.close().await;
    let reopened = AutomationStore::open(&layout).await.unwrap();
    assert_eq!(
        reopened.timer_status().await.unwrap().phase,
        TimerPhase::Retired
    );
    assert_eq!(
        reopened.resume_timer().await,
        Err(AutomationError::TimerFenced)
    );
    let intent =
        automation_task_operation_intent(reopened.owner_agent_id(), &original, generation(1))
            .unwrap();
    let retained = reopened
        .create_task_from_operation(&intent, &original)
        .await
        .unwrap();
    assert_eq!(
        retained.disposition,
        DestinationApplyDisposition::AlreadyApplied
    );
    assert_eq!(reopened.list_tasks(10).await.unwrap().len(), 1);
    drop(first_writer);
    reopened.close().await;
}
