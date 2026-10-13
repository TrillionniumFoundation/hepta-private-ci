//! Matrix evidence pool regression after removing the heavyweight Codex state
//! dependency. This is real SQLite/WAL execution, not a synthetic graph test.
//! It does NOT attest Matrix SDK 0.19 E2EE, artifact promotion, or production WAL
//! fault recovery on target hardware.

use std::error::Error;
use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaFleetRoot;
use sqlx::ConnectOptions;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;
use tempfile::TempDir;

type TestResult = Result<(), Box<dyn Error>>;

#[tokio::test]
#[expect(
    clippy::disallowed_methods,
    reason = "the test deliberately opens a separately read-only SQLite observer to check the on-disk WAL; authority is still held by MatrixDurableStore"
)]
async fn matrix_evidence_pool_preserves_wal_full_fk_and_owner_after_restart() -> TestResult {
    let temp = TempDir::new()?;
    let root = temp.path().join("fleet");
    fs::create_dir_all(&root)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let layout = HeptaFleetRoot::parse(root.canonicalize()?)?
        .layout()
        .agent(&agent);

    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    // Queries the owner connection: WAL, synchronous=FULL, FK=ON,
    // busy_timeout=5000. Fails rather than permitting degraded durability.
    store.verify_durability_profile().await?;
    let room = MatrixRoomId::parse("!profile:example.test")?;
    let user = MatrixUserId::parse("@agent:example.test")?;
    let record = store
        .bind_room(&RoomBindingDraft {
            room_id: room.clone(),
            agent_user_id: user.clone(),
            expected_revision: None,
            generation: 1,
            changed_at_ms: 7,
        })
        .await?;
    assert_eq!(record.revision, 1);

    let db_path = store.path().to_path_buf();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(fs::metadata(&db_path)?.permissions().mode() & 0o777, 0o600);
    }
    // Independent read-only observer checks the on-disk database is WAL.
    // Its own synchronous pragma is NOT incorrectly treated as owner evidence.
    let read_only = SqliteConnectOptions::new()
        .filename(&db_path)
        .create_if_missing(false)
        .read_only(true)
        .disable_statement_logging();
    let observer = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(read_only)
        .await?;
    let journal: String = sqlx::query_scalar("PRAGMA journal_mode")
        .fetch_one(&observer)
        .await?;
    assert!(journal.eq_ignore_ascii_case("wal"));
    observer.close().await;
    store.close().await;

    // Restart on the same existing owner root; never reconstruct from an
    // untrusted alternate database or silently replace the previous registry.
    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    reopened.verify_durability_profile().await?;
    let recovered = reopened
        .room_binding(&room)
        .await?
        .ok_or("durable binding lost across SQLite restart")?;
    assert_eq!(recovered.owner_agent_id, agent);
    assert_eq!(recovered.agent_user_id, user);
    assert_eq!(recovered.revision, 1);
    reopened.close().await;
    Ok(())
}
