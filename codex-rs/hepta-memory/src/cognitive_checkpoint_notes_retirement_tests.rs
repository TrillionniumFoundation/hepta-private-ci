//! Original Notes settlement with the explicit protected-protocol fixture.
//! This peer does not qualify a production Root service or filesystem fsync.

use super::*;
use crate::FinalUseProductionOutboxTarget;
use crate::LocalOutcomeState;
use crate::NotesRetirementPermit;
use crate::NotesTargetIdentity;
use crate::ProductionDispatchFuture;
use crate::ProductionDispatchRequest;
use crate::ProductionOutboxTarget;
use crate::ProductionTerminalObservation;
use crate::ProductionTerminalObservationFuture;
use crate::notes_operation_intent;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicUsize;

struct Observer {
    destination: String,
    receipt: String,
    peer: Arc<ProtocolPeer>,
    retirements: AtomicUsize,
    retired_head: Mutex<Option<CognitiveCheckpointReceipt>>,
}
impl ProductionOutboxTarget for Observer {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        panic!("receipt recovery must never dispatch an effect")
    }
}
impl FinalUseProductionOutboxTarget for Observer {
    fn destination_id(&self) -> &str {
        &self.destination
    }
    fn observe_terminal<'a>(
        &'a self,
        _request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async {
            ProductionTerminalObservation::Applied {
                receipt: self.receipt.clone(),
            }
        })
    }
    fn retire_notes_receipt(&self, permit: &NotesRetirementPermit) -> Result<(), String> {
        assert_eq!(permit.receipt(), self.receipt);
        assert_eq!(permit.request().operation_destination_id, self.destination);
        *self.retired_head.lock().unwrap() = Some(self.peer.receipt.lock().unwrap().clone());
        self.retirements.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}
async fn prepared_notes(
    writer: &ProductionDurableWriter,
    peer: Arc<ProtocolPeer>,
) -> (String, Arc<Observer>) {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../tests/fixtures/notes-target-v1.json")).unwrap();
    let payload = golden["request_utf8"].as_str().unwrap().to_string();
    let request: serde_json::Value = serde_json::from_str(&payload).unwrap();
    let identity: NotesTargetIdentity = serde_json::from_value(request["target"].clone()).unwrap();
    let intent = notes_operation_intent(
        &identity,
        &payload,
        StableId::new(writer.owner_agent_id().as_str()).unwrap(),
        Generation::new(1).unwrap(),
    )
    .unwrap();
    let queued = writer
        .prepare_operation(intent, crate::NOTES_REPLACE_TOPIC_V1, payload)
        .await
        .unwrap();
    writer
        .mark_indeterminate(&queued.occurrence_key, "fixture app applied; reply lost")
        .await
        .unwrap();
    (
        queued.occurrence_key,
        Arc::new(Observer {
            destination: identity.destination_id(),
            receipt: golden["application_response_utf8"]
                .as_str()
                .unwrap()
                .to_string(),
            peer,
            retirements: AtomicUsize::new(0),
            retired_head: Mutex::new(None),
        }),
    )
}
#[tokio::test]
async fn notes_retirement_waits_for_bound_whole_owner_publication() {
    let fixture = ManagedFixture::new().await;
    fixture.sender().acknowledge_owner_cut().await.unwrap();
    let before = fixture.peer.receipt.lock().unwrap().clone();
    let (operation, target) = prepared_notes(&fixture.writer, fixture.peer.clone()).await;
    fixture
        .peer
        .hold_current_reply
        .store(true, Ordering::SeqCst);
    assert_eq!(
        fixture
            .writer
            .reconcile_target_batch(target.as_ref(), /*limit*/ 1)
            .await
            .unwrap(),
        1
    );
    assert_eq!(
        fixture.writer.status(&operation).await.unwrap(),
        LocalOutcomeState::Committed
    );
    assert_eq!(
        target.retirements.load(Ordering::SeqCst),
        0,
        "a local terminal COMMIT must not discard the application's only receipt before independent whole-owner acknowledgement"
    );
    assert!(fixture.store.commit_gate.is_fenced());
    assert_ne!(
        fixture.store.recovery_anchor().await.unwrap(),
        before.head.last_current
    );
}

#[tokio::test]
async fn notes_retirement_acknowledges_exact_terminal_cut_without_an_objective() {
    let fixture = ManagedFixture::new().await;
    let (operation, target) = prepared_notes(&fixture.writer, fixture.peer.clone()).await;
    fixture
        .writer
        .reconcile_target_batch(target.as_ref(), /*limit*/ 1)
        .await
        .unwrap();
    let cut = fixture.store.recovery_anchor().await.unwrap();
    let acknowledged = target.retired_head.lock().unwrap().clone().unwrap();
    assert_eq!(acknowledged.head.phase, CognitiveCheckpointPhase::Current);
    assert_eq!(acknowledged.head.last_current, cut);
    assert_eq!(target.retirements.load(Ordering::SeqCst), 1);
    let objective_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_objective_sender_requests")
            .fetch_one(fixture.store.observation_pool())
            .await
            .unwrap();
    assert_eq!(objective_count, 0);
    fixture
        .writer
        .retire_notes_receipt(target.as_ref(), &operation)
        .await
        .unwrap();
    assert_eq!(
        fixture
            .writer
            .reconcile_target_batch(target.as_ref(), /*limit*/ 1)
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        *fixture.peer.receipt.lock().unwrap(),
        acknowledged,
        "metadata retries and an empty reconciliation poll must not dirty Current or mutate its token"
    );
    assert_eq!(target.retirements.load(Ordering::SeqCst), 3);
}

#[tokio::test]
async fn notes_retirement_cancelled_publication_retains_receipt_and_never_reopens_writer() {
    let fixture = ManagedFixture::new().await;
    let (operation, target) = prepared_notes(&fixture.writer, fixture.peer.clone()).await;
    fixture
        .peer
        .hold_current_reply
        .store(true, Ordering::SeqCst);
    let writer = fixture.writer.clone();
    let destination = target.clone();
    let task = tokio::spawn(async move {
        writer
            .reconcile_target_batch(destination.as_ref(), /*limit*/ 1)
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), fixture.peer.published.notified())
        .await
        .unwrap();
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    assert_eq!(target.retirements.load(Ordering::SeqCst), 0);
    assert!(fixture.store.commit_gate.is_fenced());
    assert_eq!(
        fixture.writer.status(&operation).await.unwrap(),
        LocalOutcomeState::Committed
    );
    // Only an independent exact Current readback can retire the existing
    // receipt after a lost ACK. This grants no new effect or write permission.
    fixture
        .peer
        .hold_current_reply
        .store(false, Ordering::SeqCst);
    fixture.peer.wrong_owner_reply.store(true, Ordering::SeqCst);
    assert!(
        fixture
            .writer
            .retire_notes_receipt(target.as_ref(), &operation)
            .await
            .is_err()
    );
    assert_eq!(target.retirements.load(Ordering::SeqCst), 0);
    fixture
        .peer
        .wrong_owner_reply
        .store(false, Ordering::SeqCst);
    let before = fixture.peer.receipt.lock().unwrap().clone();
    fixture
        .writer
        .retire_notes_receipt(target.as_ref(), &operation)
        .await
        .unwrap();
    assert_eq!(target.retirements.load(Ordering::SeqCst), 1);
    assert_eq!(*fixture.peer.receipt.lock().unwrap(), before);
    assert!(fixture.store.commit_gate.is_fenced());
    assert!(fixture.writer.verify_current_authority().await.is_err());
}

#[tokio::test]
async fn notes_retirement_managed_owner_without_bound_capability_cannot_fall_back_to_local_commit()
{
    let managed = ManagedFixture::new().await;
    let fixture = Fixture::new().await;
    let (operation, target) = prepared_notes(&fixture.writer, managed.peer.clone()).await;
    // Persist a real original terminal receipt in the unmanaged fixture before
    // simulating a managed owner with a missing private publication binding.
    let request = fixture
        .writer
        .reconciliation_request(&operation, &target.destination)
        .await
        .unwrap();
    fixture
        .writer
        .settle_notes_terminal(
            &request,
            &target.receipt,
            crate::LocalReconcileOutcome::Committed,
        )
        .await
        .unwrap();
    fixture.store.commit_gate.manage_commits();
    assert!(
        fixture
            .writer
            .retire_notes_receipt(target.as_ref(), &operation)
            .await
            .is_err()
    );
    assert_eq!(target.retirements.load(Ordering::SeqCst), 0);
    assert!(fixture.store.commit_gate.is_fenced());
}

#[tokio::test]
async fn notes_retirement_revoked_after_current_ack_keeps_application_receipt() {
    let fixture = ManagedFixture::new().await;
    let (_operation, target) = prepared_notes(&fixture.writer, fixture.peer.clone()).await;
    fixture
        .peer
        .revoke_after_publication
        .store(true, Ordering::SeqCst);
    assert_eq!(
        fixture
            .writer
            .reconcile_target_batch(target.as_ref(), /*limit*/ 1)
            .await
            .unwrap(),
        1
    );
    assert_eq!(target.retirements.load(Ordering::SeqCst), 0);
    assert!(fixture.store.commit_gate.is_fenced());
    assert_eq!(
        fixture.peer.receipt.lock().unwrap().head.phase,
        CognitiveCheckpointPhase::Current
    );
}

struct BlockingRetirement {
    observer: Arc<Observer>,
    entered: Notify,
    release: Mutex<std::sync::mpsc::Receiver<()>>,
}
impl ProductionOutboxTarget for BlockingRetirement {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        self.observer.dispatch(request)
    }
}
impl FinalUseProductionOutboxTarget for BlockingRetirement {
    fn destination_id(&self) -> &str {
        self.observer.destination_id()
    }
    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        self.observer.observe_terminal(request)
    }
    fn retire_notes_receipt(&self, permit: &NotesRetirementPermit) -> Result<(), String> {
        self.entered.notify_one();
        self.release
            .lock()
            .unwrap()
            .recv_timeout(Duration::from_secs(5))
            .unwrap();
        self.observer.retire_notes_receipt(permit)
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn notes_retirement_holds_original_sqlite_lock_through_synchronous_metadata_ack() {
    let fixture = ManagedFixture::new().await;
    let (_operation, observer) = prepared_notes(&fixture.writer, fixture.peer.clone()).await;
    let (release, receive) = std::sync::mpsc::channel();
    let target = Arc::new(BlockingRetirement {
        observer,
        entered: Notify::new(),
        release: Mutex::new(receive),
    });
    let writer = fixture.writer.clone();
    let destination = target.clone();
    let mut retirement = tokio::spawn(async move {
        writer
            .reconcile_target_batch(destination.as_ref(), /*limit*/ 1)
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), target.entered.notified())
        .await
        .unwrap();
    let acknowledged_cut = fixture
        .peer
        .receipt
        .lock()
        .unwrap()
        .head
        .last_current
        .clone();
    let writer = fixture.writer.clone();
    let mut mutation =
        tokio::spawn(async move { writer.admit("retirement-competitor", "fixture", "{}").await });
    assert!(
        tokio::time::timeout(Duration::from_millis(100), &mut mutation)
            .await
            .is_err(),
        "a concurrent original writer must not commit while metadata retirement holds its SQLite barrier"
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(20), &mut retirement)
            .await
            .is_err()
    );
    release.send(()).unwrap();
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(5), retirement)
            .await
            .unwrap()
            .unwrap()
            .unwrap(),
        1
    );
    tokio::time::timeout(Duration::from_secs(5), mutation)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(target.observer.retirements.load(Ordering::SeqCst), 1);
    assert_ne!(
        fixture.store.recovery_anchor().await.unwrap(),
        acknowledged_cut
    );
}
