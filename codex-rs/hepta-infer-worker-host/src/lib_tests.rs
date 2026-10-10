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

fn fixture() -> (InferenceRequest, AuthorityLease, Reservation) {
    let request = InferenceRequest {
        request_id: id("request:1"),
        reservation_id: id("reservation:1"),
        model_digest: digest(b"model"),
        prompt_digest: digest(b"prompt"),
        maximum_tokens: 128,
        deadline_ms: 2_000,
    };
    let lease = AuthorityLease {
        lease_id: id("lease:1"),
        request_id: request.request_id.clone(),
        model_digest: request.model_digest,
        payload_digest: request_digest(&request),
        expires_at_ms: 1_500,
        revoked: false,
    };
    let reservation = Reservation {
        reservation_id: request.reservation_id.clone(),
        request_id: request.request_id.clone(),
        model_digest: request.model_digest,
        maximum_tokens: request.maximum_tokens,
        valid_until_ms: 1_500,
        cancelled: false,
    };
    (request, lease, reservation)
}

#[test]
fn terminal_success_requires_exact_authority_binding() {
    let (request, lease, reservation) = fixture();
    let observation = ExecutionObservation {
        output_digest: digest(b"output"),
        consumed_tokens: 64,
        terminal_observed: true,
    };
    let Ok(receipt) = execute(1_000, request, lease, reservation, Some(observation)) else {
        panic!("exact binding must succeed");
    };
    assert_eq!(receipt.status, TerminalStatus::Succeeded);
    assert_eq!(receipt.output_digest, Some(digest(b"output")));
    assert!(!receipt.authority.grants_any());
}

#[test]
fn revoked_lease_is_rejected() {
    let (request, mut lease, reservation) = fixture();
    lease.revoked = true;
    assert_eq!(
        execute(1_000, request, lease, reservation, None),
        Err(Error::LeaseRevoked)
    );
}

#[test]
fn payload_drift_is_rejected() {
    let (mut request, lease, reservation) = fixture();
    request.prompt_digest = digest(b"drifted-prompt");
    assert_eq!(
        execute(1_000, request, lease, reservation, None),
        Err(Error::PayloadMismatch)
    );
}

#[test]
fn unobserved_terminal_state_is_indeterminate() {
    let (request, lease, reservation) = fixture();
    let observation = ExecutionObservation {
        output_digest: digest(b"provisional-output"),
        consumed_tokens: 32,
        terminal_observed: false,
    };
    let Ok(receipt) = execute(1_000, request, lease, reservation, Some(observation)) else {
        panic!("unobserved state must map to an indeterminate receipt");
    };
    assert_eq!(receipt.status, TerminalStatus::Indeterminate);
    assert_eq!(receipt.output_digest, None);
}

#[test]
fn timeout_never_becomes_success() {
    let (request, lease, reservation) = fixture();
    assert_eq!(
        execute(2_000, request, lease, reservation, None),
        Err(Error::RequestExpired)
    );
}

#[test]
fn token_limit_is_enforced() {
    let (request, lease, reservation) = fixture();
    let observation = ExecutionObservation {
        output_digest: digest(b"output"),
        consumed_tokens: 129,
        terminal_observed: true,
    };
    assert_eq!(
        execute(1_000, request, lease, reservation, Some(observation)),
        Err(Error::TokenLimitExceeded)
    );
}
