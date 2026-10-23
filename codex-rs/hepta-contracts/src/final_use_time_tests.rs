//! Native regressions for owner-clock uncertainty at every final-use boundary.
use super::*;
use std::sync::atomic::AtomicU64;

struct Clock {
    centre: AtomicU64,
    radius: AtomicU64,
}

impl Clock {
    fn new(centre: u64, radius: u64) -> Self {
        Self {
            centre: AtomicU64::new(centre),
            radius: AtomicU64::new(radius),
        }
    }
}

impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.centre.load(Ordering::SeqCst))
    }

    fn now_with_uncertainty(&self) -> Result<(u64, u64), AuthorityTrustError> {
        Ok((self.now_unix_ms()?, self.radius.load(Ordering::SeqCst)))
    }
}

fn head() -> FinalUseRevocations {
    FinalUseRevocations {
        authority_epoch: 7,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    }
}

fn grant() -> FinalUseGrant {
    FinalUseGrant {
        schema_version: 1,
        signer_id: "clock-test-owner".into(),
        authority_epoch: 7,
        grant_id: "clock-test-grant".into(),
        nonce: Sha256::digest(b"hepta.authority.time-regression.nonce.v1").into(),
        binding: FinalUseBinding {
            subject_id: "agent-one".into(),
            destination_id: "fixture:clock".into(),
            request_sha256: Sha256::digest(b"request").into(),
            scope_sha256: Sha256::digest(b"scope").into(),
            payload_sha256: Sha256::digest(b"payload").into(),
        },
        not_before_unix_ms: 1_000,
        expires_at_unix_ms: 3_000,
    }
}

#[test]
fn entire_clock_interval_must_fit_the_half_open_grant_window() {
    let grant = grant();
    let head = head();
    assert_eq!(
        validate_live_clock(&grant, &head, &Clock::new(2_000, 999)),
        Ok(2_000)
    );
    assert_eq!(
        validate_live_clock(&grant, &head, &Clock::new(1_000, 1)),
        Err(FinalUseError::NotYetValid)
    );
    assert_eq!(
        validate_live_clock(&grant, &head, &Clock::new(2_999, 1)),
        Err(FinalUseError::Expired)
    );
    assert_eq!(
        validate_live_clock(&grant, &head, &Clock::new(3_000, 0)),
        Err(FinalUseError::Expired)
    );
    assert_eq!(
        validate_live_clock(&grant, &head, &Clock::new(1_000, 0)),
        Ok(1_000)
    );
}

#[test]
fn invalid_clock_uncertainty_is_not_saturated_into_validity() {
    let mut grant = grant();
    grant.not_before_unix_ms = 0;
    grant.expires_at_unix_ms = u64::MAX;
    assert_eq!(
        validate_live_clock(&grant, &head(), &Clock::new(1, 2)),
        Err(FinalUseError::NotYetValid)
    );
    assert_eq!(
        validate_live_clock(&grant, &head(), &Clock::new(u64::MAX - 1, 2)),
        Err(FinalUseError::Expired)
    );
    assert_eq!(
        validate_live_clock(&grant, &head(), &Clock::new(100_000, 60_001)),
        Err(FinalUseError::InvalidTrust)
    );
}

#[cfg(unix)]
#[test]
fn tokens_recheck_changed_uncertainty_and_do_not_refund_claims() {
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use std::os::unix::fs::PermissionsExt;

    for boundary in 0..4 {
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let clock = Arc::new(Clock::new(2_000, 10));
        let key = SigningKey::from_bytes(&Sha256::digest(b"clock-test-issuer").into());
        let grant = grant();
        let signed = SignedFinalUseGrant {
            signature: key
                .sign(&grant.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            grant,
        };
        let authority = FinalUseAuthority::open_state_dir_with_clock(
            directory.path(),
            "clock-test-owner".into(),
            key.verifying_key().to_bytes(),
            head(),
            clock.clone(),
        )
        .unwrap();
        let token = authority.claim(&signed, &signed.grant.binding).unwrap();
        clock.radius.store(1_000, Ordering::SeqCst);
        let called = std::sync::atomic::AtomicBool::new(false);
        let result = match boundary {
            0 => token.enter(&signed.grant.binding).map(|_| ()),
            1 => authority.with_verified_use(token, &signed.grant.binding, || {
                called.store(true, Ordering::SeqCst);
            }),
            2 => authority.with_dispatch_boundary(token, &signed.grant.binding, || {
                called.store(true, Ordering::SeqCst);
            }),
            _ => authority.with_verified_effect(token, &signed.grant.binding, || {
                called.store(true, Ordering::SeqCst);
            }),
        };
        assert_eq!(result, Err(FinalUseError::Expired));
        assert!(!called.load(Ordering::SeqCst));
        clock.radius.store(10, Ordering::SeqCst);
        assert_eq!(
            authority.claim(&signed, &signed.grant.binding).unwrap_err(),
            FinalUseError::AlreadyClaimed
        );
    }
}
