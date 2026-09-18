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
        session_id: id("session:deadline"),
        thread_id: id("thread:deadline"),
        method_id: id(TURN_START_METHOD_ID),
        payload_digest: digest(b"payload"),
        lease_payload_digest: digest(b"payload"),
        owner_generation: 11,
        protocol_version: APP_SERVER_PROTOCOL_V2,
        deadline_ms,
    }
}

fn must_adapt(intent: CodexOperationIntent) -> CodexAdapterReceipt {
    adapt(/*now_ms*/ 1_000, intent, /*observation*/ None).unwrap()
}

#[test]
fn deadline_is_bound_into_the_codex_request_digest() {
    let earlier = must_adapt(intent(/*deadline_ms*/ 2_000));
    let later = must_adapt(intent(/*deadline_ms*/ 3_000));
    assert_ne!(earlier.request_digest, later.request_digest);
}

#[test]
fn session_generation_and_protocol_are_bound_into_the_request_digest() {
    let baseline = must_adapt(intent(2_000)).request_digest;

    let mut changed_session = intent(2_000);
    changed_session.session_id = id("session:other");
    assert_ne!(baseline, must_adapt(changed_session).request_digest);

    let mut changed_generation = intent(2_000);
    changed_generation.owner_generation += 1;
    assert_ne!(baseline, must_adapt(changed_generation).request_digest);

    let mut changed_protocol = intent(2_000);
    changed_protocol.protocol_version = 3;
    assert_eq!(
        adapt(1_000, changed_protocol, None),
        Err(Error::UnsupportedProtocol(3))
    );
}

#[test]
fn an_exact_retry_keeps_the_adapter_receipt_stable() {
    assert_eq!(
        must_adapt(intent(/*deadline_ms*/ 2_000)),
        must_adapt(intent(/*deadline_ms*/ 2_000))
    );
}

#[test]
fn deadline_expiry_is_a_typed_unknown_outcome_not_a_fake_rejection() {
    let receipt = adapt(
        /*now_ms*/ 2_000,
        intent(/*deadline_ms*/ 2_000),
        /*observation*/ None,
    )
    .unwrap();
    assert_eq!(receipt.status, AdapterStatus::TimedOut);
    assert_eq!(receipt.replay, ReplayDisposition::ReconcileOnly);
}
