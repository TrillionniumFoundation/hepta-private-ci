use super::*;

fn id(v: &str) -> StableId {
    StableId::new(v).expect("valid id")
}
fn digest(v: &[u8]) -> Digest32 {
    Digest32::of_bytes(v)
}
fn intent(deadline_ms: u64) -> CodexOperationIntent {
    let payload = digest(b"payload");
    CodexOperationIntent {
        operation_id: id("operation:deadline"),
        thread_id: id("thread:deadline"),
        method_id: id("method:deadline"),
        payload_digest: payload,
        lease_payload_digest: payload,
        deadline_ms,
        app_server_binding: None,
    }
}
#[test]
fn deadline_is_bound_and_exclusive() {
    assert_ne!(
        request_digest(&intent(2_000)),
        request_digest(&intent(3_000))
    );
    assert_eq!(
        adapt_request(2_000, intent(2_000)),
        Err(Error::DeadlineExpired)
    );
}
#[test]
fn exact_request_retry_is_stable() {
    assert_eq!(
        adapt_request(1, intent(2_000)).unwrap(),
        adapt_request(1, intent(2_000)).unwrap()
    );
}
#[test]
fn observed_terminal_evidence_is_not_erased_by_later_wall_clock() {
    let receipt = adapt_observed_event(
        &super::tests::product_intent(),
        &id("turn:test"),
        &super::tests::terminal(codex_app_server_protocol::TurnStatus::Completed),
    )
    .unwrap()
    .unwrap();
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
}
