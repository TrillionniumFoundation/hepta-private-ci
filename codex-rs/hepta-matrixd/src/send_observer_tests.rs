use std::error::Error as StdError;
use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixTransactionId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

use super::*;

type TestResult<T = ()> = Result<T, Box<dyn StdError>>;
const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

struct Fixture {
    temp: TempDir,
    layout: HeptaAgentLayout,
    store: MatrixDurableStore,
    observer: MatrixSendObserver,
    txn_id: MatrixTransactionId,
    payload_digest: String,
}

async fn fixture() -> TestResult<Fixture> {
    let temp = TempDir::new()?;
    let agent = AgentId::parse(AGENT)?;
    let fleet_root = temp.path().join("fleet");
    fs::create_dir_all(&fleet_root)?;
    let root = HeptaFleetRoot::parse(fleet_root.canonicalize()?)?;
    let layout = root.layout().agent(&agent);
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let room = MatrixRoomId::parse("!room:example.org")?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room.clone(),
            agent_user_id: MatrixUserId::parse("@agent:example.org")?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 10,
        })
        .await?;
    let payload = b"{\"msgtype\":\"m.text\",\"body\":\"hello\"}".to_vec();
    let payload_digest = Sha256Digest::for_bytes(&payload).as_str().to_string();
    let logical = "observer.test.send";
    let txn_id = transaction_id(logical, 1)?;
    store
        .enqueue_outbox(&OutboxDraft {
            logical_outbox_id: logical.to_string(),
            revision: 1,
            txn_id: txn_id.clone(),
            room_id: room,
            kind: OutboxKind::Final,
            payload,
            binding_revision: 1,
            generation: 1,
            created_at_ms: 10,
        })
        .await?;
    let observer = MatrixSendObserver::new(store.clone());
    Ok(Fixture {
        temp,
        layout,
        store,
        observer,
        txn_id,
        payload_digest,
    })
}

fn intent(fixture: &Fixture) -> SendIntent {
    SendIntent {
        operation_id: "operation.1".to_string(),
        transaction_id: fixture.txn_id.as_str().to_string(),
        homeserver_id: "homeserver.1".to_string(),
        room_id: "!room:example.org".to_string(),
        device_id: "device.1".to_string(),
        session_generation: 1,
        authority_epoch: 7,
        payload_digest: fixture.payload_digest.clone(),
        grant_payload_digest: fixture.payload_digest.clone(),
        deadline_ms: 10_000,
    }
}

fn successful_observation(fixture: &Fixture, digest: char, at_ms: u64) -> ServerObservation {
    ServerObservation {
        operation_id: "operation.1".to_string(),
        transaction_id: fixture.txn_id.as_str().to_string(),
        homeserver_id: "homeserver.1".to_string(),
        room_id: "!room:example.org".to_string(),
        session_generation: 1,
        terminal_observed: true,
        accepted: true,
        server_event_id: Some("$event:example.org".to_string()),
        observation_digest: digest.to_string().repeat(64),
        observed_at_ms: at_ms,
    }
}

#[tokio::test]
async fn lost_ack_keeps_transaction_and_reconciles_to_server_event() -> TestResult {
    let fixture = fixture().await?;
    fixture
        .observer
        .prepare_send(100, intent(&fixture))
        .await?;
    let claimed = fixture.store.claim_outbox(101, 30, 1).await?;
    assert_eq!(claimed.len(), 1);
    let pending = fixture
        .observer
        .observe_send(ServerObservation {
            terminal_observed: false,
            accepted: false,
            server_event_id: None,
            observation_digest: "2".repeat(64),
            observed_at_ms: 102,
            ..successful_observation(&fixture, '3', 103)
        })
        .await?;
    assert_eq!(pending.state, SendState::Indeterminate);
    let terminal = fixture
        .observer
        .observe_send(successful_observation(&fixture, '3', 103))
        .await?;
    assert_eq!(terminal.state, SendState::Succeeded);
    assert_eq!(terminal.transaction_id, fixture.txn_id.as_str());
    Ok(())
}

#[tokio::test]
async fn payload_drift_and_operation_reuse_are_rejected() -> TestResult {
    let fixture = fixture().await?;
    let mut changed = intent(&fixture);
    changed.grant_payload_digest = "2".repeat(64);
    assert_eq!(
        fixture.observer.prepare_send(100, changed).await,
        Err(Error::PayloadMismatch)
    );
    fixture
        .observer
        .prepare_send(100, intent(&fixture))
        .await?;
    let mut changed = intent(&fixture);
    changed.operation_id = "operation.2".to_string();
    assert_eq!(
        fixture.observer.prepare_send(100, changed).await,
        Err(Error::OperationConflict)
    );
    Ok(())
}

#[tokio::test]
async fn terminal_success_survives_reopen_and_redaction_keeps_original_evidence() -> TestResult {
    let fixture = fixture().await?;
    let success_digest = "3".repeat(64);
    let redaction_digest = "4".repeat(64);
    fixture
        .observer
        .prepare_send(100, intent(&fixture))
        .await?;
    fixture.store.claim_outbox(101, 30, 1).await?;
    let success = fixture
        .observer
        .observe_send(successful_observation(&fixture, '3', 102))
        .await?;
    assert_eq!(success.state, SendState::Succeeded);
    assert_eq!(
        success.send_observation_digest.as_deref(),
        Some(success_digest.as_str())
    );
    assert_eq!(success.redaction_observation_digest, None);

    let redacted = fixture
        .observer
        .apply_redaction("$event:example.org", &redaction_digest, 103)
        .await?;
    assert_eq!(redacted.state, SendState::Redacted);
    assert_eq!(
        redacted.send_observation_digest.as_deref(),
        Some(success_digest.as_str())
    );
    assert_eq!(
        redacted.redaction_observation_digest.as_deref(),
        Some(redaction_digest.as_str())
    );

    fixture.store.close().await;
    let reopened =
        MatrixDurableStore::open(&fixture.layout, MatrixDurableConfig::default()).await?;
    let durable = reopened
        .dispatch_record(&fixture.txn_id)
        .await?
        .ok_or("dispatch disappeared after reopen")?;
    assert_eq!(durable.state, MatrixDispatchState::Redacted);
    assert_eq!(
        durable.send_observation_digest.as_deref(),
        Some(success_digest.as_str())
    );
    assert_eq!(
        durable.redaction_observation_digest.as_deref(),
        Some(redaction_digest.as_str())
    );
    let observations = reopened
        .dispatch_observations(&fixture.txn_id, 16)
        .await?;
    assert!(observations.len() >= 2);
    reopened.close().await;
    drop(fixture.temp);
    Ok(())
}

#[tokio::test]
async fn terminal_state_cannot_be_reopened_by_contradictory_observation() -> TestResult {
    let fixture = fixture().await?;
    fixture
        .observer
        .prepare_send(100, intent(&fixture))
        .await?;
    fixture.store.claim_outbox(101, 30, 1).await?;
    let terminal = fixture
        .observer
        .observe_send(successful_observation(&fixture, '3', 102))
        .await?;
    let failed = ServerObservation {
        accepted: false,
        server_event_id: None,
        observation_digest: "5".repeat(64),
        observed_at_ms: 103,
        ..successful_observation(&fixture, '3', 102)
    };
    assert_eq!(
        fixture.observer.observe_send(failed).await,
        Err(Error::OperationConflict)
    );
    let durable = fixture
        .observer
        .receipt("operation.1")
        .await?
        .ok_or("receipt missing")?;
    assert_eq!(durable, terminal);
    Ok(())
}
