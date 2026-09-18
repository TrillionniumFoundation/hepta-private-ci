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
        expected_turn_id: None,
        method_id: id("method:deadline"),
        payload_digest: digest(b"payload"),
        lease_payload_digest: digest(b"payload"),
        connection_digest: digest(b"connection"),
        session_generation: 11,
        protocol_version: 2,
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
fn transport_session_and_protocol_are_bound_into_request_digest() {
    let base = must_adapt(intent(2_000));

    let mut other_connection = intent(2_000);
    other_connection.connection_digest = digest(b"other-connection");
    assert_ne!(
        base.request_digest,
        must_adapt(other_connection).request_digest
    );

    let mut other_generation = intent(2_000);
    other_generation.session_generation = 12;
    assert_ne!(
        base.request_digest,
        must_adapt(other_generation).request_digest
    );

    let mut other_protocol = intent(2_000);
    other_protocol.protocol_version = 3;
    assert_ne!(base.request_digest, must_adapt(other_protocol).request_digest);
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
        adapt(
            /*now_ms*/ 2_000,
            intent(/*deadline_ms*/ 2_000),
            /*observation*/ None
        ),
        Err(Error::DeadlineExpired)
    );
}
