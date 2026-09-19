use std::error::Error;
use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::outbox_id;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_store::MatrixDispatchContext;
use codex_hepta_matrix_store::MatrixDispatchIntent;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::OutboxState;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_matrix_store::matrix_dispatch_operation_id;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn agent_layout(temp: &TempDir) -> TestResult<(AgentId, HeptaAgentLayout)> {
    let agent_id = AgentId::parse(AGENT)?;
    let fleet_root = temp.path().join("fleet");
    fs::create_dir_all(&fleet_root)?;
    let root = HeptaFleetRoot::parse(fleet_root.canonicalize()?)?;
    let layout = root.layout().agent(&agent_id);
    Ok((agent_id, layout))
}

async fn reopen_store(temp: &TempDir) -> TestResult<MatrixDurableStore> {
    let (_, layout) = agent_layout(temp)?;
    Ok(MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?)
}

async fn prepared_store(temp: &TempDir) -> TestResult<(MatrixDurableStore, AgentId, MatrixRoomId)> {
    let (agent_id, layout) = agent_layout(temp)?;
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let room_id = MatrixRoomId::parse("!dispatch:example.test")?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room_id.clone(),
            agent_user_id: MatrixUserId::parse("@agent:example.test")?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    Ok((store, agent_id, room_id))
}

async fn enqueue_final(
    store: &MatrixDurableStore,
    agent_id: &AgentId,
    room_id: &MatrixRoomId,
    payload: &[u8],
) -> TestResult<codex_hepta_matrix_store::OutboxRecord> {
    let logical = outbox_id(agent_id, room_id, "thread-1", "turn-1", "item-1", "final");
    let txn_id = transaction_id(&logical, 1)?;
    let disposition = store
        .enqueue_outbox(&OutboxDraft {
            logical_outbox_id: logical,
            revision: 1,
            txn_id,
            room_id: room_id.clone(),
            kind: OutboxKind::Final,
            payload: payload.to_vec(),
            binding_revision: 1,
            generation: 1,
            created_at_ms: 2,
        })
        .await?;
    Ok(match disposition {
        codex_hepta_matrix_store::OutboxDisposition::Enqueued(record)
        | codex_hepta_matrix_store::OutboxDisposition::Coalesced(record)
        | codex_hepta_matrix_store::OutboxDisposition::Duplicate(record) => record,
    })
}

fn intent(record: &codex_hepta_matrix_store::OutboxRecord, payload: &[u8]) -> MatrixDispatchIntent {
    let payload_digest = Sha256Digest::for_bytes(payload).as_str().to_string();
    MatrixDispatchIntent {
        operation_id: matrix_dispatch_operation_id(&record.stable_txn_id),
        stable_txn_id: record.stable_txn_id.clone(),
        room_id: record.room_id.clone(),
        payload_digest: payload_digest.clone(),
        context: MatrixDispatchContext {
            homeserver_id: Some("https://matrix.example.test".to_string()),
            device_id: Some("DEVICE1".to_string()),
            session_generation: 1,
            binding_revision: 1,
            authority_epoch: Some(7),
            authority_binding_digest: Some("a".repeat(64)),
            grant_id: Some("grant.1".to_string()),
            grant_payload_digest: Some(payload_digest),
        },
    }
}

#[tokio::test]
async fn accepted_send_stays_indeterminate_until_server_observation_and_survives_reopen()
-> TestResult {
    let temp = TempDir::new()?;
    let (store, agent_id, room_id) = prepared_store(&temp).await?;
    let payload = b"durable terminal observation";
    let outbox = enqueue_final(&store, &agent_id, &room_id, payload).await?;
    let claimed = store.claim_outbox(10, 20, 1).await?;
    assert_eq!(claimed.len(), 1);
    let claimed = &claimed[0];
    assert_eq!(claimed.stable_txn_id, outbox.stable_txn_id);

    store
        .prepare_matrix_dispatch(10, &intent(claimed, payload))
        .await?;
    store
        .record_matrix_dispatch_attempt(&claimed.stable_txn_id, claimed.attempts, 10)
        .await?;
    let accepted_event = MatrixEventId::parse("$accepted:example.test")?;
    let accepted = store
        .record_matrix_transport_acceptance(
            &claimed.stable_txn_id,
            claimed.attempts,
            &accepted_event,
            11,
        )
        .await?;
    assert_eq!(accepted.state, MatrixDispatchState::Indeterminate);
    let still_in_flight = store.claim_outbox(12, 20, 1).await?;
    assert!(still_in_flight.is_empty());
    store.close().await;

    let reopened = reopen_store(&temp).await?;
    let pending = reopened
        .matrix_dispatch_receipt(&claimed.stable_txn_id)
        .await?
        .expect("durable receipt");
    assert_eq!(pending.state, MatrixDispatchState::Indeterminate);
    assert_eq!(pending.accepted_event_id.as_ref(), Some(&accepted_event));

    let settled = reopened
        .observe_matrix_server_event(
            Some(&claimed.stable_txn_id),
            &accepted_event,
            &room_id,
            1,
            1,
            &"b".repeat(64),
            20,
        )
        .await?
        .expect("matching server event");
    assert_eq!(settled.state, MatrixDispatchState::ObservedSucceeded);
    assert!(settled.archived);
    assert_eq!(settled.send_observation_digest, Some("b".repeat(64)));

    let snapshot = reopened.snapshot(32).await?;
    let sent = snapshot
        .outbox
        .iter()
        .find(|record| record.stable_txn_id == claimed.stable_txn_id)
        .expect("outbox record");
    assert_eq!(sent.state, OutboxState::Sent);
    assert_eq!(sent.sent_event_id.as_ref(), Some(&accepted_event));
    Ok(())
}

#[tokio::test]
async fn ack_loss_retries_same_transaction_after_reopen() -> TestResult {
    let temp = TempDir::new()?;
    let (store, agent_id, room_id) = prepared_store(&temp).await?;
    let payload = b"ack loss";
    let outbox = enqueue_final(&store, &agent_id, &room_id, payload).await?;
    let claimed = store.claim_outbox(10, 5, 1).await?.remove(0);
    store
        .prepare_matrix_dispatch(10, &intent(&claimed, payload))
        .await?;
    store
        .record_matrix_dispatch_attempt(&claimed.stable_txn_id, claimed.attempts, 10)
        .await?;
    store
        .record_matrix_transport_indeterminate_and_retry(
            &claimed.stable_txn_id,
            claimed.attempts,
            11,
            25,
        )
        .await?;
    store.close().await;

    let reopened = reopen_store(&temp).await?;
    assert!(reopened.claim_outbox(24, 5, 1).await?.is_empty());
    let retried = reopened.claim_outbox(25, 5, 1).await?;
    assert_eq!(retried.len(), 1);
    assert_eq!(retried[0].stable_txn_id, outbox.stable_txn_id);
    assert_eq!(retried[0].attempts, claimed.attempts + 1);
    let pending = reopened
        .matrix_dispatch_receipt(&outbox.stable_txn_id)
        .await?
        .expect("dispatch receipt");
    assert_eq!(pending.state, MatrixDispatchState::Indeterminate);
    Ok(())
}

#[tokio::test]
async fn redaction_preserves_original_send_evidence_and_terminal_rows_leave_active_capacity()
-> TestResult {
    let temp = TempDir::new()?;
    let (store, agent_id, room_id) = prepared_store(&temp).await?;
    let payload = b"redact me";
    let outbox = enqueue_final(&store, &agent_id, &room_id, payload).await?;
    let claimed = store.claim_outbox(10, 20, 1).await?.remove(0);
    store
        .record_matrix_dispatch_attempt(&claimed.stable_txn_id, claimed.attempts, 10)
        .await?;
    let event_id = MatrixEventId::parse("$sent:example.test")?;
    store
        .record_matrix_transport_acceptance(&claimed.stable_txn_id, claimed.attempts, &event_id, 11)
        .await?;
    let succeeded = store
        .observe_matrix_server_event(
            Some(&claimed.stable_txn_id),
            &event_id,
            &room_id,
            1,
            1,
            &"b".repeat(64),
            12,
        )
        .await?
        .expect("server observation");
    assert_eq!(succeeded.state, MatrixDispatchState::ObservedSucceeded);
    assert_eq!(store.unresolved_matrix_dispatch_count().await?, 0);

    let redaction_event = MatrixEventId::parse("$redaction:example.test")?;
    let redacted = store
        .observe_matrix_redaction(&event_id, &redaction_event, &"c".repeat(64), 13)
        .await?
        .expect("redaction observation");
    assert_eq!(redacted.state, MatrixDispatchState::Redacted);
    assert_eq!(redacted.send_observation_digest, Some("b".repeat(64)));
    assert_eq!(redacted.redaction_observation_digest, Some("c".repeat(64)));
    let replay = store
        .observe_matrix_redaction(&event_id, &redaction_event, &"c".repeat(64), 14)
        .await?
        .expect("idempotent redaction");
    assert!(replay.idempotent);
    assert_eq!(store.unresolved_matrix_dispatch_count().await?, 0);
    assert_eq!(outbox.stable_txn_id, claimed.stable_txn_id);
    Ok(())
}
