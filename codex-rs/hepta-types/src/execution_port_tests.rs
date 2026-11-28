use super::*;

fn intent<'a>(operation_id: &'a StableId) -> ExecutionPortIntentV1<'a> {
    let payload = Digest32::of_bytes(b"actual-turn-payload");
    ExecutionPortIntentV1 {
        operation_id,
        source_admission_digest: Digest32::of_bytes(b"durably-admitted-source"),
        generation: Generation::new(7).unwrap(),
        payload_digest: payload,
        lease_payload_digest: payload,
        deadline_ms: 1_000,
    }
}

#[test]
fn borrowed_intent_is_valid_with_an_exclusive_deadline() {
    let id = StableId::new("operation:one").unwrap();
    let port = intent(&id);
    assert_eq!(port.validate(999), Ok(()));
    assert_eq!(
        port.validate(1_000),
        Err(ExecutionPortIntentErrorV1::DeadlineExpired)
    );
    assert_eq!(
        port.validate(1_001),
        Err(ExecutionPortIntentErrorV1::DeadlineExpired)
    );
}

#[test]
fn invalid_or_unbound_intents_fail_closed() {
    let id = StableId::new("operation:two").unwrap();

    let mut port = intent(&id);
    port.source_admission_digest = Digest32::ZERO;
    assert_eq!(
        port.validate(1),
        Err(ExecutionPortIntentErrorV1::EmptyDigest("source admission"))
    );

    let mut port = intent(&id);
    port.payload_digest = Digest32::ZERO;
    assert_eq!(
        port.validate(1),
        Err(ExecutionPortIntentErrorV1::EmptyDigest("payload"))
    );

    let mut port = intent(&id);
    port.lease_payload_digest = Digest32::ZERO;
    assert_eq!(
        port.validate(1),
        Err(ExecutionPortIntentErrorV1::EmptyDigest("payload"))
    );

    let mut port = intent(&id);
    port.lease_payload_digest = Digest32::of_bytes(b"unrelated-lease-payload");
    assert_eq!(
        port.validate(1),
        Err(ExecutionPortIntentErrorV1::PayloadBindingMismatch)
    );

    let mut port = intent(&id);
    port.deadline_ms = 0;
    assert_eq!(
        port.validate(0),
        Err(ExecutionPortIntentErrorV1::DeadlineExpired)
    );
}
