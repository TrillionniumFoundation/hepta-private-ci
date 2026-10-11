use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn request() -> InferenceRequest {
    InferenceRequest {
        request_id: id("request:1"),
        model_digest: Digest32::of_bytes(b"model"),
        prompt_digest: Digest32::of_bytes(b"prompt"),
        maximum_tokens: 128,
        deadline_ms: 2_000,
    }
}

fn ledger() -> InferenceLedger {
    let Ok(value) = InferenceLedger::new(8) else {
        panic!("test ledger must initialize");
    };
    value
}

#[test]
fn request_lifecycle_is_fenced_and_authority_free() {
    let mut value = ledger();
    let request = request();
    let digest = request_digest(&request);
    assert!(value.submit(request).is_ok());
    assert!(
        value
            .reserve(&id("request:1"), digest, id("reservation:1"))
            .is_ok()
    );
    let Ok(receipt) = value.complete(&id("request:1"), Digest32::of_bytes(b"terminal-receipt"))
    else {
        panic!("completion must succeed");
    };
    assert_eq!(receipt.status, RequestStatus::Completed);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn conflicting_identity_is_rejected() {
    let mut value = ledger();
    assert!(value.submit(request()).is_ok());
    let mut drifted = request();
    drifted.prompt_digest = Digest32::of_bytes(b"other");
    assert_eq!(
        value.submit(drifted),
        Err(Error::RequestConflict("request:1".to_string()))
    );
}

#[test]
fn stale_digest_cannot_reserve() {
    let mut value = ledger();
    assert!(value.submit(request()).is_ok());
    assert_eq!(
        value.reserve(
            &id("request:1"),
            Digest32::of_bytes(b"stale"),
            id("reservation:1")
        ),
        Err(Error::DigestMismatch)
    );
}

#[test]
fn completion_requires_reservation() {
    let mut value = ledger();
    assert!(value.submit(request()).is_ok());
    assert_eq!(
        value.complete(&id("request:1"), Digest32::of_bytes(b"terminal-receipt")),
        Err(Error::InvalidTransition)
    );
}
