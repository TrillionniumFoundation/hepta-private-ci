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
async fn prepared_notes(fixture: &ManagedFixture) -> (String, Arc<Observer>) {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../tests/fixtures/notes-target-v1.json")).unwrap();
    let payload = golden["request_utf8"].as_str().unwrap().to_string();
    let request: serde_json::Value = serde_json::from_str(&payload).unwrap();
    let identity: NotesTargetIdentity = serde_json::from_value(request["target"].clone()).unwrap();
    let intent = notes_operation_intent(
        &identity,
        &payload,
        StableId::new(fixture.writer.owner_agent_id().as_str()).unwrap(),
        Generation::new(1).unwrap(),
    )
    .unwrap();
    let queued = fixture
        .writer
        .prepare_operation(intent, crate::NOTES_REPLACE_TOPIC_V1, payload)
        .await
        .unwrap();
    fixture
        .writer
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
            peer: fixture.peer.clone(),
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
    let (operation, target) = prepared_notes(&fixture).await;
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
