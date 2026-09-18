use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier must be valid")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn intent(deadline_ms: u64) -> CodexOperationIntent {
    let params = TurnStartParams {
        thread_id: "thread:deadline".to_string(),
        client_user_message_id: Some("client:deadline".to_string()),
        input: Vec::new(),
        ..Default::default()
    };
    let payload_digest = turn_start_payload_digest(&params);
    CodexOperationIntent {
        operation_id: id("operation:deadline"),
        subject_id: id("agent:deadline"),
        destination_id: id("agent:deadline/app-server:9"),
        thread_id: id("thread:deadline"),
        client_message_id: id("client:deadline"),
        method_id: id("turn/start"),
        payload_digest,
        lease_payload_digest: payload_digest,
        scope_digest: digest(b"scope"),
        authority_epoch: 4,
        session_generation: 9,
        protocol_version: 2,
        deadline_ms,
    }
}

fn dispatched(intent: CodexOperationIntent) -> DispatchedCodexOperation {
    DispatchedCodexOperation {
        intent,
        turn_id: id("turn:deadline"),
    }
}

fn must_adapt(intent: CodexOperationIntent) -> CodexAdapterReceipt {
    adapt_observation(1_000, &dispatched(intent), None)
        .expect("valid request adaptation must succeed")
}

#[test]
fn deadline_is_bound_into_the_codex_request_digest() {
    let earlier = must_adapt(intent(2_000));
    let later = must_adapt(intent(3_000));
    assert_ne!(earlier.request_digest, later.request_digest);
}

#[test]
fn authority_session_protocol_and_client_identity_are_bound_into_request_digest() {
    let base = intent(2_000);

    let mut changed_client = base.clone();
    changed_client.client_message_id = id("client:other");
    assert_ne!(
        must_adapt(base.clone()).request_digest,
        must_adapt(changed_client).request_digest
    );

    let mut changed_authority = base.clone();
    changed_authority.authority_epoch += 1;
    assert_ne!(
        must_adapt(base.clone()).request_digest,
        must_adapt(changed_authority).request_digest
    );

    let mut changed_generation = base.clone();
    changed_generation.session_generation += 1;
    assert_ne!(
        must_adapt(base.clone()).request_digest,
        must_adapt(changed_generation).request_digest
    );

    let mut changed_protocol = base.clone();
    changed_protocol.protocol_version += 1;
    assert_ne!(
        must_adapt(base).request_digest,
        must_adapt(changed_protocol).request_digest
    );
}

#[test]
fn an_exact_retry_keeps_the_adapter_receipt_stable() {
    assert_eq!(
        must_adapt(intent(2_000)),
        must_adapt(intent(2_000))
    );
}

#[test]
fn the_deadline_remains_exclusive() {
    let value = dispatched(intent(2_000));
    assert_eq!(
        adapt_observation(2_000, &value, None),
        Err(Error::DeadlineExpired)
    );
}
