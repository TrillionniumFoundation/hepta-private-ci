use super::*;
use pretty_assertions::assert_eq;
use tokio::sync::Notify;

#[derive(Clone, Copy)]
enum TrustChange {
    Expiry,
    Revocation,
}

async fn assert_live_change_after_actual_entry_await(change: TrustChange) {
    let fixture = SourceFixture::new(WorkerBehavior::ExitZero).await;
    let mut connections = Vec::new();
    for _ in 0..5 {
        connections.push(
            fixture
                .pool
                .acquire()
                .await
                .expect("actual target connection"),
        );
    }
    for mut connection in connections {
        connection.return_to_pool().await;
    }
    assert_eq!((fixture.pool.size(), fixture.pool.num_idle()), (5, 5));
    let blocker = fixture
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("real destination writer lock");
    assert_eq!(fixture.pool.num_idle(), 4);
    let signed = fixture.signed_grant("live-change-during-entry", 9);
    let dispatcher = fixture.dispatcher.clone();
    let writer = fixture.writer.clone();
    let binding = fixture.binding.clone();
    let queued = fixture.queued.clone();
    let task_signed = signed.clone();
    let task = tokio::spawn(async move {
        dispatcher
            .dispatch(&writer, &task_signed, &binding, queued)
            .await
    });
    tokio::time::timeout(Duration::from_secs(2), async {
        // No other task uses this destination pool. Its second held connection
        // proves begin_apply reached the actual SQLite write-lock await, after
        // the original source claimed and passed along its sealed token.
        while fixture.pool.num_idle() != 3 {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .expect("sealed dispatch must reach real entry await");
    let expected = match change {
        TrustChange::Expiry => {
            fixture
                .clock
                .0
                .store(signed.grant.expires_at_unix_ms + 1, Ordering::SeqCst);
            FinalUseError::Expired
        }
        TrustChange::Revocation => {
            fixture
                .target
                .authority
                .update_revocations(FinalUseRevocations {
                    authority_epoch: 1,
                    revision: 2,
                    revoked_grant_ids: BTreeSet::from([signed.grant.grant_id.clone()]),
                })
                .expect("original trusted revocation");
            FinalUseError::Revoked
        }
    };
    blocker.rollback().await.expect("release only fixture lock");
    match tokio::time::timeout(Duration::from_secs(2), task)
        .await
        .expect("dispatch must settle")
        .expect("task")
    {
        Err(ProductionWriterError::FinalUse(actual)) => assert_eq!(actual, expected),
        other => panic!("live authority change must prevent physical entry: {other:?}"),
    }
    let counts: (i64, i64) = sqlx::query_as("SELECT (SELECT COUNT(*) FROM ordinary_cpu_entries), (SELECT COUNT(*) FROM destination_operation_dedupe)").fetch_one(&fixture.pool).await.expect("permanent admission");
    assert_eq!(counts, (1, 1));
    assert!(!fixture.temp.path().join("child-marker").exists());
    assert!(
        fixture
            .target
            .children
            .lock()
            .expect("children")
            .iter()
            .all(Option::is_none)
    );
    let intent = fixture
        .target
        .registration
        .operation(StableId::new("original-source-effect").expect("operation"))
        .expect("intent");
    assert!(matches!(
        fixture
            .target
            .owner
            .enter(&intent)
            .await
            .expect("permanent admission survives"),
        Entry::Retained
    ));
}

#[tokio::test]
async fn expiry_after_actual_sqlite_entry_await_prevents_spawn_and_retains_slot() {
    assert_live_change_after_actual_entry_await(TrustChange::Expiry).await;
}

#[tokio::test]
async fn revocation_after_actual_sqlite_entry_await_prevents_spawn_and_retains_slot() {
    assert_live_change_after_actual_entry_await(TrustChange::Revocation).await;
}

struct LostAcknowledgementTarget {
    inner: Arc<OrdinaryCpuTarget>,
    entered: Notify,
    release: Notify,
}

impl ProductionOutboxTarget for LostAcknowledgementTarget {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        self.inner.dispatch(request)
    }
}

impl FinalUseProductionOutboxTarget for LostAcknowledgementTarget {
    fn destination_id(&self) -> &str {
        DESTINATION
    }
    fn dispatch_verified<'a>(
        &'a self,
        dispatch: ProductionVerifiedDispatch,
    ) -> ProductionVerifiedDispatchFuture<'a> {
        Box::pin(async move {
            let outcome = self.inner.dispatch_verified(dispatch).await?;
            self.entered.notify_one();
            self.release.notified().await;
            Ok(outcome)
        })
    }
}

#[derive(Clone, Copy)]
enum ChildOwnerAfterAcknowledgementLoss {
    Retain,
    Lose,
}

async fn assert_lost_acknowledgement(mode: ChildOwnerAfterAcknowledgementLoss) {
    let fixture = SourceFixture::new(WorkerBehavior::ExitZero).await;
    let lost = Arc::new(LostAcknowledgementTarget {
        inner: fixture.target.clone(),
        entered: Notify::new(),
        release: Notify::new(),
    });
    let dispatcher =
        ProductionFinalUseOutboxDispatcher::attach(fixture.target.authority.clone(), lost.clone());
    let writer = fixture.writer.clone();
    let binding = fixture.binding.clone();
    let queued = fixture.queued.clone();
    let signed = fixture.signed_grant("lost-acknowledgement", 10);
    let task = tokio::spawn(async move {
        dispatcher
            .dispatch(&writer, &signed, &binding, queued)
            .await
    });
    tokio::time::timeout(Duration::from_secs(2), lost.entered.notified())
        .await
        .expect("actual target entry before lost acknowledgement");
    tokio::time::timeout(Duration::from_secs(2), async {
        while !fixture.temp.path().join("child-marker").exists() {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .expect("actual fixed worker effect");
    task.abort();
    assert!(
        task.await
            .expect_err("acknowledgement future cancelled")
            .is_cancelled()
    );
    drop(lost);
    assert_eq!(
        fixture
            .writer
            .status("original-source-effect")
            .await
            .expect("durable source fence"),
        LocalOutcomeState::Indeterminate
    );
    let signed = fixture.signed_grant("no-second-effect", 11);
    assert!(
        fixture
            .dispatcher
            .dispatch(
                &fixture.writer,
                &signed,
                &fixture.binding,
                fixture.queued.clone()
            )
            .await
            .is_err()
    );
    match mode {
        ChildOwnerAfterAcknowledgementLoss::Retain => {
            fixture.wait_for_observed_exit().await;
            assert_eq!(
                fixture
                    .writer
                    .status("original-source-effect")
                    .await
                    .expect("original Child observed"),
                LocalOutcomeState::Committed
            );
            fixture.assert_single_spawn();
        }
        ChildOwnerAfterAcknowledgementLoss::Lose => {
            assert!(
                fixture.target.children.lock().expect("children")[0]
                    .as_ref()
                    .expect("Child")
                    .exit
                    .is_none()
            );
            let original_authority = fixture.target.authority.clone();
            let SourceFixture {
                temp,
                clock: _,
                pool,
                target,
                writer,
                dispatcher,
                queued,
                binding,
            } = fixture;
            drop(dispatcher);
            drop(target);
            let recreated = Arc::new(
                OrdinaryCpuTarget::from_migrated_pool(
                    registered_worker(&temp, writer.owner_agent_id(), WorkerBehavior::ExitZero),
                    original_authority.clone(),
                    pool.clone(),
                )
                .await
                .expect("same trusted pool, no original Child"),
            );
            let dispatcher =
                ProductionFinalUseOutboxDispatcher::attach(original_authority, recreated.clone());
            assert_eq!(
                dispatcher
                    .reconcile(&writer, 1)
                    .await
                    .expect("observer only"),
                1
            );
            assert_eq!(
                writer
                    .status("original-source-effect")
                    .await
                    .expect("source state"),
                LocalOutcomeState::Indeterminate
            );
            assert!(
                dispatcher
                    .dispatch(&writer, &signed, &binding, queued)
                    .await
                    .is_err()
            );
            assert!(
                recreated
                    .children
                    .lock()
                    .expect("children")
                    .iter()
                    .all(Option::is_none)
            );
            assert_eq!(
                std::fs::read_to_string(temp.path().join("child-marker"))
                    .expect("one physical effect")
                    .lines()
                    .collect::<Vec<_>>(),
                vec!["x"]
            );
            let counts: (i64, i64) = sqlx::query_as("SELECT (SELECT COUNT(*) FROM ordinary_cpu_entries), (SELECT COUNT(*) FROM destination_operation_dedupe)").fetch_one(&pool).await.expect("retained permanent slot");
            assert_eq!(counts, (1, 1));
        }
    }
}

#[tokio::test]
async fn lost_acknowledgement_keeps_original_child_observer_and_never_respawns() {
    assert_lost_acknowledgement(ChildOwnerAfterAcknowledgementLoss::Retain).await;
}

#[tokio::test]
async fn lost_acknowledgement_and_lost_child_owner_stay_unknown_without_respawn() {
    assert_lost_acknowledgement(ChildOwnerAfterAcknowledgementLoss::Lose).await;
}
