use std::error::Error;
use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_store::ChangeKind;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::OutboxState;
use codex_hepta_matrix_store::OutboxUnresolvedRecord;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

#[tokio::test]
async fn unknown_outcome_is_exact_restart_safe_and_settles_only_the_issued_attempt() -> TestResult {
    let temp = TempDir::new()?;
    let root = temp.path().join("fleet");
    fs::create_dir_all(&root)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let layout = HeptaFleetRoot::parse(root.canonicalize()?)?
        .layout()
        .agent(&agent);
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let room = MatrixRoomId::parse("!unknown-outcome:example.test")?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room.clone(),
            agent_user_id: MatrixUserId::parse("@agent:example.test")?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    let stable_txn_id = transaction_id("unknown-stream", /*revision*/ 1)?;
    let alias_txn_id = transaction_id("unknown-stream", /*revision*/ 2)?;
    for (revision, txn_id) in [(1, stable_txn_id.clone()), (2, alias_txn_id.clone())] {
        store
            .enqueue_outbox(&OutboxDraft {
                logical_outbox_id: "unknown-stream".to_string(),
                revision,
                txn_id,
                room_id: room.clone(),
                kind: OutboxKind::TextDelta,
                payload: b"x".to_vec(),
                binding_revision: 1,
                generation: 1,
                created_at_ms: 20,
            })
            .await?;
    }
    assert_eq!(
        store
            .claim_outbox(/*now_ms*/ 170, /*lease_ms*/ 10, /*limit*/ 1)
            .await?
            .len(),
        1
    );
    assert_eq!(
        store
            .park_outbox_unresolved(
                &alias_txn_id,
                /*expected_attempt*/ 1,
                /*now_ms*/ 171
            )
            .await,
        Err(MatrixDurableError::Conflict)
    );
    assert_eq!(
        store
            .park_outbox_unresolved(
                &stable_txn_id,
                /*expected_attempt*/ 2,
                /*now_ms*/ 171
            )
            .await,
        Err(MatrixDurableError::Conflict)
    );
    assert_eq!(
        store
            .park_outbox_unresolved(
                &stable_txn_id,
                /*expected_attempt*/ 1,
                /*now_ms*/ 169
            )
            .await,
        Err(MatrixDurableError::Conflict)
    );
    let unresolved = OutboxUnresolvedRecord {
        stable_txn_id: stable_txn_id.clone(),
        attempts: 1,
        recorded_at_ms: 171,
    };
    assert_eq!(
        store
            .park_outbox_unresolved(
                &stable_txn_id,
                /*expected_attempt*/ 1,
                /*now_ms*/ 171
            )
            .await?,
        unresolved
    );
    let snapshot = store.snapshot(/*now_ms*/ 171, /*queue_limit*/ 10).await?;
    assert_eq!(
        store
            .park_outbox_unresolved(
                &stable_txn_id,
                /*expected_attempt*/ 1,
                /*now_ms*/ 172
            )
            .await?,
        unresolved
    );
    assert_eq!(
        store.snapshot(/*now_ms*/ 171, /*queue_limit*/ 10).await?,
        snapshot
    );
    assert_eq!(
        store
            .read_changes(/*after_cursor*/ 0, /*limit*/ 10)
            .await?
            .events
            .last()
            .ok_or("change")?
            .kind,
        ChangeKind::OutboxNeedsReconciliation
    );
    store.close().await;
    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    assert_eq!(
        reopened.unresolved_outbox(/*limit*/ 10).await?,
        vec![unresolved]
    );
    let record = reopened
        .outbox_for_txn(&stable_txn_id)
        .await?
        .ok_or("outbox")?;
    assert_eq!(
        (record.state, record.attempts, record.payload),
        (OutboxState::InFlight, 1, b"xx".to_vec())
    );
    assert_eq!(
        reopened
            .claim_outbox(
                /*now_ms*/ 1_000, /*lease_ms*/ 10, /*limit*/ 10
            )
            .await?,
        vec![]
    );
    assert_eq!(
        reopened
            .mark_outbox_retry(
                &stable_txn_id,
                /*expected_attempt*/ 1,
                /*now_ms*/ 1_000,
                /*next_attempt_at_ms*/ 1_001
            )
            .await,
        Err(MatrixDurableError::Conflict)
    );
    let observed = MatrixEventId::parse("$observed-unknown-transaction")?;
    assert_eq!(
        reopened
            .mark_outbox_sent(
                &alias_txn_id,
                /*expected_attempt*/ 1,
                &observed,
                /*now_ms*/ 1_000,
            )
            .await,
        Err(MatrixDurableError::Conflict)
    );
    assert_eq!(
        reopened
            .mark_outbox_sent(
                &stable_txn_id,
                /*expected_attempt*/ 2,
                &observed,
                /*now_ms*/ 1_000
            )
            .await,
        Err(MatrixDurableError::Conflict)
    );
    let sent = reopened
        .mark_outbox_sent(
            &stable_txn_id,
            /*expected_attempt*/ 1,
            &observed,
            /*now_ms*/ 1_000,
        )
        .await?;
    assert_eq!(
        reopened
            .mark_outbox_sent(
                &stable_txn_id,
                /*expected_attempt*/ 1,
                &observed,
                /*now_ms*/ 1_001
            )
            .await?,
        sent
    );
    assert_eq!(reopened.unresolved_outbox(/*limit*/ 10).await?, vec![]);
    assert_eq!(
        (sent.state, sent.attempts, sent.sent_event_id),
        (OutboxState::Sent, 1, Some(observed))
    );
    reopened.close().await;
    let reconciled = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    assert_eq!(reconciled.unresolved_outbox(/*limit*/ 10).await?, vec![]);
    assert_eq!(
        reconciled
            .claim_outbox(
                /*now_ms*/ 2_000, /*lease_ms*/ 10, /*limit*/ 10
            )
            .await?,
        vec![]
    );
    Ok(())
}
