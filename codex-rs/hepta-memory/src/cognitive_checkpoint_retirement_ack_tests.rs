//! Lost target replies and failed original-source ACK COMMITs stay unknown.
use super::*;
use crate::ProductionRetirementAck;
use std::sync::atomic::AtomicBool;

struct LostAck {
    observer: Arc<Observer>,
    lose_reply: AtomicBool,
}
impl ProductionOutboxTarget for LostAck {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        self.observer.dispatch(request)
    }
}
impl FinalUseProductionOutboxTarget for LostAck {
    fn destination_id(&self) -> &str {
        self.observer.destination_id()
    }
    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        self.observer.observe_terminal(request)
    }
    fn retire_notes_receipt(
        &self,
        permit: &NotesRetirementPermit,
    ) -> Result<ProductionRetirementAck, String> {
        let acknowledgement = self.observer.retire_notes_receipt(permit)?;
        if self.lose_reply.swap(false, Ordering::SeqCst) {
            return Err("explicit fixture lost the target ACK after retirement".into());
        }
        Ok(acknowledgement)
    }
}

#[tokio::test]
async fn lost_target_ack_remains_pending_until_exact_metadata_reack() {
    let fixture = ManagedFixture::new().await;
    let (operation, observer) = prepared_notes(&fixture.writer, fixture.peer.clone()).await;
    let target = LostAck {
        observer,
        lose_reply: AtomicBool::new(true),
    };
    assert_eq!(
        fixture
            .writer
            .reconcile_target_batch(&target, /*limit*/ 1)
            .await
            .unwrap(),
        1
    );
    assert_eq!(target.observer.retirements.load(Ordering::SeqCst), 1);
    assert!(
        !fixture
            .writer
            .retained_notes_retirement_ack(&operation)
            .await
            .unwrap()
    );
    assert!(
        fixture
            .writer
            .retained_notes_retirement_ack("not-an-original-operation")
            .await
            .is_err()
    );
    assert!(
        fixture
            .writer
            .retained_calculator_retirement_ack(&operation)
            .await
            .is_err()
    );
    let pending: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_local_events WHERE event_kind = 'retirement_acknowledged'",
    )
    .fetch_one(fixture.store.observation_pool())
    .await
    .unwrap();
    assert_eq!(pending, 0);

    fixture
        .writer
        .retire_notes_receipt(&target, &operation)
        .await
        .unwrap();
    assert!(
        fixture
            .writer
            .retained_notes_retirement_ack(&operation)
            .await
            .unwrap()
    );
    assert_eq!(
        fixture.writer.status(&operation).await.unwrap(),
        LocalOutcomeState::Committed
    );
    assert_eq!(
        fixture
            .writer
            .retained_notes_terminal_receipt(&operation)
            .await
            .unwrap(),
        Some(target.observer.receipt.clone())
    );
    let protected = fixture.peer.receipt.lock().unwrap().clone();
    let cut = fixture.store.recovery_anchor().await.unwrap();
    fixture
        .writer
        .retire_notes_receipt(&target, &operation)
        .await
        .unwrap();
    assert!(
        fixture
            .writer
            .retained_notes_retirement_ack(&operation)
            .await
            .unwrap()
    );
    assert_eq!(*fixture.peer.receipt.lock().unwrap(), protected);
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), cut);
    let recorded: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_local_events WHERE event_kind = 'retirement_acknowledged'",
    )
    .fetch_one(fixture.store.observation_pool())
    .await
    .unwrap();
    assert_eq!(
        (recorded, target.observer.retirements.load(Ordering::SeqCst)),
        (1, 3)
    );
}

#[tokio::test]
async fn failed_source_ack_commit_cannot_retire_an_older_target_for_recovery() {
    let fixture = ManagedFixture::new().await;
    let (operation, target) = prepared_notes(&fixture.writer, fixture.peer.clone()).await;
    sqlx::query("CREATE TRIGGER retirement_ack_fixture_fail BEFORE INSERT ON cognitive_local_events WHEN NEW.event_kind = 'retirement_acknowledged' BEGIN SELECT RAISE(ABORT, 'fixture source ACK COMMIT refused'); END")
        .execute(&fixture.store.pool).await.unwrap();
    assert_eq!(
        fixture
            .writer
            .reconcile_target_batch(target.as_ref(), /*limit*/ 1)
            .await
            .unwrap(),
        1
    );
    assert_eq!(target.retirements.load(Ordering::SeqCst), 1);
    let absent: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_local_events WHERE event_kind = 'retirement_acknowledged'",
    )
    .fetch_one(fixture.store.observation_pool())
    .await
    .unwrap();
    assert_eq!(absent, 0);
    assert!(
        fixture
            .writer
            .retained_notes_retirement_ack(&operation)
            .await
            .is_err(),
        "the source is Dirty after a failed guarded ACK write, so even a Pending observation lacks protected Current"
    );

    sqlx::query("DROP TRIGGER retirement_ack_fixture_fail")
        .execute(&fixture.store.pool)
        .await
        .unwrap();
    fixture.writer.acknowledge_current().await.unwrap();
    assert!(
        !fixture
            .writer
            .retained_notes_retirement_ack(&operation)
            .await
            .unwrap()
    );
    fixture
        .writer
        .retire_notes_receipt(target.as_ref(), &operation)
        .await
        .unwrap();
    assert!(
        fixture
            .writer
            .retained_notes_retirement_ack(&operation)
            .await
            .unwrap()
    );
    let recorded: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_local_events WHERE event_kind = 'retirement_acknowledged'",
    )
    .fetch_one(fixture.store.observation_pool())
    .await
    .unwrap();
    assert_eq!(
        (recorded, target.retirements.load(Ordering::SeqCst)),
        (1, 2)
    );
}
