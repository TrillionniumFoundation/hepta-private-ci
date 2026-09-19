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

fn successful_observation() -> ServerObservation {
    ServerObservation {
        operation_id: "operation.1".to_string(),
        transaction_id: "transaction.1".to_string(),
        homeserver_id: "homeserver.1".to_string(),
        room_id: "!room:example.org".to_string(),
        session_generation: 3,
        terminal_observed: true,
        accepted: true,
        server_event_id: Some("$event:example.org".to_string()),
        observation_digest: "3".repeat(64),
    }
}

#[test]
fn failed_send_is_terminal_and_only_identical_replay_is_idempotent() {
    let mut observer = MatrixSendObserver::default();
    observer.prepare_send(100, intent()).expect("prepare");
    let failed = ServerObservation {
        accepted: false,
        server_event_id: None,
        ..successful_observation()
    };
    let terminal = observer.observe_send(failed.clone()).expect("failure");
    assert_eq!(terminal.state, SendState::Failed);
    let mut replay = terminal.clone();
    replay.idempotent = true;
    assert_eq!(observer.observe_send(failed.clone()), Ok(replay));

    let indeterminate = ServerObservation {
        terminal_observed: false,
        ..failed
    };
    for observation in [successful_observation(), indeterminate] {
        assert_eq!(
            observer.observe_send(observation),
            Err(Error::AlreadyTerminal)
        );
        assert_eq!(observer.receipt("operation.1"), Some(&terminal));
    }
}

#[test]
fn successful_send_replay_binds_outcome_event_and_terminal_observation() {
    let mut observer = MatrixSendObserver::default();
    observer.prepare_send(100, intent()).expect("prepare");
    let observation = successful_observation();
    let terminal = observer.observe_send(observation.clone()).expect("success");
    let mut replay = terminal.clone();
    replay.idempotent = true;
    assert_eq!(observer.observe_send(observation.clone()), Ok(replay));

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
        assert_eq!(observer.observe_send(changed), Err(Error::AlreadyTerminal));
        assert_eq!(observer.receipt("operation.1"), Some(&terminal));
    }
}

#[test]
fn redacted_send_cannot_be_resurrected_by_delayed_observations() {
    let mut observer = MatrixSendObserver::default();
    observer.prepare_send(100, intent()).expect("prepare");
    let observation = successful_observation();
    observer.observe_send(observation.clone()).expect("success");
    let redacted = observer
        .apply_redaction("$event:example.org", &"4".repeat(64))
        .expect("redaction");
    assert_eq!(redacted.state, SendState::Redacted);
    assert_eq!(redacted.observation_digest.as_deref(), Some("3333333333333333333333333333333333333333333333333333333333333333"));
    assert_eq!(redacted.redaction_observation_digest.as_deref(), Some("4444444444444444444444444444444444444444444444444444444444444444"));

    for changed in [
        observation.clone(),
        ServerObservation {
            terminal_observed: false,
            accepted: false,
            server_event_id: None,
            ..observation.clone()
        },
        ServerObservation {
            observation_digest: "4".repeat(64),
            ..observation
        },
    ] {
        assert_eq!(observer.observe_send(changed), Err(Error::AlreadyTerminal));
        assert_eq!(observer.receipt("operation.1"), Some(&redacted));
    }
}

#[test]
fn redaction_replay_is_idempotent_without_replacing_original_evidence() {
    let mut observer = MatrixSendObserver::default();
    observer.prepare_send(100, intent()).expect("prepare");
    observer
        .observe_send(successful_observation())
        .expect("success");
    let digest = "4".repeat(64);
    let redacted = observer
        .apply_redaction("$event:example.org", &digest)
        .expect("redaction");
    let mut replay = redacted.clone();
    replay.idempotent = true;
    assert_eq!(
        observer.apply_redaction("$event:example.org", &digest),
        Ok(replay)
    );
    assert_eq!(
        observer.apply_redaction("$event:example.org", &"5".repeat(64)),
        Err(Error::AlreadyTerminal)
    );
    assert_eq!(observer.receipt("operation.1"), Some(&redacted));
}

#[test]
fn terminal_history_does_not_consume_unresolved_capacity() {
    let mut observer = MatrixSendObserver::default();
    for index in 0..MAX_PENDING_SENDS {
        let mut value = intent();
        value.operation_id = format!("operation.{index}");
        value.transaction_id = format!("transaction.{index}");
        observer.prepare_send(100, value).expect("prepare");
        let mut observation = successful_observation();
        observation.operation_id = format!("operation.{index}");
        observation.transaction_id = format!("transaction.{index}");
        observation.server_event_id = Some(format!("$event{index}:example.org"));
        observer.observe_send(observation).expect("terminal");
    }
    let mut next = intent();
    next.operation_id = "operation.after-history".to_string();
    next.transaction_id = "transaction.after-history".to_string();
    observer.prepare_send(100, next).expect("terminal history must not exhaust unresolved capacity");
}
