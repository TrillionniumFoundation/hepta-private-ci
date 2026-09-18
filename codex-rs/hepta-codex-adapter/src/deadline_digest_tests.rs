use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn intent(deadline_ms: u64) -> CodexOperationIntent {
    CodexOperationIntent {
        operation_id: id("operation:deadline"),
        thread_id: id("thread:deadline"),
        turn_id: Some(id("turn:deadline")),
        method_id: id("turn:start"),
        protocol_version: id(APP_SERVER_V2_PROTOCOL_ID),
        session_generation: 9,
        payload_digest: digest(b"payload"),
        lease_payload_digest: digest(b"payload"),
        deadline_ms,
    }
}

fn must_adapt(intent: CodexOperationIntent) -> CodexAdapterReceipt {
    let Ok(receipt) = adapt(/*now_ms*/ 1_000, intent, /*observation*/ None) else {
        panic!("valid request adaptation must succeed");
    };
    receipt
}

#[test]
fn deadline_is_bound_into_the_codex_request_digest() {
    let earlier = must_adapt(intent(/*deadline_ms*/ 2_000));
    let later = must_adapt(intent(/*deadline_ms*/ 3_000));

    assert_ne!(earlier.request_digest, later.request_digest);
}

#[test]
fn thread_turn_protocol_and_generation_are_bound_into_request_digest() {
    let base = intent(2_000);
    let base_digest = request_digest(&base);

    let mut changed = base.clone();
    changed.thread_id = id("thread:other");
    assert_ne!(base_digest, request_digest(&changed));

    let mut changed = base.clone();
    changed.turn_id = Some(id("turn:other"));
    assert_ne!(base_digest, request_digest(&changed));

    let mut changed = base.clone();
    changed.protocol_version = id("codex.app-server.v3");
    assert_ne!(base_digest, request_digest(&changed));

    let mut changed = base;
    changed.session_generation = 10;
    assert_ne!(base_digest, request_digest(&changed));
}

#[test]
fn an_exact_retry_keeps_the_adapter_receipt_stable() {
    assert_eq!(
        must_adapt(intent(/*deadline_ms*/ 2_000)),
        must_adapt(intent(/*deadline_ms*/ 2_000))
    );
}

#[test]
fn the_deadline_remains_exclusive() {
    assert_eq!(
        validate_for_dispatch(
            /*now_ms*/ 2_000,
            &intent(/*deadline_ms*/ 2_000)
        ),
        Err(Error::DeadlineExpired)
    );
}

#[test]
fn zero_generation_is_rejected() {
    let mut value = intent(2_000);
    value.session_generation = 0;
    assert_eq!(adapt(1_000, value, None), Err(Error::InvalidGeneration));
}

#[test]
fn terminal_reconciliation_survives_the_original_deadline() {
    use codex_app_server_protocol::Turn;
    use codex_app_server_protocol::TurnCompletedNotification;
    use codex_app_server_protocol::TurnItemsView;

    let value = intent(/*deadline_ms*/ 2_000);
    let notification = TurnCompletedNotification {
        thread_id: value.thread_id.to_string(),
        turn: Turn {
            id: value.turn_id.as_ref().expect("turn").to_string(),
            items: Vec::new(),
            items_view: TurnItemsView::Full,
            status: TurnStatus::Completed,
            error: None,
            started_at: None,
            completed_at: None,
            duration_ms: None,
        },
    };
    let observation = AppServerObservation::from_turn_completed(
        value.protocol_version.clone(),
        value.session_generation,
        1,
        &notification,
    )
    .expect("valid terminal observation");
    let receipt = adapt(/*now_ms after deadline*/ 3_000, value, Some(observation))
        .expect("late terminal fact must remain recordable");
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
}
