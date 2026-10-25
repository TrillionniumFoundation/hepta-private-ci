//! Real SQLite capacity boundaries; the original event chain and codec are used.
use super::*;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

const EVENT_LIMIT: usize = 4_096;
const LAST_OPERATION: &str = "op:capacity-pending";

fn capacity_journal(
    current_fence: &CompactFence,
    checkpoint: &CompactCheckpoint,
    current: &CompactParentSnapshot,
) -> CompactPersistenceJournal {
    let mut journal = CompactPersistenceJournal::new(current_fence.clone()).expect("journal");
    let digest = checkpoint_digest(checkpoint).expect("digest");
    for index in 0..1_365 {
        let operation = format!("op:capacity-{index}");
        journal
            .append_intent(&operation, checkpoint, current)
            .expect("intent");
        journal
            .commit_checkpoint(&operation, &digest)
            .expect("commit");
        journal
            .record_rehydration(&operation, &digest, checkpoint.checkpoint_revision)
            .expect("rehydration");
    }
    journal
        .append_intent(LAST_OPERATION, checkpoint, current)
        .expect("final intent");
    assert_eq!(journal.entries().len(), EVENT_LIMIT);
    journal
}

async fn install_journal(
    store: &CognitiveStore,
    executor: &crate::LocalCompactExecutor,
    journal: &CompactPersistenceJournal,
) {
    let mut transaction = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("begin");
    for entry in journal.entries() {
        executor
            .insert_event(&mut transaction, entry)
            .await
            .expect("persist original event");
    }
    transaction.commit().await.expect("commit");
}

fn database_bytes(store: &CognitiveStore) -> (Sha256Digest, Option<Sha256Digest>) {
    let database = fs::read(store.path()).expect("database bytes");
    let mut wal = store.path().as_os_str().to_os_string();
    wal.push("-wal");
    let wal = match fs::read(wal) {
        Ok(bytes) => Some(Sha256Digest::for_bytes(&bytes)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
        Err(error) => panic!("WAL read failed: {error}"),
    };
    (Sha256Digest::for_bytes(&database), wal)
}

#[tokio::test]
async fn full_journal_cold_reopen_reads_and_idempotent_replays_remain_legal() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(111);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let current_fence = fence(1, "capacity");
    let checkpoint = checkpoint(current_fence.clone());
    let current = snapshot(current_fence.clone());
    let journal = capacity_journal(&current_fence, &checkpoint, &current);
    let executor = store
        .open_local_compact_executor("journal:capacity", current_fence.clone())
        .await
        .expect("executor");
    install_journal(&store, &executor, &journal).await;
    drop(executor);
    store.pool.close().await;
    drop(store);

    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("cold store");
    let executor = store
        .open_local_compact_executor("journal:capacity", current_fence)
        .await
        .expect("full cold executor");
    let before = database_bytes(&store);
    let digest = checkpoint_digest(&checkpoint).expect("digest");
    assert!(matches!(
        executor
            .append_intent("op:capacity-0", &checkpoint, &current)
            .await
            .expect("replay intent"),
        CompactPersistenceAppend::Replay { .. }
    ));
    assert!(matches!(
        executor
            .commit_checkpoint("op:capacity-0", &digest)
            .await
            .expect("replay commit"),
        CompactPersistenceAppend::Replay { .. }
    ));
    assert_eq!(
        executor
            .rehydrate("op:capacity-0", &checkpoint, checkpoint.checkpoint_revision)
            .await
            .expect("replay rehydration")
            .status,
        crate::RehydrationStatus::Complete
    );
    assert_eq!(
        executor.state(LAST_OPERATION).await.expect("state"),
        Some(CompactPersistenceState::Pending)
    );
    assert_eq!(
        executor.snapshot().await.expect("snapshot"),
        journal.snapshot()
    );
    assert_eq!(database_bytes(&store), before);
}

#[tokio::test]
async fn full_journal_refuses_every_new_event_without_changing_database_or_wal() {
    let temp = TempDir::new().expect("temp");
    let store = CognitiveStore::open(&layout(&temp, &agent_id(112)))
        .await
        .expect("store");
    let current_fence = fence(1, "capacity");
    let checkpoint = checkpoint(current_fence.clone());
    let current = snapshot(current_fence.clone());
    let journal = capacity_journal(&current_fence, &checkpoint, &current);
    let executor = store
        .open_local_compact_executor("journal:capacity", current_fence)
        .await
        .expect("executor");
    install_journal(&store, &executor, &journal).await;
    let before = database_bytes(&store);
    let digest = checkpoint_digest(&checkpoint).expect("digest");
    let results = [
        executor.commit_checkpoint(LAST_OPERATION, &digest).await,
        executor
            .mark_indeterminate(LAST_OPERATION, "capacity")
            .await,
        executor
            .append_intent("op:capacity-new", &checkpoint, &current)
            .await,
    ];
    for result in results {
        assert!(
            matches!(result, Err(LocalCompactExecutorError::Invalid(ref reason)) if reason.contains("4096 event append limit")),
            "{result:?}"
        );
    }
    assert_eq!(
        executor.snapshot().await.expect("still readable"),
        journal.snapshot()
    );
    assert_eq!(database_bytes(&store), before);
}

#[tokio::test]
async fn over_capacity_valid_cold_journal_is_refused_without_truncation_or_rewrite() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(113);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let current_fence = fence(1, "capacity");
    let checkpoint = checkpoint(current_fence.clone());
    let current = snapshot(current_fence.clone());
    let mut journal = capacity_journal(&current_fence, &checkpoint, &current);
    journal
        .commit_checkpoint(
            LAST_OPERATION,
            &checkpoint_digest(&checkpoint).expect("digest"),
        )
        .expect("valid 4097th event");
    assert_eq!(journal.entries().len(), EVENT_LIMIT + 1);
    let executor = store
        .open_local_compact_executor("journal:capacity", current_fence.clone())
        .await
        .expect("executor");
    install_journal(&store, &executor, &journal).await;
    let database_path = store.path().to_path_buf();
    drop(executor);
    store.pool.close().await;
    drop(store);

    let before = Sha256Digest::for_bytes(&fs::read(&database_path).expect("cold database bytes"));
    // The store's own cold verification invokes the same loader before it can
    // issue an executor. A valid over-cap chain must refuse the whole open.
    let result = CognitiveStore::open(&layout(&temp, &owner)).await;
    assert!(
        matches!(result, Err(crate::CognitiveStoreError::Corrupt(ref reason)) if reason.contains("4096 event reopen limit"))
    );
    let home =
        AbsolutePathBuf::from_absolute_path(database_path.parent().expect("database parent"))
            .expect("absolute database root");
    let inspection = SqliteConfig::from_sqlite_home(home)
        .open_read_only_pool(&database_path)
        .await
        .expect("independent read-only database inspection");
    let count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_compact_events WHERE journal_id = ?")
            .bind("journal:capacity")
            .fetch_one(&inspection)
            .await
            .expect("row count");
    assert_eq!(count, 4_097);
    inspection.close().await;
    assert_eq!(
        Sha256Digest::for_bytes(&fs::read(database_path).expect("unchanged database bytes")),
        before
    );
}
