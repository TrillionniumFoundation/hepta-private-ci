//! The original budget is checked by the synchronous first-effect clock.
use super::*;
use codex_hepta_authbus::TrustedTimeAttestationClaims;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
fn attestation(wall_ms: u64, revision: u64) -> SignedTrustedTimeAttestation {
    SignedTrustedTimeAttestation {
        claims: TrustedTimeAttestationClaims {
            issuer_id: StableId::new("native-time").unwrap(),
            key_epoch: Generation::new(1).unwrap(),
            wall_time_ms: wall_ms,
            source_revision: revision,
            source_digest: Digest32::of_bytes(&revision.to_be_bytes()),
        },
        signature: [0; 64],
    }
}
#[test]
fn original_budget_blocks_dispatch_after_expiry_and_guard_releases_original()
-> Result<(), Box<dyn std::error::Error>> {
    let clock = Arc::new(RuntimeProtectedClock::new(Duration::from_secs(1)));
    clock.observe(&attestation(100_000, 1), Instant::now())?;
    let guard = clock.begin_original_deadline(Instant::now() + Duration::from_millis(20))?;
    assert!(clock.now_unix_ms().is_ok());
    assert!(
        clock
            .begin_original_deadline(Instant::now() + Duration::from_secs(1))
            .is_err()
    );
    std::thread::sleep(Duration::from_millis(25));
    assert_eq!(clock.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
    drop(guard);
    assert!(clock.now_unix_ms().is_ok());
    Ok(())
}
#[test]
fn stale_sample_and_rollback_fail_closed_without_minting_fresh_clock()
-> Result<(), Box<dyn std::error::Error>> {
    let clock = RuntimeProtectedClock::new(Duration::from_millis(20));
    clock.observe(&attestation(100_000, 1), Instant::now())?;
    std::thread::sleep(Duration::from_millis(25));
    assert_eq!(clock.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
    clock.observe(&attestation(100_030, 2), Instant::now())?;
    assert_eq!(
        clock.observe(&attestation(100_029, 3), Instant::now()),
        Err(ConsumerPortError::Unavailable)
    );
    assert_eq!(
        clock.observe(&attestation(100_100, 4), Instant::now()),
        Err(ConsumerPortError::Unavailable)
    );
    assert_eq!(clock.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
    Ok(())
}
#[test]
fn equal_source_revision_and_slow_protected_preflight_are_rejected()
-> Result<(), Box<dyn std::error::Error>> {
    let clock = RuntimeProtectedClock::new(Duration::from_millis(20));
    assert_eq!(
        clock.observe(
            &attestation(100_000, 1),
            Instant::now() - Duration::from_millis(25)
        ),
        Err(ConsumerPortError::Unavailable)
    );
    assert_eq!(clock.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
    clock.observe(&attestation(100_000, 1), Instant::now())?;
    assert_eq!(
        clock.observe(&attestation(100_010, 1), Instant::now()),
        Err(ConsumerPortError::Unavailable)
    );
    assert_eq!(clock.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
    Ok(())
}

#[test]
fn recovery_preflight_refreshes_the_idle_runtime_clock() {
    let clock = Arc::new(RuntimeProtectedClock::new(Duration::from_secs(1)));
    clock
        .observe(&attestation(100_000, 1), Instant::now())
        .unwrap();
    clock.sample.lock().unwrap().as_mut().unwrap().sampled_at =
        Instant::now() - Duration::from_secs(2);
    assert_eq!(clock.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
    let mut source = RuntimeEvidence {
        client: RecoveryEvidenceSource::Valid {
            wall_ms: 102_000,
            revision: 2,
        },
        clock: Arc::clone(&clock),
    };
    source.trusted_time().unwrap();
    assert!(clock.now_unix_ms().is_ok());
}

enum RecoveryEvidenceSource {
    Valid { wall_ms: u64, revision: u64 },
    Unavailable,
}

#[test]
fn slow_response_does_not_erase_the_accepted_clock_floor() {
    let clock = RuntimeProtectedClock::new(Duration::from_secs(1));
    clock
        .observe(&attestation(100_000, 10), Instant::now())
        .unwrap();
    assert_eq!(
        clock.observe(
            &attestation(102_000, 11),
            Instant::now() - Duration::from_secs(2)
        ),
        Err(ConsumerPortError::Unavailable)
    );
    assert_eq!(
        clock.observe(&attestation(99_000, 9), Instant::now()),
        Err(ConsumerPortError::Unavailable)
    );
    assert_eq!(clock.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
}

impl BaoAuthBusEvidenceProvider for RecoveryEvidenceSource {
    fn trusted_time(&mut self) -> Result<SignedTrustedTimeAttestation, BaoAuthBusError> {
        match self {
            Self::Valid { wall_ms, revision } => Ok(attestation(*wall_ms, *revision)),
            Self::Unavailable => Err(BaoAuthBusError::Evidence("synthetic unavailable source")),
        }
    }

    fn settlement_evidence(
        &mut self,
        _reservation: &QuotaReservation,
        _status: SettlementStatus,
        _cost: u64,
        _terminal: Digest32,
        _observed_at_ms: u64,
    ) -> Result<SignedSettlementEvidence, BaoAuthBusError> {
        panic!("clock refresh must not settle or execute an operation")
    }
}

#[test]
fn recovery_refresh_cannot_clear_a_permanent_clock_fence() {
    let clock = Arc::new(RuntimeProtectedClock::new(Duration::from_secs(1)));
    clock
        .observe(&attestation(100_000, 10), Instant::now())
        .unwrap();
    let mut replay = RuntimeEvidence {
        client: RecoveryEvidenceSource::Valid {
            wall_ms: 100_000,
            revision: 10,
        },
        clock: Arc::clone(&clock),
    };
    assert!(replay.trusted_time().is_err());
    replay.client = RecoveryEvidenceSource::Valid {
        wall_ms: 102_000,
        revision: 11,
    };
    assert!(replay.trusted_time().is_err());
    assert_eq!(clock.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
}

#[test]
fn unavailable_recovery_time_keeps_the_clock_fenced() {
    let clock = Arc::new(RuntimeProtectedClock::new(Duration::from_secs(1)));
    clock
        .observe(&attestation(100_000, 10), Instant::now())
        .unwrap();
    let mut source = RuntimeEvidence {
        client: RecoveryEvidenceSource::Unavailable,
        clock: Arc::clone(&clock),
    };
    assert!(source.trusted_time().is_err());
    source.client = RecoveryEvidenceSource::Valid {
        wall_ms: 102_000,
        revision: 11,
    };
    assert!(source.trusted_time().is_err());
    assert_eq!(clock.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
}
