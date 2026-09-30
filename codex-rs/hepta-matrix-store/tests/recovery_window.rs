use std::error::Error;
use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

#[tokio::test]
async fn recovery_frontier_reaches_rows_beyond_a_full_window_and_wraps_without_duplicates()
-> Result<(), Box<dyn Error>> {
    let temp = TempDir::new()?;
    let fleet = temp.path().join("fleet");
    fs::create_dir_all(&fleet)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let layout = HeptaFleetRoot::parse(fleet.canonicalize()?)?
        .layout()
        .agent(&agent);
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let room = MatrixRoomId::parse("!recovery-window:example.test")?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room.clone(),
            agent_user_id: MatrixUserId::parse("@agent:example.test")?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    let fixture_pool = sqlx::sqlite::SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(sqlx::sqlite::SqliteConnectOptions::new().filename(store.path()))
        .await?;
    let mut fixture = fixture_pool.begin().await?;
    let payload = b"pending recovery fixture";
    let digest = Sha256Digest::for_bytes(payload);
    // Bulk fixture construction keeps the regression about recovery windows,
    // rather than timing 1041 individually durable ingress commits.
    for index in 1..=1_041_i64 {
        sqlx::query(
            "INSERT INTO inbox_events (
                event_id, room_id, sender_user_id, event_type, payload, payload_sha256,
                binding_revision, generation, origin_server_ts_ms, received_at_ms,
                state, processed_at_ms
             ) VALUES (?, ?, '@owner:example.test', 'm.room.message', ?, ?, 1, 1, ?, ?,
                       'pending', NULL)",
        )
        .bind(format!("$pending-{index}"))
        .bind(room.as_str())
        .bind(payload.as_slice())
        .bind(digest.as_str())
        .bind(index)
        .bind(index)
        .execute(&mut *fixture)
        .await?;
    }
    fixture.commit().await?;
    fixture_pool.close().await;

    let first = store
        .pending_recovery_inbox(/*limit*/ 1_024, /*after_cursor*/ 0)
        .await?;
    assert_eq!(
        first.iter().map(|record| record.cursor).collect::<Vec<_>>(),
        (1..=1_024).collect::<Vec<_>>()
    );
    let next = store
        .pending_recovery_inbox(/*limit*/ 1_024, /*after_cursor*/ 1_024)
        .await?;
    assert_eq!(
        next.iter().map(|record| record.cursor).collect::<Vec<_>>(),
        (1_025..=1_041).chain(1..=1_007).collect::<Vec<_>>()
    );
    let frontier = next.last().ok_or("recovery window empty")?.cursor;
    store.close().await;
    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let resumed = reopened
        .pending_recovery_inbox(/*limit*/ 1_024, frontier)
        .await?;
    assert_eq!(
        resumed
            .iter()
            .map(|record| record.cursor)
            .collect::<Vec<_>>(),
        (1_008..=1_041).chain(1..=990).collect::<Vec<_>>()
    );
    reopened.close().await;
    Ok(())
}
