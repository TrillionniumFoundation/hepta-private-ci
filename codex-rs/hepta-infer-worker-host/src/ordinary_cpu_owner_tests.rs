use super::*;
use crate::OrdinaryCpuBinding;
use crate::OrdinaryCpuRegistration;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::time::Duration;
use tempfile::TempDir;

pub(super) fn registration(temp: &TempDir) -> OrdinaryCpuRegistration {
    OrdinaryCpuRegistration::new(
        OrdinaryCpuBinding {
            subject_id: StableId::new("ordinary-host-subject").expect("subject"),
            scope_digest: Digest32::of_bytes(b"ordinary-child-only-scope"),
            policy_generation: Generation::new(1).expect("generation"),
            source_digest: Digest32::of_bytes(b"registered-test-worker-source"),
            worker_id: StableId::new("fixed-ordinary-worker").expect("worker"),
            profile_id: StableId::new("ordinary-test-profile").expect("profile"),
            observer_deadline: Duration::from_secs(8),
        },
        temp.path().join("fixed-worker"),
        vec!["fixed-argument".to_owned()],
    )
    .expect("registration")
}

pub(super) async fn pool(temp: &TempDir) -> SqlitePool {
    let root = temp.path().canonicalize().expect("private root");
    let config =
        SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(root.clone()).expect("absolute"));
    let pool = config
        .open_durable_evidence_pool(&root.join("ordinary-owner.sqlite"))
        .await
        .expect("pool");
    sqlx::raw_sql(include_str!("../ordinary_cpu_owner.sql"))
        .execute(&pool)
        .await
        .expect("owner migration");
    pool
}

#[tokio::test]
async fn committed_entry_survives_all_connection_replacements_and_owner_recreation() {
    let temp = TempDir::new().expect("temp");
    let pool = pool(&temp).await;
    let registration = registration(&temp);
    let intent = registration
        .operation(StableId::new("effect-one").expect("id"))
        .expect("intent");
    let owner = OrdinaryCpuOwner::from_migrated_pool(pool.clone())
        .await
        .expect("owner");
    assert!(matches!(
        owner.enter(&intent).await.expect("entry"),
        Entry::New(0)
    ));
    let counts: (i64, i64) = sqlx::query_as("SELECT (SELECT COUNT(*) FROM ordinary_cpu_entries), (SELECT COUNT(*) FROM destination_operation_dedupe)")
        .fetch_one(&pool).await.expect("counts");
    assert_eq!(counts, (1, 1));
    drop(owner);
    // Replace every physical SQLite connection in this existing trusted fixture
    // pool. This is not a pool/process restart or qualified identity-bound recovery.
    let mut connections = Vec::new();
    for _ in 0..5 {
        connections.push(pool.acquire().await.expect("fixture connection"));
    }
    for connection in connections {
        connection.close().await.expect("physical connection close");
    }
    assert_eq!(pool.size(), 0);
    let recreated = OrdinaryCpuOwner::from_migrated_pool(pool.clone())
        .await
        .expect("owner recreation with fresh connections");
    assert!(matches!(
        recreated.enter(&intent).await.expect("replay"),
        Entry::Retained
    ));
    assert_eq!(
        recreated.entry(&intent).await.expect("observation"),
        Some((0, None))
    );
    assert!(
        sqlx::query("DELETE FROM ordinary_cpu_entries")
            .execute(&pool)
            .await
            .is_err()
    );
    assert!(
        sqlx::query("DELETE FROM destination_operation_dedupe")
            .execute(&pool)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn capacity_and_mid_transaction_failure_never_leave_partial_admission() {
    let temp = TempDir::new().expect("temp");
    let pool = pool(&temp).await;
    let registration = registration(&temp);
    let owner = OrdinaryCpuOwner::from_migrated_pool(pool.clone())
        .await
        .expect("owner");
    sqlx::raw_sql("CREATE TRIGGER fail_dedupe BEFORE INSERT ON destination_operation_dedupe BEGIN SELECT RAISE(ABORT, 'original injected commit cut'); END;")
        .execute(&pool).await.expect("cut");
    let intent = registration
        .operation(StableId::new("cut-effect").expect("id"))
        .expect("intent");
    assert!(owner.enter(&intent).await.is_err());
    assert_eq!(owner.entry(&intent).await.expect("no row"), None);
    sqlx::query("DROP TRIGGER fail_dedupe")
        .execute(&pool)
        .await
        .expect("remove cut");
    for slot in 0..CAPACITY {
        let intent = registration
            .operation(StableId::new(format!("effect-{slot}")).expect("id"))
            .expect("intent");
        assert!(
            matches!(owner.enter(&intent).await.expect("entry"), Entry::New(actual) if actual == slot)
        );
    }
    // Storage-only terminal rows still consume the same permanent lifetime cap.
    sqlx::query("UPDATE ordinary_cpu_entries SET terminal_receipt = 'storage-only-test-terminal'")
        .execute(&pool)
        .await
        .expect("fixture terminal rows");
    let mut connections = Vec::new();
    for _ in 0..5 {
        let mut connection = pool.acquire().await.expect("owner connection");
        sqlx::query("PRAGMA recursive_triggers = OFF")
            .execute(&mut *connection)
            .await
            .expect("replacement control");
        connections.push(connection);
    }
    drop(connections);
    let last = registration
        .operation(StableId::new("effect-15").expect("id"))
        .expect("last intent");
    assert!(sqlx::query("INSERT OR REPLACE INTO ordinary_cpu_entries(slot, operation_id, semantic_digest) VALUES (0, ?, ?)")
        .bind(last.operation_id().as_str()).bind(last.semantic_digest().as_array().as_slice())
        .execute(&pool).await.is_err(), "REPLACE must not remove two permanent tombstones even with recursive triggers disabled");
    let overflow = registration
        .operation(StableId::new("overflow-effect").expect("id"))
        .expect("intent");
    assert!(
        owner
            .enter(&overflow)
            .await
            .expect_err("fixed lifetime cap")
            .contains("capacity")
    );
    let counts: (i64, i64) = sqlx::query_as("SELECT (SELECT COUNT(*) FROM ordinary_cpu_entries), (SELECT COUNT(*) FROM destination_operation_dedupe)")
        .fetch_one(&pool).await.expect("counts");
    assert_eq!(counts, (16, 16));
}

#[tokio::test]
async fn constructor_and_actual_entry_refuse_non_full_connections() {
    let temp = TempDir::new().expect("temp");
    let pool = pool(&temp).await;
    let owner = OrdinaryCpuOwner::from_migrated_pool(pool.clone())
        .await
        .expect("initial FULL owner");
    let mut connections = Vec::new();
    for _ in 0..5 {
        let mut connection = pool
            .acquire()
            .await
            .expect("one of the five owner connections");
        sqlx::query("PRAGMA synchronous = NORMAL")
            .execute(&mut *connection)
            .await
            .expect("non-FULL fixture");
        connections.push(connection);
    }
    drop(connections);
    assert!(
        OrdinaryCpuOwner::from_migrated_pool(pool.clone())
            .await
            .err()
            .expect("constructor refusal")
            .contains("FULL")
    );
    let registration = registration(&temp);
    let intent = registration
        .operation(StableId::new("non-full-effect").expect("id"))
        .expect("intent");
    assert!(
        owner
            .enter(&intent)
            .await
            .expect_err("actual connection must remain FULL")
            .contains("FULL")
    );
    assert_eq!(owner.entry(&intent).await.expect("no entry"), None);
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM destination_operation_dedupe")
        .fetch_one(&pool)
        .await
        .expect("no dedupe");
    assert_eq!(count, 0);
}
