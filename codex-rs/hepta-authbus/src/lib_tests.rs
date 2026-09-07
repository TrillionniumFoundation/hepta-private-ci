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

fn envelope(sequence: u64) -> AuthEnvelope {
    AuthEnvelope {
        message_id: id(&format!("message:{sequence}")),
        subject_id: id("subject:1"),
        scope_digest: digest(b"scope"),
        payload_digest: digest(b"payload"),
        signature_digest: digest(b"signature"),
        sequence,
        expires_at_ms: 2_000,
        revoked: false,
    }
}

#[test]
fn exact_envelope_is_verified_without_authority_grant() {
    let mut window = ReplayWindow::new(8);
    let Ok(receipt) = window.verify(1_000, envelope(1), digest(b"scope"), digest(b"payload"))
    else {
        panic!("exact envelope must verify");
    };
    assert_eq!(receipt.sequence, 1);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn replay_is_rejected() {
    let mut window = ReplayWindow::new(8);
    assert!(
        window
            .verify(1_000, envelope(1), digest(b"scope"), digest(b"payload"))
            .is_ok()
    );
    assert_eq!(
        window.verify(1_000, envelope(1), digest(b"scope"), digest(b"payload")),
        Err(Error::Replay)
    );
}

#[test]
fn revoked_envelope_is_rejected() {
    let mut value = envelope(1);
    value.revoked = true;
    assert_eq!(
        ReplayWindow::new(8).verify(1_000, value, digest(b"scope"), digest(b"payload")),
        Err(Error::Revoked)
    );
}

#[test]
fn payload_drift_is_rejected() {
    assert_eq!(
        ReplayWindow::new(8).verify(1_000, envelope(1), digest(b"scope"), digest(b"other")),
        Err(Error::PayloadMismatch)
    );
}

#[test]
fn expiration_is_fail_closed() {
    assert_eq!(
        ReplayWindow::new(8).verify(2_000, envelope(1), digest(b"scope"), digest(b"payload")),
        Err(Error::Expired)
    );
}
