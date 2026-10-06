//! Deterministic scheduling fixtures and actual concurrent settlement controls.

use super::*;

async fn fixture_times(store: &CognitiveStore, lease_id: &str, times: &[(&str, i64)]) {
    // Test-only scheduling metadata construction. Preserve the exact immutable
    // guard and restore it before exposing this fixture to any dispatcher.
    // No authority, operation semantics, task state or event bytes are changed.
    let mut transaction = store.pool.begin().await.expect("fixture transaction");
    let trigger: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = 'cognitive_operation_ledger_no_update'",
    ).fetch_one(&mut *transaction).await.expect("original immutable guard");
    assert_eq!(
        trigger,
        "CREATE TRIGGER cognitive_operation_ledger_no_update BEFORE UPDATE ON cognitive_operation_ledger BEGIN SELECT RAISE(ABORT, 'operation ledger is immutable'); END"
    );
    sqlx::query("DROP TRIGGER cognitive_operation_ledger_no_update")
        .execute(&mut *transaction)
        .await
        .expect("fixture clock seam");
    for (id, timestamp) in times {
        let changed = sqlx::query(
            "UPDATE cognitive_operation_ledger SET prepared_at_unix_seconds = ? WHERE lease_id = ? AND operation_id = ?",
        ).bind(timestamp).bind(lease_id).bind(id).execute(&mut *transaction).await.expect("fixture timestamp");
        assert_eq!(changed.rows_affected(), 1);
    }
    sqlx::raw_sql("CREATE TRIGGER cognitive_operation_ledger_no_update BEFORE UPDATE ON cognitive_operation_ledger BEGIN SELECT RAISE(ABORT, 'operation ledger is immutable'); END")
        .execute(&mut *transaction)
        .await
        .expect("restore exact immutable guard");
    let restored: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = 'cognitive_operation_ledger_no_update'",
    ).fetch_one(&mut *transaction).await.expect("restored guard");
    assert_eq!(restored, trigger);
    transaction
        .commit()
        .await
        .expect("publish only complete fixture");
}

#[tokio::test]
async fn tied_and_new_keys_wrap_past_terminal_holes_without_crossing_destinations() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let writer = ProductionDurableWriter::open(
        store.clone(),
        production_authority(owner.clone()),
        &AllowVerifier,
        "production:h4:fairness-keys",
        /*generation*/ 1,
    )
    .await
    .expect("writer");
    let target = Arc::new(PausedObserverTarget::default());
    let foreign_target = Arc::new(PausedObserverTarget {
        destination: Some("test.foreign-destination"),
        ..Default::default()
    });
    let issuer = SigningKey::from_bytes(&[91; 32]);
    let authority = final_use(&temp, &issuer);
    let dispatcher = ProductionFinalUseOutboxDispatcher::attach(authority.clone(), target.clone());
    let foreign = ProductionFinalUseOutboxDispatcher::attach(authority, foreign_target.clone());
    prepare_operations(
        &writer,
        &dispatcher,
        &issuer,
        &owner,
        &[
            "operation:a",
            "operation:b",
            "operation:hole",
            "operation:z",
        ],
    )
    .await;
    prepare_operations(&writer, &foreign, &issuer, &owner, &["operation:foreign"]).await;
    fixture_times(
        &store,
        writer.lease_id(),
        &[
            ("operation:a", 100),
            ("operation:b", 100),
            ("operation:hole", 100),
            ("operation:z", 200),
            ("operation:foreign", 0),
        ],
    )
    .await;
    writer
        .reconcile("operation:hole", crate::LocalReconcileOutcome::Rejected)
        .await
        .expect("real terminal hole transition");
    assert_eq!(
        dispatcher
            .reconcile(&writer, /*limit*/ 1)
            .await
            .expect("first key"),
        0
    );
    // Real admission/dispatch followed by fixture-only timestamps places one
    // new key before the saved position and one beyond this cycle's upper key.
    prepare_operations(
        &writer,
        &dispatcher,
        &issuer,
        &owner,
        &["operation:old", "operation:new"],
    )
    .await;
    fixture_times(
        &store,
        writer.lease_id(),
        &[("operation:old", 50), ("operation:new", 300)],
    )
    .await;
    for _ in 0..7 {
        assert_eq!(
            dispatcher
                .reconcile(&writer, /*limit*/ 1)
                .await
                .expect("next key"),
            0
        );
    }
    assert_eq!(
        *target.observed.lock().expect("log"),
        vec![
            "operation:a",
            "operation:b",
            "operation:z",
            "operation:old",
            "operation:a",
            "operation:b",
            "operation:z",
            "operation:new",
        ]
    );
    assert!(
        foreign_target
            .observed
            .lock()
            .expect("foreign log")
            .is_empty()
    );
    assert_eq!(
        foreign
            .reconcile(&writer, /*limit*/ 256)
            .await
            .expect("foreign bounded cycle"),
        0
    );
    assert_eq!(
        *foreign_target.observed.lock().expect("foreign log"),
        vec!["operation:foreign"]
    );
    assert_eq!(
        writer
            .status("operation:hole")
            .await
            .expect("terminal hole"),
        LocalOutcomeState::Rejected
    );
    for id in [
        "operation:a",
        "operation:b",
        "operation:z",
        "operation:old",
        "operation:new",
        "operation:foreign",
    ] {
        assert_eq!(
            writer.status(id).await.expect("preserved pending state"),
            LocalOutcomeState::Indeterminate
        );
    }
    assert_eq!(
        target.dispatches.load(std::sync::atomic::Ordering::SeqCst),
        6
    );
    assert_eq!(
        foreign_target
            .dispatches
            .load(std::sync::atomic::Ordering::SeqCst),
        1
    );
    // Fixture construction did not leave the production immutability guard off.
    assert!(
        sqlx::query("UPDATE cognitive_operation_ledger SET prepared_at_unix_seconds = 999")
            .execute(&store.pool)
            .await
            .is_err()
    );
}

#[derive(Debug, Default)]
struct ConflictingObserversTarget {
    observed: std::sync::atomic::AtomicUsize,
    dispatched: std::sync::atomic::AtomicUsize,
    first_entered: tokio::sync::Notify,
    release_first: tokio::sync::Notify,
}

impl ProductionOutboxTarget for ConflictingObserversTarget {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        self.dispatched
            .fetch_add(/*val*/ 1, std::sync::atomic::Ordering::SeqCst);
        Box::pin(async {
            ProductionTargetOutcome::Indeterminate {
                reason: "synthetic unknown effect".to_string(),
            }
        })
    }
}

impl crate::FinalUseProductionOutboxTarget for ConflictingObserversTarget {
    fn destination_id(&self) -> &str {
        COGNITIVE_SOURCE_DESTINATION_V1
    }

    fn observe_terminal<'a>(
        &'a self,
        _request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            if self
                .observed
                .fetch_add(/*val*/ 1, std::sync::atomic::Ordering::SeqCst)
                == 0
            {
                self.first_entered.notify_one();
                self.release_first.notified().await;
                ProductionTerminalObservation::NotApplied {
                    reason: "late conflicting observer".to_string(),
                }
            } else {
                ProductionTerminalObservation::Applied {
                    receipt: "synthetic terminal owner observation".to_string(),
                }
            }
        })
    }
}

#[tokio::test]
async fn concurrent_cross_wrap_observations_preserve_terminal_cas_and_never_dispatch() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let writer = Arc::new(
        ProductionDurableWriter::open(
            store,
            production_authority(owner.clone()),
            &AllowVerifier,
            "production:h4:fairness-terminal-race",
            /*generation*/ 1,
        )
        .await
        .expect("writer"),
    );
    let target = Arc::new(ConflictingObserversTarget::default());
    let issuer = SigningKey::from_bytes(&[91; 32]);
    let dispatcher =
        ProductionFinalUseOutboxDispatcher::attach(final_use(&temp, &issuer), target.clone());
    prepare_operations(&writer, &dispatcher, &issuer, &owner, &["operation:race"]).await;
    let first_dispatcher = dispatcher.clone();
    let first_writer = Arc::clone(&writer);
    let first = tokio::spawn(async move {
        first_dispatcher.reconcile(&first_writer, /*limit*/ 2).await
    });
    tokio::time::timeout(
        std::time::Duration::from_secs(/*secs*/ 5),
        target.first_entered.notified(),
    )
    .await
    .expect("first observer in flight");
    assert_eq!(
        tokio::time::timeout(
            std::time::Duration::from_secs(/*secs*/ 5),
            dispatcher.reconcile(&writer, /*limit*/ 2)
        )
        .await
        .expect("second observer progressed")
        .expect("second observer terminalized"),
        1
    );
    target.release_first.notify_one();
    let late = tokio::time::timeout(std::time::Duration::from_secs(/*secs*/ 5), first)
        .await
        .expect("late observer exits")
        .expect("task joined");
    assert!(
        late.is_err(),
        "conflicting late settlement must fail closed"
    );
    assert_eq!(
        writer
            .status("operation:race")
            .await
            .expect("terminal status"),
        LocalOutcomeState::Committed
    );
    assert_eq!(target.observed.load(std::sync::atomic::Ordering::SeqCst), 2);
    assert_eq!(
        target.dispatched.load(std::sync::atomic::Ordering::SeqCst),
        1
    );
}
