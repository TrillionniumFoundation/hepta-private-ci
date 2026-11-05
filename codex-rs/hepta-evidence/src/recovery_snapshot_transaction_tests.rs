use std::future::Future;
use std::future::poll_fn;
use std::task::Poll;

use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::HeptaEvidenceStore;

#[tokio::test]
async fn recovery_snapshot_does_not_mix_atomic_commits_between_pool_reads() {
    let temp = TempDir::new().expect("temporary evidence directory");
    let sqlite = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute evidence path"),
    );
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open original evidence schema through the SQLite shim");
    let before = store.recovery_snapshot().await.expect("snapshot before write");

    // Hold every shim-created connection. SQLx's FIFO acquire queue then lets
    // the reader start before the writer, without a sleep or a product hook.
    let mut held = Vec::new();
    for _ in 0..store.pool.options().get_max_connections() {
        held.push(store.pool.acquire().await.expect("hold existing connection"));
    }
    let snapshot = store.recovery_snapshot();
    let mut snapshot = std::pin::pin!(snapshot);
    poll_fn(|context| {
        assert!(snapshot.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;

    let write = async {
        let mut transaction = store.pool.begin().await.expect("queued writer transaction");
        // Change two checkpoint components in one real SQLite commit. The
        // migration description is fixture data only; no schema migration or
        // production pool/connection configuration is changed by this test.
        let changed = sqlx::query(
            "UPDATE _sqlx_migrations
             SET description = description || '-snapshot-concurrent-write'
             WHERE version = (SELECT MIN(version) FROM _sqlx_migrations)",
        )
        .execute(&mut *transaction)
        .await
        .expect("change fixture migration frontier");
        assert_eq!(changed.rows_affected(), 1);
        sqlx::query(
            "INSERT INTO authbus_replay_sequences
             (issuer_id, key_epoch, subject_id, scope_digest, sequence, envelope_digest)
             VALUES (?, ?, ?, ?, ?, ?)",
        )
        .bind("snapshot-writer")
        .bind(1_u64.to_be_bytes().to_vec())
        .bind("snapshot-subject")
        .bind(vec![1_u8; 32])
        .bind(1_u64.to_be_bytes().to_vec())
        .bind(vec![2_u8; 32])
        .execute(&mut *transaction)
        .await
        .expect("change fixture replay frontier in the same transaction");
        transaction.commit().await.expect("commit both frontier changes");
    };
    let mut write = std::pin::pin!(write);
    poll_fn(|context| {
        assert!(write.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;

    // Only one connection is released. An independent read releases it to the
    // queued writer after its first SELECT; a transaction retains it for all
    // components, so the writer cannot create a mixed checkpoint.
    drop(held.pop().expect("one held connection"));
    let (during, ()) = tokio::join!(snapshot, write);
    drop(held);
    let during = during.expect("snapshot overlapping the writer");
    let after = store.recovery_snapshot().await.expect("snapshot after write");
    assert_ne!(before, after, "the fixture must actually commit its changes");
    assert_eq!(during, before, "every component must belong to one SQLite snapshot");
}
