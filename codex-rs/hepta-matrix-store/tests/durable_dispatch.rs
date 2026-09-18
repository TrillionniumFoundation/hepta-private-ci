use std::error::Error;
use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::OutboxState;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;
const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

fn layout(temp: &TempDir, agent_id: &AgentId) -> TestResult<HeptaAgentLayout> {
    let fleet_root = temp.path().join("fleet");
    fs::create_dir_all(&fleet_root)?;
    Ok(HeptaFleetRoot::parse(fleet_root.canonicalize()?)?
        .layout()
        .agent(agent_id))
}

async fn prepared_store(
    temp: &TempDir,
) -> TestResult<(HeptaAgentLayout, MatrixDurableStore, MatrixRoomId)> {
    let agent = AgentId::parse(AGENT)?;
    let layout = layout(temp, &agent)?;
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let room = MatrixRoomId::parse("!room:example.org")?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room.clone(),
            agent_user_id: MatrixUserId::parse("@agent:example.org")?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    Ok((layout, store, room))
}

async fn enqueue(
    store: &MatrixDurableStore,
    room: &MatrixRoomId,
    logical: &str,
    payload: &[u8],
    at_ms: u64,
) -> TestResult<codex_hepta_matrix_protocol::MatrixTransactionId> {
    let txn = transaction_id(logical, 1)?;
    store
        .enqueue_outbox(&OutboxDraft {
            logical_outbox_id: logical.to_string(),
            revision: 1,
            txn_id: txn.clone(),
            room_id: room.clone(),
            kind: OutboxKind::Final,
            payload: payload.to_vec(),
            binding_revision: 1,
            generation: 1,
            created_at_ms: at_ms,
        })
        .await?;
    Ok(txn)
}

#[tokio::test]
async fn transport_acceptance_is_not_terminal_and_observation_survives_reopen() -> TestResult {
    let temp = TempDir::new()?;
    let (layout, store, room) = prepared_store(&temp).await?;
    let txn = enqueue(&store, &room, "dispatch.acceptance", b"hello", 10).await?;
    let claimed = store.claim_outbox(10, 30, 1).await?;
    assert_eq!(claimed.len(), 1);
    let event = MatrixEventId::parse("$accepted:example.org")?;
    let accepted = store.mark_outbox_accepted(&txn, 1, &event, 11).await?;
    assert_eq!(accepted.state, MatrixDispatchState::Accepted);
    assert_eq!(
        store
            .outbox_for_txn(&txn)
            .await?
            .ok_or("outbox missing")?
            .state,
        OutboxState::InFlight
    );

    let send_digest = "a".repeat(64);
    store
        .observe_dispatch_terminal_success(&txn, &event, &send_digest, 12)
        .await?;
    let terminal = store
        .dispatch_record(&txn)
        .await?
        .ok_or("dispatch missing")?;
    assert_eq!(terminal.state, MatrixDispatchState::Succeeded);
    assert_eq!(
        terminal.send_observation_digest.as_deref(),
        Some(send_digest.as_str())
    );
    store.close().await;

    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let durable = reopened
        .dispatch_record(&txn)
        .await?
        .ok_or("dispatch missing after reopen")?;
    assert_eq!(durable.state, MatrixDispatchState::Succeeded);
    assert_eq!(durable.terminal_event_id.as_ref(), Some(&event));
    assert_eq!(
        reopened
            .outbox_for_txn(&txn)
            .await?
            .ok_or("outbox missing after reopen")?
            .state,
        OutboxState::Sent
    );
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn expired_in_flight_dispatch_is_frozen_instead_of_reclaimed() -> TestResult {
    let temp = TempDir::new()?;
    let (_layout, store, room) = prepared_store(&temp).await?;
    let txn = enqueue(&store, &room, "dispatch.crash", b"crash-window", 10).await?;
    assert_eq!(store.claim_outbox(10, 20, 1).await?.len(), 1);
    assert!(store.claim_outbox(31, 20, 1).await?.is_empty());
    let frozen = store
        .dispatch_record(&txn)
        .await?
        .ok_or("dispatch missing")?;
    assert_eq!(frozen.state, MatrixDispatchState::Indeterminate);
    assert_eq!(
        store
            .outbox_for_txn(&txn)
            .await?
            .ok_or("outbox missing")?
            .state,
        OutboxState::InFlight
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn redaction_appends_evidence_without_replacing_send_observation() -> TestResult {
    let temp = TempDir::new()?;
    let (_layout, store, room) = prepared_store(&temp).await?;
    let first = enqueue(&store, &room, "dispatch.redaction", b"redact-me", 10).await?;
    store.claim_outbox(10, 20, 1).await?;
    let event = MatrixEventId::parse("$redact-me:example.org")?;
    store.mark_outbox_accepted(&first, 1, &event, 11).await?;
    let send_digest = "b".repeat(64);
    let redaction_digest = "c".repeat(64);
    store
        .observe_dispatch_terminal_success(&first, &event, &send_digest, 12)
        .await?;
    store
        .apply_dispatch_redaction(&event, &redaction_digest, 13)
        .await?;
    let redacted = store
        .dispatch_record(&first)
        .await?
        .ok_or("dispatch missing")?;
    assert_eq!(redacted.state, MatrixDispatchState::Redacted);
    assert_eq!(
        redacted.send_observation_digest.as_deref(),
        Some(send_digest.as_str())
    );
    assert_eq!(
        redacted.redaction_observation_digest.as_deref(),
        Some(redaction_digest.as_str())
    );
    let observations = store.dispatch_observations(&first, 16).await?;
    assert!(observations.len() >= 3);

    // Terminal history is retained but is not part of the unresolved working
    // set; a fresh send remains admissible under the same store owner.
    let second = enqueue(&store, &room, "dispatch.after-terminal", b"next", 20).await?;
    assert_eq!(
        store
            .dispatch_record(&second)
            .await?
            .ok_or("second dispatch missing")?
            .state,
        MatrixDispatchState::Prepared
    );
    store.close().await;
    Ok(())
}
