use super::*;

const NOW: u64 = 8_000_000;
fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("identity")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn limits() -> FederationRecoveryLimitsV1 {
    FederationRecoveryLimitsV1 {
        replay_capacity: 512,
        replay_per_peer_capacity: 256,
        attempt_capacity: 512,
        attempt_per_peer_capacity: 256,
    }
}
fn state() -> DurableFederationStateV1 {
    DurableFederationStateV1::empty(id("local"), limits(), NOW).expect("empty")
}
fn add_replay(state: &mut DurableFederationStateV1, slot: u64, expiry: u64) {
    let mut nonce = [1; 32];
    nonce[..8].copy_from_slice(&slot.to_be_bytes());
    let peer = id("peer");
    let key = state
        .preflight_frame(
            FederationReplayKeyV1 {
                sender_peer_id: &peer,
                receiver_peer_id: &id("local"),
                key_id: &id("key"),
                generation: 1,
                nonce: &nonce,
            },
            expiry,
            NOW,
        )
        .expect("preflight");
    state
        .record_verified_frame(key, &peer, expiry)
        .expect("record");
}
fn check_indexes(state: &DurableFederationStateV1) {
    let mut rebuilt = state.clone();
    rebuilt.rebuild_indexes();
    assert_eq!(state.replay_counts, rebuilt.replay_counts);
    assert_eq!(state.attempt_counts, rebuilt.attempt_counts);
    assert_eq!(state.replay_expiries, rebuilt.replay_expiries);
    assert_eq!(state.attempt_expiries, rebuilt.attempt_expiries);
    assert_eq!(state.replay_expiries.len(), state.replay.len());
    assert_eq!(state.attempt_expiries.len(), state.attempts.len());
}

#[test]
fn shared_cleanup_budget_preserves_live_cancellation_through_restart() {
    let mut state = state();
    for slot in 0..128 {
        add_replay(&mut state, slot, NOW + 5);
        state
            .begin_attempt(
                &id("peer"),
                &id(&format!("query-{slot}")),
                digest(&format!("binding-{slot}")),
                NOW + 5,
                NOW,
            )
            .expect("attempt");
    }
    state
        .begin_attempt(
            &id("live-peer"),
            &id("live-query"),
            digest("live"),
            NOW + 100,
            NOW,
        )
        .expect("live attempt");
    let cancel = FederationCancelMessageV1 {
        query_id: id("live-query"),
        query_binding_digest: digest("live"),
        cancellation_id: id("cancel"),
        reason: FederationCancellationReasonV1::CallerCancelled,
    };
    state
        .observe_cancel(&id("live-peer"), &cancel, NOW + 1)
        .expect("cancel");
    assert_eq!(
        state
            .purge_expired_bounded(NOW + 5, 0)
            .expect("zero budget"),
        0
    );
    let mut removed = 0;
    loop {
        let batch = state.purge_expired_bounded(NOW + 5, 7).expect("cleanup");
        assert!(batch <= 7);
        removed += batch;
        check_indexes(&state);
        if batch == 0 {
            break;
        }
    }
    assert_eq!(removed, 256);
    assert_eq!(state.attempt_len(), 1);
    let bytes = state.snapshot_bytes().expect("snapshot");
    let mut restored =
        DurableFederationStateV1::restore(id("local"), limits(), NOW + 6, &bytes).expect("restart");
    check_indexes(&restored);
    assert!(restored.is_cancelled(&id("live-peer"), &id("live-query"), digest("live")));
    assert!(matches!(
        restored.observe_terminal(
            &id("live-peer"),
            &id("live-query"),
            digest("live"),
            digest("late"),
            NOW + 7
        ),
        Err(FederationRecoveryError::Cancelled)
    ));
}

#[test]
fn staged_clone_never_installs_a_transition_in_the_live_owner() {
    let mut original = state();
    add_replay(&mut original, 1, NOW + 100);
    let before = original.snapshot_bytes().expect("before");
    let mut staged = original.stage_at(NOW + 1).expect("stage");
    staged
        .begin_attempt(
            &id("peer"),
            &id("new-query"),
            digest("new"),
            NOW + 100,
            NOW + 1,
        )
        .expect("staged transition");
    assert_eq!(original.snapshot_bytes().expect("unchanged"), before);
    assert_eq!(original.attempt_len(), 0);
    assert_eq!(staged.attempt_len(), 1);
    check_indexes(&original);
    check_indexes(&staged);
}

#[test]
fn restoration_rebuilds_derived_indexes_without_changing_wire_snapshot() {
    let mut original = state();
    for slot in 0..32 {
        add_replay(&mut original, slot, NOW + 100);
    }
    original
        .begin_attempt(&id("peer"), &id("query"), digest("binding"), NOW + 100, NOW)
        .expect("attempt");
    let bytes = original.snapshot_bytes().expect("snapshot");
    let restored =
        DurableFederationStateV1::restore(id("local"), limits(), NOW, &bytes).expect("restore");
    assert_eq!(
        restored.snapshot_bytes().expect("canonical roundtrip"),
        bytes
    );
    check_indexes(&restored);
}

#[test]
fn expired_cancel_removes_the_corresponding_index_and_partition_count() {
    let mut state = state();
    state
        .begin_attempt(&id("peer"), &id("query"), digest("binding"), NOW + 5, NOW)
        .expect("attempt");
    let ack = state
        .observe_cancel(
            &id("peer"),
            &FederationCancelMessageV1 {
                query_id: id("query"),
                query_binding_digest: digest("binding"),
                cancellation_id: id("cancel"),
                reason: FederationCancellationReasonV1::CallerCancelled,
            },
            NOW + 5,
        )
        .expect("expired cancel");
    assert_eq!(
        ack.disposition,
        FederationCancellationDispositionV1::UnknownAttempt
    );
    assert!(state.attempt_counts.is_empty());
    assert!(state.attempt_expiries.is_empty());
    check_indexes(&state);
}

#[test]
fn record_cannot_bypass_capacity_expiry_or_duplicate_checks() {
    let mut state = DurableFederationStateV1::empty(
        id("local"),
        FederationRecoveryLimitsV1 {
            replay_capacity: 4,
            replay_per_peer_capacity: 1,
            attempt_capacity: 4,
            attempt_per_peer_capacity: 1,
        },
        NOW,
    )
    .expect("state");
    state
        .record_verified_frame([1; 32], &id("peer"), NOW + 10)
        .expect("first");
    assert!(matches!(
        state.record_verified_frame([2; 32], &id("peer"), NOW + 10),
        Err(FederationRecoveryError::ReplayPeerCapacityExhausted)
    ));
    assert!(matches!(
        state.record_verified_frame([1; 32], &id("peer"), NOW + 10),
        Err(FederationRecoveryError::Replay)
    ));
    assert!(matches!(
        state.record_verified_frame([3; 32], &id("other"), NOW),
        Err(FederationRecoveryError::Expired)
    ));
    assert!(matches!(
        state.record_verified_frame([0; 32], &id("other"), NOW + 10),
        Err(FederationRecoveryError::FrameIdentityMismatch)
    ));
    check_indexes(&state);
    assert_eq!(
        state.purge_expired_bounded(NOW + 10, 1).expect("cleanup"),
        1
    );
    assert!(matches!(
        state.purge_expired_bounded(NOW + 9, 1),
        Err(FederationRecoveryError::ClockRegression)
    ));
}
