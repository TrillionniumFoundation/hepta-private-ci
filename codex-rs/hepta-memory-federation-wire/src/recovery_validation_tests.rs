use super::*;

const NOW: u64 = 8_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("identity")
}

fn limits() -> FederationRecoveryLimitsV1 {
    FederationRecoveryLimitsV1 {
        replay_capacity: 8,
        replay_per_peer_capacity: 4,
        attempt_capacity: 8,
        attempt_per_peer_capacity: 4,
    }
}

fn cancellation_snapshot() -> RecoveryEnvelope {
    let mut state = DurableFederationStateV1::empty(id("host"), limits(), NOW).expect("empty");
    let binding = Digest32::of_bytes(b"binding");
    state
        .begin_attempt(&id("peer"), &id("query"), binding, NOW + 100, NOW)
        .expect("begin");
    state
        .observe_cancel(
            &id("peer"),
            &FederationCancelMessageV1 {
                query_id: id("query"),
                query_binding_digest: binding,
                cancellation_id: id("cancel"),
                reason: FederationCancellationReasonV1::CallerCancelled,
            },
            NOW + 1,
        )
        .expect("cancel");
    serde_json::from_slice(&state.snapshot_bytes().expect("snapshot")).expect("decode fixture")
}

fn restore(
    mut envelope: RecoveryEnvelope,
    now: u64,
) -> Result<DurableFederationStateV1, FederationRecoveryError> {
    // Rehash using the canonical producer. These tests exercise semantic
    // validation, not merely detection of accidental byte corruption.
    envelope.digest = snapshot_digest(&serde_json::to_vec(&envelope.payload).expect("payload"));
    DurableFederationStateV1::restore(
        id("host"),
        limits(),
        now,
        &serde_json::to_vec(&envelope).expect("envelope"),
    )
}

#[test]
fn invalid_begin_is_rejected_instead_of_silently_dropping_a_cancelled_attempt() {
    let mut envelope = cancellation_snapshot();
    envelope.payload.attempts[0].began_unix_ms = 0;
    assert!(matches!(
        restore(envelope, NOW + 2),
        Err(FederationRecoveryError::SnapshotStateInvalid)
    ));
}

#[test]
fn expired_records_still_require_valid_semantics() {
    let mut envelope = cancellation_snapshot();
    envelope.payload.attempts[0].expires_unix_ms = NOW;
    assert!(matches!(
        restore(envelope, NOW + 200),
        Err(FederationRecoveryError::SnapshotStateInvalid)
    ));
}

#[test]
fn cancellation_cannot_predate_begin_or_exceed_the_snapshot_clock() {
    for invalid_time in [0, NOW - 1, NOW + 2, NOW + 100] {
        let mut envelope = cancellation_snapshot();
        let StoredAttemptState::Cancelled {
            observed_unix_ms, ..
        } = &mut envelope.payload.attempts[0].state
        else {
            panic!("cancelled fixture")
        };
        *observed_unix_ms = invalid_time;
        assert!(matches!(
            restore(envelope, NOW + 200),
            Err(FederationRecoveryError::SnapshotStateInvalid)
        ));
    }
}

#[test]
fn terminal_timestamps_are_checked_even_after_expiry() {
    let mut envelope = cancellation_snapshot();
    envelope.payload.attempts[0].state = StoredAttemptState::Terminal {
        terminal_digest: *Digest32::of_bytes(b"terminal").as_array(),
        observed_unix_ms: NOW + 100,
    };
    assert!(matches!(
        restore(envelope, NOW + 200),
        Err(FederationRecoveryError::SnapshotStateInvalid)
    ));
}

#[test]
fn zero_query_digest_is_not_hidden_by_expiration() {
    let mut envelope = cancellation_snapshot();
    envelope.payload.attempts[0].query_binding_digest = [0; 32];
    assert!(matches!(
        restore(envelope, NOW + 200),
        Err(FederationRecoveryError::EmptyDigest)
    ));
}

#[test]
fn valid_expired_cancellation_is_collected() {
    let restored = restore(cancellation_snapshot(), NOW + 200).expect("valid expired snapshot");
    assert_eq!(restored.attempt_len(), 0);
}

#[test]
fn host_profiles_cannot_widen_recovery_architecture_limits() {
    let mut value = limits();
    value.replay_capacity = crate::replay::MAX_FEDERATION_REPLAY_ENTRIES + 1;
    assert_eq!(
        value.validate(),
        Err(FederationRecoveryError::InvalidLimits)
    );
    value = limits();
    value.attempt_capacity = crate::attempt::MAX_FEDERATION_ATTEMPTS + 1;
    assert_eq!(
        value.validate(),
        Err(FederationRecoveryError::InvalidLimits)
    );
}
