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
        turn_id: id("turn:deadline"),
        method_id: id("method:deadline"),
        protocol_version: 2,
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
fn turn_and_protocol_are_bound_into_the_codex_request_digest() {
    let baseline = must_adapt(intent(2_000));

    let mut changed_turn = intent(2_000);
    changed_turn.turn_id = id("turn:other");
    assert_ne!(baseline.request_digest, must_adapt(changed_turn).request_digest);

    let mut changed_protocol = intent(2_000);
    changed_protocol.protocol_version = 3;
    assert_ne!(
        baseline.request_digest,
        must_adapt(changed_protocol).request_digest
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

#[test]
fn protocol_version_zero_is_rejected() {
    let mut value = intent(2_000);
    value.protocol_version = 0;
    assert_eq!(adapt(1_000, value, None), Err(Error::InvalidProtocolVersion));
}
