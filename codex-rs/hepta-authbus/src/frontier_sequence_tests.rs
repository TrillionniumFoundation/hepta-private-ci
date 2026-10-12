use super::*;
use crate::AuthBusAuthorityStore;
use crate::AuthorityCheckpoint;
use crate::TrustedTimeSample;
use codex_hepta_types::Digest32;
use tempfile::TempDir;

struct Fixture {
    _root: TempDir,
    path: std::path::PathBuf,
    store: AuthBusAuthorityStore,
    checkpoint: AuthorityCheckpoint,
    applied: i64,
}

fn time(revision: u64) -> TrustedTimeSample {
    TrustedTimeSample::new(
        1_000 + revision * 100,
        revision,
        Digest32::of_bytes(&revision.to_be_bytes()),
    )
    .unwrap()
}

impl Fixture {
    async fn new() -> Self {
        let root = TempDir::new().unwrap();
        let path = root.path().join("sequence.sqlite");
        let store = AuthBusAuthorityStore::open(&path).await.unwrap();
        let initial = AuthorityCheckpoint {
            generation: 1,
            digest: store.authority_frontier_digest().await.unwrap(),
        };
        store
            .initialize_authority_checkpoint(initial)
            .await
            .unwrap();
        store.observe_time(time(1)).await.unwrap();
        let checkpoint = store
            .reconcile_authority_checkpoint(initial)
            .await
            .unwrap()
            .unwrap();
        store
            .advance_authority_checkpoint(initial.generation, checkpoint)
            .await
            .unwrap();
        let applied = sqlx::query_scalar(
            "SELECT applied_change_id FROM authbus_frontier_accumulator WHERE singleton = 1",
        )
        .fetch_one(&store.pool)
        .await
        .unwrap();
        Self {
            _root: root,
            path,
            store,
            checkpoint,
            applied,
        }
    }

    async fn assert_rejected_without_time_or_journal_change(&self) {
        let before = self.store.last_trusted_time().await.unwrap();
        let journal: Vec<(i64, String)> = sqlx::query_as(
            "SELECT change_id, canonical_record FROM authbus_frontier_change ORDER BY change_id",
        )
        .fetch_all(&self.store.pool)
        .await
        .unwrap();
        assert!(matches!(
            self.store.observe_time(time(3)).await,
            Err(AuthBusAuthorityError::CorruptState(
                "invalid AuthBus frontier sequence"
            ))
        ));
        assert!(matches!(
            self.store.authority_frontier_digest().await,
            Err(AuthBusAuthorityError::CorruptState(
                "invalid AuthBus frontier sequence"
            ))
        ));
        assert_eq!(self.store.last_trusted_time().await.unwrap(), before);
        let after: Vec<(i64, String)> = sqlx::query_as(
            "SELECT change_id, canonical_record FROM authbus_frontier_change ORDER BY change_id",
        )
        .fetch_all(&self.store.pool)
        .await
        .unwrap();
        assert_eq!(after, journal);
    }
}

#[tokio::test]
async fn rewind_is_rejected_before_the_next_authority_mutation() {
    let fixture = Fixture::new().await;
    assert!(fixture.applied > 0);
    // Privileged storage corruption, not a supported authority caller operation.
    sqlx::query("UPDATE sqlite_sequence SET seq = ? WHERE name = 'authbus_frontier_change'")
        .bind(fixture.applied - 1)
        .execute(&fixture.store.pool)
        .await
        .unwrap();
    fixture
        .assert_rejected_without_time_or_journal_change()
        .await;
    let sequence: i64 = sqlx::query_scalar(
        "SELECT seq FROM sqlite_sequence WHERE name = 'authbus_frontier_change'",
    )
    .fetch_one(&fixture.store.pool)
    .await
    .unwrap();
    assert_eq!(sequence, fixture.applied - 1, "never repair the counter");
}

#[tokio::test]
async fn already_reused_event_is_rejected_even_when_sequence_looks_current() {
    let fixture = Fixture::new().await;
    sqlx::query("UPDATE sqlite_sequence SET seq = ? WHERE name = 'authbus_frontier_change'")
        .bind(fixture.applied - 1)
        .execute(&fixture.store.pool)
        .await
        .unwrap();
    // Reproduce an old-owner committed event after corruption. This bypass is
    // deliberately confined to the fixture; production begin now rejects first.
    sqlx::query(
        "UPDATE authbus_trusted_time SET wall_time_ms = ?, source_revision = ?, source_digest = ?
         WHERE singleton = 1",
    )
    .bind(1_200_u64.to_be_bytes().as_slice())
    .bind(2_u64.to_be_bytes().as_slice())
    .bind(
        Digest32::of_bytes(b"corrupt old-owner event")
            .as_array()
            .as_slice(),
    )
    .execute(&fixture.store.pool)
    .await
    .unwrap();
    let sequence: i64 = sqlx::query_scalar(
        "SELECT seq FROM sqlite_sequence WHERE name = 'authbus_frontier_change'",
    )
    .fetch_one(&fixture.store.pool)
    .await
    .unwrap();
    assert_eq!(sequence, fixture.applied);
    fixture
        .assert_rejected_without_time_or_journal_change()
        .await;
}

#[tokio::test]
async fn missing_and_duplicate_sequence_rows_are_rejected() {
    let missing = Fixture::new().await;
    sqlx::query("DELETE FROM sqlite_sequence WHERE name = 'authbus_frontier_change'")
        .execute(&missing.store.pool)
        .await
        .unwrap();
    missing
        .assert_rejected_without_time_or_journal_change()
        .await;
    let duplicate = Fixture::new().await;
    sqlx::query("INSERT INTO sqlite_sequence(name,seq) SELECT name,seq FROM sqlite_sequence WHERE name = 'authbus_frontier_change'")
        .execute(&duplicate.store.pool).await.unwrap();
    duplicate
        .assert_rejected_without_time_or_journal_change()
        .await;
}

#[tokio::test]
async fn noninteger_negative_and_out_of_range_sequence_values_are_rejected() {
    for encoded in ["1.5", "\"invalid\"", "null", "-1", "9223372036854775808.0"] {
        let fixture = Fixture::new().await;
        // JSON extraction supplies the exact SQLite storage class of each
        // corruption fixture while keeping the SQL statement literal/bound.
        sqlx::query("UPDATE sqlite_sequence SET seq = json_extract(?, '$') WHERE name = 'authbus_frontier_change'")
            .bind(encoded).execute(&fixture.store.pool).await.unwrap();
        fixture
            .assert_rejected_without_time_or_journal_change()
            .await;
    }
}

#[tokio::test]
async fn retained_nonpositive_events_are_rejected_without_pruning() {
    for change_id in [0_i64, -1] {
        let fixture = Fixture::new().await;
        sqlx::query("INSERT INTO authbus_frontier_change(change_id,domain,operation,record_key,canonical_record) VALUES(?, 'fixture', 'upsert', 'fixture', 'fixture')")
            .bind(change_id).execute(&fixture.store.pool).await.unwrap();
        fixture
            .assert_rejected_without_time_or_journal_change()
            .await;
    }
}

#[tokio::test]
async fn sequence_below_pending_event_is_rejected_before_fold() {
    let fixture = Fixture::new().await;
    fixture.store.observe_time(time(2)).await.unwrap();
    sqlx::query("UPDATE sqlite_sequence SET seq = ? WHERE name = 'authbus_frontier_change'")
        .bind(fixture.applied)
        .execute(&fixture.store.pool)
        .await
        .unwrap();
    fixture
        .assert_rejected_without_time_or_journal_change()
        .await;
}

#[tokio::test]
async fn startup_rejects_corruption_before_recovery_state_update() {
    let fixture = Fixture::new().await;
    sqlx::query("UPDATE authbus_recovery_state SET recovery_required = 1 WHERE singleton = 1")
        .execute(&fixture.store.pool)
        .await
        .unwrap();
    sqlx::query("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'authbus_frontier_change'")
        .execute(&fixture.store.pool)
        .await
        .unwrap();
    assert!(matches!(
        AuthBusAuthorityStore::open(&fixture.path).await,
        Err(AuthBusAuthorityError::CorruptState(
            "invalid AuthBus frontier sequence"
        ))
    ));
    assert!(fixture.store.recovery_required().await.unwrap());
}

#[tokio::test]
async fn normal_gapped_sequence_and_pending_recovery_advance_frontier() {
    let fixture = Fixture::new().await;
    sqlx::query("UPDATE sqlite_sequence SET seq = ? WHERE name = 'authbus_frontier_change'")
        .bind(fixture.applied + 3)
        .execute(&fixture.store.pool)
        .await
        .unwrap();
    fixture.store.observe_time(time(2)).await.unwrap();
    let reopened = AuthBusAuthorityStore::open(&fixture.path).await.unwrap();
    let next = reopened
        .reconcile_authority_checkpoint(fixture.checkpoint)
        .await
        .unwrap()
        .unwrap();
    assert_ne!(next.digest, fixture.checkpoint.digest);
    reopened
        .advance_authority_checkpoint(fixture.checkpoint.generation, next)
        .await
        .unwrap();
    assert_eq!(
        reopened.authority_frontier_digest().await.unwrap(),
        next.digest
    );
    assert_eq!(reopened.last_trusted_time().await.unwrap(), Some(time(2)));
}
