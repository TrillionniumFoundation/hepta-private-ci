//! Native SQLite regressions for the content pin, not a grant/remote-effect oracle.
use std::error::Error;
use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::outbox_id;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::MatrixFencedOutboxClaim;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

async fn fixture() -> TestResult<(TempDir, HeptaAgentLayout, MatrixDurableStore)> {
    let temp = TempDir::new()?;
    let root = temp.path().join("fleet");
    fs::create_dir_all(&root)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let layout = HeptaFleetRoot::parse(root.canonicalize()?)?
        .layout()
        .agent(&agent);
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let room = MatrixRoomId::parse("!allowed:example.test")?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room.clone(),
            agent_user_id: MatrixUserId::parse("@agent:example.test")?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    let logical = outbox_id(&agent, &room, "thread", "turn", "item", "final");
    store
        .enqueue_outbox(&OutboxDraft {
            txn_id: transaction_id(&logical, /*revision*/ 1)?,
            logical_outbox_id: logical,
            revision: 1,
            room_id: room,
            kind: OutboxKind::Final,
            payload: b"complete".to_vec(),
            binding_revision: 1,
            generation: 1,
            created_at_ms: 2,
        })
        .await?;
    Ok((temp, layout, store))
}

async fn claim(store: &MatrixDurableStore, now_ms: u64) -> TestResult<MatrixFencedOutboxClaim> {
    let mut claims = store
        .claim_outbox_fenced(now_ms, /*lease_ms*/ 100, /*limit*/ 1)
        .await?;
    let claim = claims.pop().ok_or("claim missing")?;
    store
        .prepare_outbox_dispatch(claim.record(), now_ms + 1)
        .await?;
    Ok(claim)
}

#[tokio::test]
async fn pin_survives_reopen_and_rejects_content_scope_and_old_claim_drift() -> TestResult {
    let (_temp, layout, store) = fixture().await?;
    let first = claim(&store, /*now_ms*/ 10).await?;
    store
        .pin_outbox_content(
            &first,
            &"a".repeat(64),
            &"b".repeat(64),
            /*recorded_at_ms*/ 12,
        )
        .await?;
    store
        .pin_outbox_content(
            &first,
            &"a".repeat(64),
            &"b".repeat(64),
            /*recorded_at_ms*/ 13,
        )
        .await?;
    store
        .release_outbox_claim_canceled(&first, /*recorded_at_ms*/ 14)
        .await?;
    store.close().await;
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let second = claim(&store, /*now_ms*/ 20).await?;
    assert_eq!(first.record().stable_txn_id, second.record().stable_txn_id);
    store
        .pin_outbox_content(
            &second,
            &"a".repeat(64),
            &"b".repeat(64),
            /*recorded_at_ms*/ 22,
        )
        .await?;
    for (content, scope) in [("c", "b"), ("a", "c")] {
        assert_eq!(
            store
                .pin_outbox_content(
                    &second,
                    &content.repeat(64),
                    &scope.repeat(64),
                    /*recorded_at_ms*/ 23
                )
                .await,
            Err(MatrixDurableError::Conflict)
        );
    }
    assert_eq!(
        store
            .pin_outbox_content(
                &first,
                &"a".repeat(64),
                &"b".repeat(64),
                /*recorded_at_ms*/ 24
            )
            .await,
        Err(MatrixDurableError::Conflict)
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn new_pre_pin_cancellation_survives_reopen_and_keeps_transaction_identity() -> TestResult {
    let (_temp, layout, store) = fixture().await?;
    let first = claim(&store, /*now_ms*/ 10).await?;
    store
        .release_outbox_claim_canceled(&first, /*recorded_at_ms*/ 12)
        .await?;
    store.close().await;
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let second = claim(&store, /*now_ms*/ 20).await?;
    assert_eq!(first.record().stable_txn_id, second.record().stable_txn_id);
    store
        .pin_outbox_content(
            &second,
            &"a".repeat(64),
            &"b".repeat(64),
            /*recorded_at_ms*/ 22,
        )
        .await?;
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn a_same_named_weakened_trigger_fails_the_content_boundary_check() -> TestResult {
    let (_temp, _layout, store) = fixture().await?;
    let claimed = claim(&store, /*now_ms*/ 10).await?;
    let path = store.path();
    let parent = path
        .parent()
        .ok_or_else(|| std::io::Error::other("matrix store parent is missing"))?;
    let sqlite = SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(parent.to_path_buf())?);
    let pool = sqlite.open_durable_evidence_pool(path).await?;
    sqlx::query("DROP TRIGGER matrix_dispatch_content_bindings_no_update")
        .execute(&pool)
        .await?;
    sqlx::query("CREATE TRIGGER matrix_dispatch_content_bindings_no_update BEFORE UPDATE ON matrix_dispatch_content_bindings BEGIN SELECT 1; END")
        .execute(&pool)
        .await?;
    pool.close().await;
    assert_eq!(
        store
            .pin_outbox_content(
                &claimed,
                &"a".repeat(64),
                &"b".repeat(64),
                /*recorded_at_ms*/ 12
            )
            .await,
        Err(MatrixDurableError::Corrupt)
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn expiry_and_invalid_digests_cannot_publish_a_pin() -> TestResult {
    let (_temp, _layout, store) = fixture().await?;
    let claimed = claim(&store, /*now_ms*/ 10).await?;
    assert_eq!(
        store
            .pin_outbox_content(
                &claimed,
                &"a".repeat(64),
                &"0".repeat(64),
                /*recorded_at_ms*/ 12
            )
            .await,
        Err(MatrixDurableError::Invalid)
    );
    assert_eq!(
        store
            .pin_outbox_content(
                &claimed,
                &"a".repeat(64),
                &"b".repeat(64),
                /*recorded_at_ms*/ 110
            )
            .await,
        Err(MatrixDurableError::Conflict)
    );
    store.close().await;
    Ok(())
}
