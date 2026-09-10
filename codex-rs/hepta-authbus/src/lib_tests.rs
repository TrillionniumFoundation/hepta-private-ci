use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn generation(value: u64) -> Generation {
    let Ok(value) = Generation::new(value) else {
        panic!("test generation must be valid");
    };
    value
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn context() -> TrustedReplayContext {
    TrustedReplayContext {
        issuer_id: id("issuer:1"),
        key_epoch: generation(1),
        now_ms: 1_000,
        revoked: false,
    }
}

fn envelope(sequence: u64) -> PreverifiedAuthEnvelope {
    PreverifiedAuthEnvelope {
        message_id: id(&format!("message:{sequence}")),
        subject_id: id("subject:1"),
        scope_digest: digest(b"scope"),
        payload_digest: digest(b"payload"),
        signature_digest: digest(b"signature"),
        sequence,
        expires_at_ms: 2_000,
    }
}

#[test]
fn exact_envelope_is_replay_checked_without_authority_grant() {
    let mut window = ReplayWindow::new(8);
    let Ok(receipt) = window.verify(context(), envelope(1), digest(b"scope"), digest(b"payload"))
    else {
        panic!("exact envelope must verify");
    };
    assert_eq!(receipt.sequence, 1);
    assert_eq!(receipt.issuer_id, id("issuer:1"));
    assert!(!receipt.authority.grants_any());
}

#[test]
fn a_nonzero_signature_reference_is_not_cryptographic_authority() {
    let mut value = envelope(1);
    value.signature_digest = digest(b"untrusted-but-nonzero-reference");
    let Ok(receipt) =
        ReplayWindow::new(8).verify(context(), value, digest(b"scope"), digest(b"payload"))
    else {
        panic!("the replay verifier only performs structural digest checks");
    };
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn replay_is_rejected_within_one_issuer_epoch_subject_and_scope() {
    let mut window = ReplayWindow::new(8);
    assert!(
        window
            .verify(context(), envelope(1), digest(b"scope"), digest(b"payload"),)
            .is_ok()
    );
    assert_eq!(
        window.verify(context(), envelope(1), digest(b"scope"), digest(b"payload"),),
        Err(Error::Replay)
    );
}

#[test]
fn scope_issuer_and_key_epoch_have_independent_replay_sequences() {
    let mut window = ReplayWindow::new(8);
    assert!(
        window
            .verify(context(), envelope(1), digest(b"scope"), digest(b"payload"),)
            .is_ok()
    );

    let mut other_scope = envelope(1);
    other_scope.scope_digest = digest(b"other-scope");
    assert!(
        window
            .verify(
                context(),
                other_scope,
                digest(b"other-scope"),
                digest(b"payload"),
            )
            .is_ok()
    );

    let mut other_issuer = context();
    other_issuer.issuer_id = id("issuer:2");
    assert!(
        window
            .verify(
                other_issuer,
                envelope(1),
                digest(b"scope"),
                digest(b"payload"),
            )
            .is_ok()
    );

    let mut other_epoch = context();
    other_epoch.key_epoch = generation(2);
    assert!(
        window
            .verify(
                other_epoch,
                envelope(1),
                digest(b"scope"),
                digest(b"payload"),
            )
            .is_ok()
    );
}

#[test]
fn trusted_revocation_context_is_fail_closed() {
    let mut revoked = context();
    revoked.revoked = true;
    assert_eq!(
        ReplayWindow::new(8).verify(revoked, envelope(1), digest(b"scope"), digest(b"payload"),),
        Err(Error::Revoked)
    );
}

#[test]
fn payload_drift_is_rejected() {
    assert_eq!(
        ReplayWindow::new(8).verify(context(), envelope(1), digest(b"scope"), digest(b"other"),),
        Err(Error::PayloadMismatch)
    );
}

#[test]
fn expiration_is_fail_closed() {
    let mut expired = context();
    expired.now_ms = 2_000;
    assert_eq!(
        ReplayWindow::new(8).verify(expired, envelope(1), digest(b"scope"), digest(b"payload"),),
        Err(Error::Expired)
    );
}

#[test]
fn zero_digest_and_zero_sequence_are_rejected() {
    let mut zero_digest = envelope(1);
    zero_digest.signature_digest = Digest32::ZERO;
    assert_eq!(
        ReplayWindow::new(8).verify(context(), zero_digest, digest(b"scope"), digest(b"payload"),),
        Err(Error::EmptyDigest("signature"))
    );
    assert_eq!(
        ReplayWindow::new(8).verify(context(), envelope(0), digest(b"scope"), digest(b"payload"),),
        Err(Error::ZeroSequence)
    );
}

#[test]
fn replay_key_capacity_is_bounded() {
    let mut window = ReplayWindow::new(1);
    assert!(
        window
            .verify(context(), envelope(1), digest(b"scope"), digest(b"payload"),)
            .is_ok()
    );
    let mut second = envelope(1);
    second.subject_id = id("subject:2");
    assert_eq!(
        window.verify(context(), second, digest(b"scope"), digest(b"payload"),),
        Err(Error::CapacityExceeded)
    );
}
