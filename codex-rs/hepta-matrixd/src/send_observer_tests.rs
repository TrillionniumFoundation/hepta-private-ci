use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::outbox_id;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_store::MatrixDispatchContext;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::OutboxDisposition;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_matrix_store::matrix_dispatch_operation_id;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

use super::*;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

async fn fixture() -> (TempDir, MatrixDurableStore, SendIntent) {
    let temp = TempDir::new().expect("tempdir");
    let fleet_root = temp.path().join("fleet");
    fs::create_dir_all(&fleet_root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(fleet_root.canonicalize().expect("canonical fleet"))
        .expect("fleet root");
    let agent_id = AgentId::parse(AGENT).expect("agent id");
    let layout = fleet.layout().agent(&agent_id);
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default())
        .await
        .expect("store");
    let room_id = MatrixRoomId::parse("!observer:example.test").expect("room id");
    store
        .bind_room(&RoomBindingDraft {
            room_id: room_id.clone(),
            agent_user_id: codex_hepta_matrix_store::MatrixUserId::parse("@agent:example.test")
                .expect("user id"),
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await
        .expect("bind room");
    let payload = b"durable observer";
    let logical = outbox_id(&agent_id, &room_id, "thread", "turn", "item", "final");
    let txn_id = transaction_id(&logical, 1).expect("txn id");
    let record = match store
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
        .await
        .expect("enqueue")
    {
        OutboxDisposition::Enqueued(record)
        | OutboxDisposition::Coalesced(record)
        | OutboxDisposition::Duplicate(record) => record,
    };
    let intent = SendIntent {
        operation_id: matrix_dispatch_operation_id(&record.stable_txn_id),
        stable_txn_id: record.stable_txn_id,
        room_id,
        payload_digest: Sha256Digest::for_bytes(payload).as_str().to_string(),
        context: MatrixDispatchContext {
            homeserver_id: Some("https://matrix.example.test".to_string()),
            device_id: Some("DEVICE1".to_string()),
            session_generation: 1,
            binding_revision: 1,
            authority_epoch: Some(7),
            authority_binding_digest: Some("a".repeat(64)),
            grant_id: Some("grant.1".to_string()),
            grant_payload_digest: Some(Sha256Digest::for_bytes(payload).as_str().to_string()),
        },
    };
    (temp, store, intent)
}

#[tokio::test]
async fn facade_has_no_second_state_owner_and_reconciles_durably() {
    let (_temp, store, intent) = fixture().await;
    let claimed = store
        .claim_outbox(10, 20, 1)
        .await
        .expect("claim")
        .remove(0);
    let observer = MatrixSendObserver::new(&store);
    let prepared = observer
        .prepare_send(10, &intent)
        .await
        .expect("prepare durable send");
    assert_eq!(prepared.state, SendState::Prepared);
    store
        .record_matrix_dispatch_attempt(&claimed.stable_txn_id, claimed.attempts, 10)
        .await
        .expect("dispatch attempt");
    let event_id = MatrixEventId::parse("$observed:example.test").expect("event id");
    store
        .record_matrix_transport_acceptance(&claimed.stable_txn_id, claimed.attempts, &event_id, 11)
        .await
        .expect("transport acceptance");
    let terminal = observer
        .observe_send(&ServerObservation {
            transaction_id: claimed.stable_txn_id.clone(),
            server_event_id: event_id.clone(),
            room_id: intent.room_id.clone(),
            binding_revision: 1,
            session_generation: 1,
            observation_digest: "b".repeat(64),
            observed_at_ms: 12,
        })
        .await
        .expect("observe")
        .expect("matched dispatch");
    assert_eq!(terminal.state, SendState::ObservedSucceeded);
    assert!(terminal.archived);
    assert_eq!(
        observer
            .receipt(&claimed.stable_txn_id)
            .await
            .expect("receipt")
            .expect("stored")
            .state,
        SendState::ObservedSucceeded
    );
}

#[tokio::test]
async fn redaction_keeps_send_evidence_separate() {
    let (_temp, store, intent) = fixture().await;
    let claimed = store
        .claim_outbox(10, 20, 1)
        .await
        .expect("claim")
        .remove(0);
    let observer = MatrixSendObserver::new(&store);
    observer.prepare_send(10, &intent).await.expect("prepare");
    store
        .record_matrix_dispatch_attempt(&claimed.stable_txn_id, claimed.attempts, 10)
        .await
        .expect("attempt");
    let event_id = MatrixEventId::parse("$observed:example.test").expect("event id");
    store
        .record_matrix_transport_acceptance(&claimed.stable_txn_id, claimed.attempts, &event_id, 11)
        .await
        .expect("accepted");
    observer
        .observe_send(&ServerObservation {
            transaction_id: claimed.stable_txn_id.clone(),
            server_event_id: event_id.clone(),
            room_id: intent.room_id.clone(),
            binding_revision: 1,
            session_generation: 1,
            observation_digest: "b".repeat(64),
            observed_at_ms: 12,
        })
        .await
        .expect("observe");
    let redaction_event = MatrixEventId::parse("$redact:example.test").expect("redaction id");
    let redacted = observer
        .apply_redaction(&event_id, &redaction_event, &"c".repeat(64), 13)
        .await
        .expect("redaction")
        .expect("matched dispatch");
    assert_eq!(redacted.state, SendState::Redacted);
    assert_eq!(redacted.send_observation_digest, Some("b".repeat(64)));
    assert_eq!(redacted.redaction_observation_digest, Some("c".repeat(64)));
}
