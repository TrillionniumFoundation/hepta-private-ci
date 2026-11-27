use super::test_support::*;
use super::*;
use pretty_assertions::assert_eq;
use std::sync::Mutex;
use tokio::sync::Notify;

// Deliberately nonconforming external publisher used to attack the owner's
// interlock. This is not a provider implementation or a durability claim.
struct LatePublisher {
    entered: Notify,
    release: Arc<Notify>,
    published: Arc<Mutex<Option<CognitiveRecoveryAnchor>>>,
    worker: Mutex<Option<tokio::task::JoinHandle<()>>>,
}

impl ObjectiveSenderCheckpoint for LatePublisher {
    async fn acknowledge_current(
        &self,
        current: &CognitiveRecoveryAnchor,
        _writer: &ObjectiveSenderWriterFence,
    ) -> Result<CognitiveRecoveryAnchor, ObjectiveSenderCheckpointError> {
        let current = current.clone();
        let release = Arc::clone(&self.release);
        let published = Arc::clone(&self.published);
        *self.worker.lock().unwrap() = Some(tokio::spawn(async move {
            release.notified().await;
            *published.lock().unwrap() = Some(current);
        }));
        self.entered.notify_one();
        std::future::pending().await
    }
}

#[tokio::test]
async fn late_fixture_publication_cannot_follow_a_new_owner_commit_after_cancel() {
    let fixture = Fixture::new().await;
    let checkpoint = Arc::new(LatePublisher {
        entered: Notify::new(),
        release: Arc::new(Notify::new()),
        published: Arc::new(Mutex::new(None)),
        worker: Mutex::new(None),
    });
    let sender = fixture
        .writer
        .objective_sender(checkpoint.clone(), Duration::from_secs(2))
        .unwrap();
    let retained = tokio::spawn(async move { sender.retain_before_send(request()).await });
    checkpoint.entered.notified().await;
    retained.abort();
    assert!(matches!(retained.await, Err(error) if error.is_cancelled()));

    assert!(
        fixture
            .writer
            .admit("late-publish-intervening-write", "test", "{}")
            .await
            .is_err()
    );
    checkpoint.release.notify_one();
    let worker = checkpoint.worker.lock().unwrap().take().unwrap();
    worker.await.unwrap();
    let published = checkpoint.published.lock().unwrap().clone().unwrap();
    assert_eq!(published, fixture.store.recovery_anchor().await.unwrap());
}

#[tokio::test]
async fn cancelled_checkpoint_fences_a_writer_already_waiting_for_sqlite() {
    let fixture = Fixture::new().await;
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Hold;
    let sender = fixture.sender();
    let retain = tokio::spawn(async move { sender.retain_before_send(request()).await });
    fixture.checkpoint.entered.notified().await;
    let captured = fixture
        .checkpoint
        .seen
        .lock()
        .unwrap()
        .last()
        .unwrap()
        .0
        .clone();

    // This connection and authority check predate cancellation. Its original
    // SQLite transaction is waiting behind the checkpoint's BEGIN IMMEDIATE.
    fixture.writer.verify_current_authority().await.unwrap();
    let waiting = fixture.store.pool.begin_with("BEGIN IMMEDIATE");
    tokio::pin!(waiting);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), &mut waiting)
            .await
            .is_err()
    );
    retain.abort();
    assert!(matches!(retain.await, Err(error) if error.is_cancelled()));
    assert!(fixture.writer.checkpoint_fenced());

    let mut transaction = waiting.await.unwrap();
    sqlx::query("CREATE TABLE checkpoint_gate_probe (value INTEGER)")
        .execute(&mut *transaction)
        .await
        .unwrap();
    assert!(transaction.commit().await.is_err());
    let tables: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM sqlite_schema WHERE name = 'checkpoint_gate_probe'",
    )
    .fetch_one(&fixture.store.pool)
    .await
    .unwrap();
    assert_eq!(tables, 0);
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), captured);

    // A separate original writer clone cannot create a new occurrence either.
    let clone = fixture.writer.as_ref().clone();
    assert!(clone.admit("after-cancel", "test", "{}").await.is_err());
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), captured);
}

#[tokio::test]
async fn checkpoint_fence_covers_new_pool_connections_and_implicit_transactions() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Refuse;
    assert!(matches!(
        sender.retain_before_send(request()).await,
        Err(ObjectiveSenderError::AcknowledgementUnknown)
    ));
    let captured = fixture.store.recovery_anchor().await.unwrap();
    let mut connections = Vec::new();
    for _ in 0..5 {
        connections.push(fixture.store.pool.acquire().await.unwrap());
    }
    for mut connection in connections {
        assert!(
            sqlx::query("CREATE TABLE checkpoint_implicit_probe (value INTEGER)")
                .execute(&mut *connection)
                .await
                .is_err()
        );
        connection.close().await.unwrap();
    }
    // All five prior handles are closed. A replacement must install the gate
    // before its first statement, not inherit an unguarded pool default.
    assert!(
        sqlx::query("CREATE TABLE checkpoint_replacement_probe (value INTEGER)")
            .execute(&fixture.store.pool)
            .await
            .is_err()
    );
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), captured);
}

#[tokio::test]
async fn read_reconciliation_never_unfences_the_generation_or_rearms_tickets() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    let ticket = sender.retain_before_send(request()).await.unwrap();
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Refuse;
    assert!(matches!(
        sender.snapshot_acknowledged(&ticket).await,
        Err(ObjectiveSenderError::AcknowledgementUnknown)
    ));
    assert!(fixture.writer.checkpoint_fenced());
    assert!(sender.mark_send_started(&ticket).await.is_err());

    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Accept;
    let recovered = sender.recover_pending(request()).await.unwrap();
    assert!(sender.snapshot_acknowledged(&recovered).await.is_ok());
    assert!(
        sender
            .retained_page(ObjectiveSenderRetainedPosition::Beginning)
            .await
            .is_ok()
    );
    assert!(fixture.writer.checkpoint_fenced());
    assert!(fixture.writer.verify_current_authority().await.is_err());
    assert!(sender.mark_send_started(&ticket).await.is_err());
    assert!(sender.mark_send_started(&recovered).await.is_err());
}

#[tokio::test]
async fn recovered_generation_keeps_its_exclusive_store_fence_after_checkpoint_failure() {
    let temp = tempfile::TempDir::new().unwrap();
    let owner = crate::cognitive_test_support::agent_id(OWNER);
    let layout = crate::cognitive_test_support::layout(&temp, &owner);
    // Explicit test genesis only; recovery below uses the original exact-cut
    // API and retains its exclusive store fence for the active generation.
    let initial = crate::CognitiveStore::open(&layout).await.unwrap();
    let cut = initial.recovery_anchor().await.unwrap();
    initial.close().await;
    let verifier = Arc::new(TestVerifier::new());
    let store = crate::CognitiveStore::open_with_recovery(
        &layout,
        crate::CognitiveRecoveryRequirement::ExactCurrentCut(&cut),
        &authority(&owner, 87),
        verifier.as_ref(),
    )
    .await
    .unwrap();
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store.clone(),
            authority(&owner, 87),
            verifier.clone(),
            LEASE,
            1,
        )
        .await
        .unwrap(),
    );
    let checkpoint = Arc::new(TestCheckpoint::new(verifier));
    *checkpoint.mode.lock().unwrap() = CheckpointMode::Refuse;
    let sender = writer
        .objective_sender(checkpoint, Duration::from_secs(2))
        .unwrap();
    assert!(matches!(
        sender.retain_before_send(request()).await,
        Err(ObjectiveSenderError::AcknowledgementUnknown)
    ));
    assert!(writer.checkpoint_fenced());
    assert!(crate::CognitiveStore::open(&layout).await.is_err());
    let current = store.recovery_anchor().await.unwrap();
    assert!(
        crate::CognitiveStore::open_with_recovery(
            &layout,
            crate::CognitiveRecoveryRequirement::ExactCurrentCut(&current),
            &authority(&owner, 87),
            &TestVerifier::new(),
        )
        .await
        .is_err()
    );
}
