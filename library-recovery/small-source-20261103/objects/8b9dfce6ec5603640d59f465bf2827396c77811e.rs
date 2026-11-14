use super::*;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn policy() -> UnverifiedTimePolicy {
    UnverifiedTimePolicy {
        minimum_rate: Rate {
            ticks: 1,
            milliseconds: 1,
        },
        maximum_rate: Rate {
            ticks: 1,
            milliseconds: 1,
        },
        measurement_error_ticks: 0,
        issuer_uncertainty_ms: 2,
        maximum_roundtrip_ms: 20,
        maximum_anchor_age_ms: 40,
    }
}

fn sample(ticks: u64) -> UnverifiedMonotonicSample {
    UnverifiedMonotonicSample {
        epoch: Digest32::from_array([9; 32]),
        ticks,
    }
}

fn challenge() -> UnverifiedTimeChallengeV2 {
    UnverifiedTimeChallengeV2 {
        nonce: [1; 32],
        requester: StableId::new("requester:a").unwrap(),
        owner_incarnation: Digest32::from_array([2; 32]),
        clock_domain: StableId::new("clock:a").unwrap(),
        policy_digest: Digest32::from_array([3; 32]),
        issuer: StableId::new("issuer:a").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
    }
}

fn response(request: &UnverifiedTimeChallengeV2) -> UnverifiedTimeResponseV2 {
    UnverifiedTimeResponseV2 {
        request_digest: request.digest(),
        issuer: request.issuer.clone(),
        key_epoch: request.key_epoch,
        sampled_wall_ms: 1000,
        source_revision: 7,
        source_digest: Digest32::from_array([4; 32]),
    }
}

#[test]
fn integer_projection_contains_fixture_true_time() {
    // Exact integer clock rates; the Python model separately exercises rational
    // rates and measurement errors. Every number here is a fixture policy.
    for rate in 1..=3 {
        for rtt in 0..=10 {
            for age in rtt..=20 {
                for issuer_sample_offset in 0..=rtt {
                    for signed_error in [-2_i64, 0, 2] {
                        let p = UnverifiedTimePolicy {
                            minimum_rate: Rate {
                                ticks: 1,
                                milliseconds: 1,
                            },
                            maximum_rate: Rate {
                                ticks: 3,
                                milliseconds: 1,
                            },
                            maximum_roundtrip_ms: 100,
                            maximum_anchor_age_ms: 100,
                            ..policy()
                        };
                        let wall = u64::try_from(1000 + issuer_sample_offset as i64 + signed_error)
                            .unwrap();
                        let interval = UnverifiedProjectedBounds::project(
                            p,
                            wall,
                            sample(0),
                            sample(rate * rtt),
                            sample(rate * age),
                            0,
                        )
                        .unwrap();
                        assert!(interval.earliest_ms <= 1000 + age);
                        assert!(interval.latest_ms >= 1000 + age);
                    }
                }
            }
        }
    }
}

#[test]
fn outward_rounding_and_measurement_error_are_conservative() {
    let p = UnverifiedTimePolicy {
        minimum_rate: Rate {
            ticks: 2,
            milliseconds: 1,
        },
        maximum_rate: Rate {
            ticks: 3,
            milliseconds: 1,
        },
        ..policy()
    };
    assert_eq!(p.elapsed(0, 5), Ok((1, 3)));
    let p = UnverifiedTimePolicy {
        measurement_error_ticks: 1,
        ..p
    };
    assert_eq!(p.elapsed(0, 5), Ok((1, 4)));
    assert_eq!(p.elapsed(0, 1), Ok((0, 2)));
}

#[test]
fn freshness_never_extends_expiry_or_activates_future_authority() {
    let interval =
        UnverifiedProjectedBounds::project(policy(), 1000, sample(0), sample(2), sample(8), 0)
            .unwrap();
    assert!(!interval.fits_window(900, 1007));
    assert!(!interval.fits_window(1008, 2000));
    assert!(interval.fits_window(900, 2000));
    assert!(!interval.fits_window(900, interval.latest_ms));
}

#[test]
fn durable_floor_only_tightens_expiry() {
    let interval =
        UnverifiedProjectedBounds::project(policy(), 1000, sample(0), sample(2), sample(3), 1100)
            .unwrap();
    assert_eq!(
        interval,
        UnverifiedProjectedBounds {
            earliest_ms: 999,
            latest_ms: 1100
        }
    );
    assert!(!interval.fits_window(1010, 2000));
    assert!(!interval.fits_window(900, 1100));
}

#[test]
fn roundtrip_and_age_use_upper_elapsed_from_send() {
    let p = UnverifiedTimePolicy {
        minimum_rate: Rate {
            ticks: 1,
            milliseconds: 2,
        },
        maximum_rate: Rate {
            ticks: 2,
            milliseconds: 1,
        },
        maximum_roundtrip_ms: 15,
        ..policy()
    };
    assert_eq!(
        UnverifiedProjectedBounds::project(p, 1000, sample(0), sample(10), sample(10), 0),
        Err(TimeSpecError::RoundtripExceeded)
    );
    let p = UnverifiedTimePolicy {
        maximum_roundtrip_ms: 20,
        maximum_anchor_age_ms: 15,
        ..p
    };
    assert_eq!(
        UnverifiedProjectedBounds::project(p, 1000, sample(0), sample(2), sample(10), 0),
        Err(TimeSpecError::AnchorStale)
    );
    let p = UnverifiedTimePolicy {
        maximum_anchor_age_ms: 10,
        ..policy()
    };
    assert_eq!(
        UnverifiedProjectedBounds::project(p, 1000, sample(0), sample(8), sample(11), 0),
        Err(TimeSpecError::AnchorStale)
    );
}

#[test]
fn invalid_policy_clock_and_arithmetic_fail_closed() {
    for bad_rate in [
        Rate {
            ticks: 0,
            milliseconds: 1,
        },
        Rate {
            ticks: 1,
            milliseconds: 0,
        },
        Rate {
            ticks: 2,
            milliseconds: 1,
        },
    ] {
        assert_eq!(
            UnverifiedTimePolicy {
                minimum_rate: bad_rate,
                ..policy()
            }
            .validate(),
            Err(TimeSpecError::InvalidPolicy)
        );
    }
    assert_eq!(
        UnverifiedTimePolicy {
            maximum_anchor_age_ms: 0,
            ..policy()
        }
        .validate(),
        Err(TimeSpecError::InvalidPolicy)
    );
    assert_eq!(
        UnverifiedTimePolicy {
            maximum_roundtrip_ms: 0,
            ..policy()
        }
        .validate(),
        Err(TimeSpecError::InvalidPolicy)
    );
    assert_eq!(policy().elapsed(2, 1), Err(TimeSpecError::ClockRollback));
    let changed_epoch = UnverifiedMonotonicSample {
        epoch: Digest32::ZERO,
        ticks: 3,
    };
    assert_eq!(
        UnverifiedProjectedBounds::project(policy(), 1000, sample(0), sample(2), changed_epoch, 0),
        Err(TimeSpecError::ClockEpochMismatch)
    );
    assert_eq!(
        UnverifiedProjectedBounds::project(policy(), 1000, sample(0), sample(2), sample(1), 0),
        Err(TimeSpecError::ClockRollback)
    );
    for wall in [1, u64::MAX] {
        assert_eq!(
            UnverifiedProjectedBounds::project(policy(), wall, sample(0), sample(1), sample(1), 0),
            Err(TimeSpecError::Arithmetic)
        );
    }
    let p = UnverifiedTimePolicy {
        minimum_rate: Rate {
            ticks: 1,
            milliseconds: u64::MAX,
        },
        maximum_rate: Rate {
            ticks: 1,
            milliseconds: u64::MAX,
        },
        measurement_error_ticks: u64::MAX,
        ..policy()
    };
    assert_eq!(p.elapsed(0, u64::MAX), Err(TimeSpecError::Arithmetic));
}

#[test]
fn every_request_binding_changes_digest_and_rejects_substitution() {
    let request = challenge();
    let original = response(&request);
    assert_eq!(original.matches_request(&request), Ok(()));
    let mut variants = vec![request.clone(); 7];
    variants[0].nonce[0] ^= 1;
    variants[1].requester = StableId::new("requester:b").unwrap();
    variants[2].owner_incarnation = Digest32::from_array([8; 32]);
    variants[3].clock_domain = StableId::new("clock:b").unwrap();
    variants[4].policy_digest = Digest32::from_array([8; 32]);
    variants[5].issuer = StableId::new("issuer:b").unwrap();
    variants[6].key_epoch = Generation::new(2).unwrap();
    for changed in variants {
        assert_ne!(changed.digest(), request.digest());
        assert_eq!(
            original.matches_request(&changed),
            Err(TimeSpecError::RequestMismatch)
        );
    }
    let mut changed = original.clone();
    changed.issuer = StableId::new("issuer:b").unwrap();
    assert_eq!(
        changed.matches_request(&request),
        Err(TimeSpecError::RequestMismatch)
    );
    changed = original;
    changed.key_epoch = Generation::new(2).unwrap();
    assert_eq!(
        changed.matches_request(&request),
        Err(TimeSpecError::RequestMismatch)
    );
}

#[test]
fn canonical_request_has_fixed_domain_lengths_and_field_order() {
    let request = challenge();
    let mut expected = b"hepta.authbus.current-time.challenge.v2\0".to_vec();
    expected.extend_from_slice(&[1; 32]);
    expected.extend_from_slice(b"\0\0\0\x0brequester:a");
    expected.extend_from_slice(&[2; 32]);
    expected.extend_from_slice(b"\0\0\0\x07clock:a");
    expected.extend_from_slice(&[3; 32]);
    expected.extend_from_slice(b"\0\0\0\x08issuer:a");
    expected.extend_from_slice(&1_u64.to_be_bytes());
    assert_eq!(request.canonical_bytes(), expected);
}

#[test]
fn signed_response_binds_all_fields_and_cannot_cross_v1_domain() {
    let request = challenge();
    let original = response(&request);
    let key = SigningKey::from_bytes(&[42; 32]);
    let signature: Signature = key.sign(&original.signing_bytes());
    assert!(
        key.verifying_key()
            .verify_strict(&original.signing_bytes(), &signature)
            .is_ok()
    );
    let mut variants = vec![original.clone(); 6];
    variants[0].request_digest = Digest32::ZERO;
    variants[1].issuer = StableId::new("issuer:b").unwrap();
    variants[2].key_epoch = Generation::new(2).unwrap();
    variants[3].sampled_wall_ms += 1;
    variants[4].source_revision += 1;
    variants[5].source_digest = Digest32::ZERO;
    for changed in variants {
        assert!(
            key.verifying_key()
                .verify_strict(&changed.signing_bytes(), &signature)
                .is_err()
        );
    }
    let legacy = crate::TrustedTimeAttestationClaims {
        issuer_id: original.issuer,
        key_epoch: original.key_epoch,
        wall_time_ms: original.sampled_wall_ms,
        source_revision: original.source_revision,
        source_digest: original.source_digest,
    };
    assert!(
        legacy
            .signing_bytes()
            .starts_with(b"hepta.authbus.trusted-time.v1\0")
    );
    assert!(
        key.verifying_key()
            .verify_strict(&legacy.signing_bytes(), &signature)
            .is_err()
    );
}

#[test]
fn source_validation_preserves_v1_nonzero_invariants() {
    let request = challenge();
    let original = response(&request);
    assert_eq!(original.validate_source(), Ok(()));
    let mut variants = vec![original; 3];
    variants[0].sampled_wall_ms = 0;
    variants[1].source_revision = 0;
    variants[2].source_digest = Digest32::ZERO;
    for changed in variants {
        assert_eq!(changed.validate_source(), Err(TimeSpecError::InvalidSource));
        assert_eq!(
            changed.matches_request(&request),
            Err(TimeSpecError::InvalidSource)
        );
    }
}
