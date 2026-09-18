use std::error::Error as StdError;
use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixServerEventObservation;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

use super::*;

type TestResult<T = ()> = Result<T, Box<dyn StdError>>;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

struct Fixture {
    _temp: TempDir,
    layout: HeptaAgentLayout,
    store: MatrixDurableStore,
    observer: MatrixSendObserver,
}

impl Fixture {
    async fn new() -> TestResult<Self> {
        let temp = TempDir::new()?;
        let fleet = temp.path().join("fleet");
        fs::create_dir_all(&fleet)?;
        let fleet = HeptaFleetRoot::parse(fleet.canonicalize()?)?;
        let layout = fleet.layout().agent(&AgentId::parse(AGENT)?);
        let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
        let observer = MatrixSendObserver::new(store.clone());
        Ok(Self {
            _temp: temp,
            layout,
            store,
            observer,
        })
    }
}

fn intent() -> SendIntent {
    SendIntent {
        operation_id: "operation.1".to_string(),
        transaction_id: "transaction.1".to_string(),
        homeserver_id: "https://homeserver.example".to_string(),
        room_id: "!room:example.org".to_string(),
        device_id: "device.1".to_string(),
        session_generation: 3,
        authority_identity: "a".repeat(64),
        authority_epoch: 7,
        payload_digest: "1".repeat(64),
        grant_payload_digest: "1".repeat(64),
        deadline_ms: 10_000,
    }
}

fn successful_observation() -> ServerObservation {
    ServerObservation {
        operation_id: "operation.1".to_string(),
        transaction_id: "transaction.1".to_string(),
        homeserver_id: "https://homeserver.example".to_string(),
        room_id: "!room:example.org".to_string(),
        session_generation: 3,
        terminal_observed: true,
        accepted: true,
        server_event_id: Some("$event:example.org".to_string()),
        observation_digest: "3".repeat(64),
        observed_at_ms: 300,
    }
}

#[tokio::test]
async fn lost_ack_survives_reopen_and_reconciles_to_server_event() -> TestResult {
    let fixture = Fixture::new().await?;
    fixture
        .observer
        .prepare_send(100, intent())
        .await
        .expect("prepare");
    let pending = fixture
        .observer
        .observe_send(ServerObservation {
            terminal_observed: false,
            accepted: false,
            server_event_id: None,
            observation_digest: "2".repeat(64),
            observed_at_ms: 200,
            ..successful_observation()
        })
        .await
        .expect("unknown");
    assert_eq!(pending.state, SendState::Indeterminate);

    fixture.store.close().await;
    let reopened =
        MatrixDurableStore::open(&fixture.layout, MatrixDurableConfig::default()).await?;
    let observer = MatrixSendObserver::new(reopened.clone());
    let terminal = observer
        .observe_send(successful_observation())
        .await
        .expect("terminal");
    assert_eq!(terminal.state, SendState::Succeeded);
    assert_eq!(terminal.transaction_id, "transaction.1");
    assert_eq!(terminal.send_observation_digest, Some("3".repeat(64)));
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn payload_drift_and_transaction_reuse_are_rejected() -> TestResult {
    let fixture = Fixture::new().await?;
    let mut changed = intent();
    changed.grant_payload_digest = "2".repeat(64);
    assert_eq!(
        fixture.observer.prepare_send(100, changed).await,
        Err(Error::PayloadMismatch)
    );
    fixture.observer.prepare_send(100, intent()).await?;
    let mut duplicate = intent();
    duplicate.operation_id = "operation.2".to_string();
    assert_eq!(
        fixture.observer.prepare_send(100, duplicate).await,
        Err(Error::OperationConflict)
    );
    fixture.store.close().await;
    Ok(())
}

#[tokio::test]
async fn transport_acceptance_is_not_terminal_until_server_event_is_observed() -> TestResult {
    let fixture = Fixture::new().await?;
    fixture.observer.prepare_send(100, intent()).await?;
    let event_id = MatrixEventId::parse("$event:example.org")?;
    let accepted = fixture
        .store
        .record_transport_accepted(
            "operation.1",
            &event_id,
            &"2".repeat(64),
            200,
        )
        .await?;
    assert_eq!(accepted.state, SendState::Accepted);
    assert!(!accepted.terminal_observed);

    fixture
        .store
        .observe_server_event(&MatrixServerEventObservation {
            event_id: event_id.clone(),
            transaction_id: None,
            room_id: codex_hepta_matrix_protocol::MatrixRoomId::parse("!room:example.org")?,
            session_generation: 3,
            observation_digest: "3".repeat(64),
            observed_at_ms: 300,
        })
        .await?;
    let terminal = fixture
        .observer
        .receipt("operation.1")
        .await?
        .ok_or("receipt disappeared")?;
    assert_eq!(terminal.state, SendState::Succeeded);
    assert_eq!(terminal.server_event_id.as_deref(), Some(event_id.as_str()));
    fixture.store.close().await;
    Ok(())
}

#[tokio::test]
async fn failed_send_is_terminal_and_only_identical_replay_is_idempotent() -> TestResult {
    let fixture = Fixture::new().await?;
    fixture.observer.prepare_send(100, intent()).await?;
    let failed = ServerObservation {
        accepted: false,
        server_event_id: None,
        ..successful_observation()
    };
    let terminal = fixture.observer.observe_send(failed.clone()).await?;
    assert_eq!(terminal.state, SendState::Failed);
    let mut replay = terminal.clone();
    replay.idempotent = true;
    assert_eq!(fixture.observer.observe_send(failed.clone()).await, Ok(replay));

    for observation in [
        successful_observation(),
        ServerObservation {
            terminal_observed: false,
            ..failed
        },
    ] {
        assert_eq!(
            fixture.observer.observe_send(observation).await,
            Err(Error::AlreadyTerminal)
        );
        assert_eq!(
            fixture.observer.receipt("operation.1").await?,
            Some(terminal.clone())
        );
    }
    fixture.store.close().await;
    Ok(())
}

#[tokio::test]
async fn successful_send_replay_binds_event_and_terminal_observation() -> TestResult {
    let fixture = Fixture::new().await?;
    fixture.observer.prepare_send(100, intent()).await?;
    let observation = successful_observation();
    let terminal = fixture.observer.observe_send(observation.clone()).await?;
    let mut replay = terminal.clone();
    replay.idempotent = true;
    assert_eq!(
        fixture.observer.observe_send(observation.clone()).await,
        Ok(replay)
    );

    for changed in [
        ServerObservation {
            accepted: false,
            server_event_id: None,
            ..observation.clone()
        },
        ServerObservation {
            server_event_id: Some("$different:example.org".to_string()),
            ..observation.clone()
        },
        ServerObservation {
            terminal_observed: false,
            ..observation.clone()
        },
        ServerObservation {
            observation_digest: "4".repeat(64),
            ..observation
        },
    ] {
        assert_eq!(
            fixture.observer.observe_send(changed).await,
            Err(Error::AlreadyTerminal)
        );
    }
    fixture.store.close().await;
    Ok(())
}

#[tokio::test]
async fn redaction_preserves_original_send_evidence_and_is_immutable() -> TestResult {
    let fixture = Fixture::new().await?;
    fixture.observer.prepare_send(100, intent()).await?;
    fixture
        .observer
        .observe_send(successful_observation())
        .await?;
    let digest = "4".repeat(64);
    let redacted = fixture
        .observer
        .apply_redaction("$event:example.org", &digest, 400)
        .await?;
    assert_eq!(redacted.state, SendState::Redacted);
    assert_eq!(redacted.send_observation_digest, Some("3".repeat(64)));
    assert_eq!(redacted.redaction_observation_digest, Some(digest.clone()));

    let mut replay = redacted.clone();
    replay.idempotent = true;
    assert_eq!(
        fixture
            .observer
            .apply_redaction("$event:example.org", &digest, 500)
            .await,
        Ok(replay)
    );
    assert_eq!(
        fixture
            .observer
            .apply_redaction("$event:example.org", &"5".repeat(64), 500)
            .await,
        Err(Error::OperationConflict)
    );
    assert_eq!(fixture.store.unresolved_send_count().await?, 0);
    fixture.store.close().await;
    Ok(())
}

#[tokio::test]
async fn terminal_history_does_not_consume_unresolved_capacity() -> TestResult {
    let fixture = Fixture::new().await?;
    fixture.observer.prepare_send(100, intent()).await?;
    fixture
        .observer
        .observe_send(successful_observation())
        .await?;
    assert_eq!(fixture.store.unresolved_send_count().await?, 0);

    let mut next = intent();
    next.operation_id = "operation.2".to_string();
    next.transaction_id = "transaction.2".to_string();
    let prepared = fixture.observer.prepare_send(500, next).await?;
    assert_eq!(prepared.state, SendState::Prepared);
    assert_eq!(fixture.store.unresolved_send_count().await?, 1);
    fixture.store.close().await;
    Ok(())
}
