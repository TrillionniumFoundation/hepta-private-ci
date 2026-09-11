use super::*;

fn intent() -> SendIntent {
    SendIntent {
        operation_id: "operation.1".to_string(),
        transaction_id: "transaction.1".to_string(),
        homeserver_id: "homeserver.1".to_string(),
        room_id: "!room:example.org".to_string(),
        device_id: "device.1".to_string(),
        session_generation: 3,
        authority_epoch: 7,
        payload_digest: "1".repeat(64),
        grant_payload_digest: "1".repeat(64),
        deadline_ms: 10_000,
    }
}

#[test]
fn lost_ack_keeps_transaction_and_reconciles_to_server_event() {
    let mut observer = MatrixSendObserver::default();
    observer.prepare_send(100, intent()).expect("prepare");
    let pending = observer
        .observe_send(ServerObservation {
            operation_id: "operation.1".to_string(),
            transaction_id: "transaction.1".to_string(),
            homeserver_id: "homeserver.1".to_string(),
            room_id: "!room:example.org".to_string(),
            session_generation: 3,
            terminal_observed: false,
            accepted: false,
            server_event_id: None,
            observation_digest: "2".repeat(64),
        })
        .expect("unknown");
    assert_eq!(pending.state, SendState::Indeterminate);
    let terminal = observer
        .observe_send(ServerObservation {
            operation_id: "operation.1".to_string(),
            transaction_id: "transaction.1".to_string(),
            homeserver_id: "homeserver.1".to_string(),
            room_id: "!room:example.org".to_string(),
            session_generation: 3,
            terminal_observed: true,
            accepted: true,
            server_event_id: Some("$event:example.org".to_string()),
            observation_digest: "3".repeat(64),
        })
        .expect("terminal");
    assert_eq!(terminal.state, SendState::Succeeded);
    assert_eq!(terminal.transaction_id, "transaction.1");
}

#[test]
fn payload_drift_and_transaction_reuse_are_rejected() {
    let mut observer = MatrixSendObserver::default();
    let mut changed = intent();
    changed.grant_payload_digest = "2".repeat(64);
    assert_eq!(
        observer.prepare_send(100, changed),
        Err(Error::PayloadMismatch)
    );
    observer.prepare_send(100, intent()).expect("prepare");
    let mut duplicate = intent();
    duplicate.operation_id = "operation.2".to_string();
    assert_eq!(
        observer.prepare_send(100, duplicate),
        Err(Error::OperationConflict)
    );
}
