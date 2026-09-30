use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AttemptRegistryError;
use crate::FederationAttemptRegistryV1;
use crate::FederationCancelMessageV1;
use crate::FederationCancellationDispositionV1;
use crate::FederationCancellationReasonV1;

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("stable id")
}

#[test]
fn cancellation_ack_fences_late_terminal_and_is_idempotent() {
    let query_id = id("query-cancelled");
    let query_digest = Digest32::of_bytes(b"query-cancelled-binding");
    let terminal_digest = Digest32::of_bytes(b"late-terminal");
    let request = FederationCancelMessageV1 {
        query_id: query_id.clone(),
        query_binding_digest: query_digest,
        cancellation_id: id("cancel-1"),
        reason: FederationCancellationReasonV1::CallerCancelled,
    };
    let mut registry = FederationAttemptRegistryV1::new(4).expect("registry");
    registry
        .begin(&query_id, query_digest, 10_000, 1_000)
        .expect("begin");
    let first = registry.observe_cancel(&request, 1_100).expect("cancel");
    assert_eq!(
        first.disposition,
        FederationCancellationDispositionV1::ObservedBeforeTerminal
    );
    let repeated = registry
        .observe_cancel(&request, 1_101)
        .expect("idempotent cancellation");
    assert_eq!(repeated.disposition, first.disposition);
    assert_eq!(repeated.observed_unix_ms, first.observed_unix_ms);
    assert!(registry.is_cancelled(&query_id, query_digest));
    assert_eq!(
        registry.observe_terminal(&query_id, query_digest, terminal_digest, 1_102),
        Err(AttemptRegistryError::Cancelled)
    );
}

#[test]
fn terminal_before_cancel_is_reported_without_retroactive_undo() {
    let query_id = id("query-terminal");
    let query_digest = Digest32::of_bytes(b"query-terminal-binding");
    let terminal_digest = Digest32::of_bytes(b"terminal");
    let mut registry = FederationAttemptRegistryV1::new(4).expect("registry");
    registry
        .begin(&query_id, query_digest, 10_000, 1_000)
        .expect("begin");
    registry
        .observe_terminal(&query_id, query_digest, terminal_digest, 1_100)
        .expect("terminal");
    let ack = registry
        .observe_cancel(
            &FederationCancelMessageV1 {
                query_id,
                query_binding_digest: query_digest,
                cancellation_id: id("cancel-after-terminal"),
                reason: FederationCancellationReasonV1::DeadlineExpired,
            },
            1_101,
        )
        .expect("ack");
    assert_eq!(
        ack.disposition,
        FederationCancellationDispositionV1::TerminalAlreadyObserved
    );
}

#[test]
fn unknown_conflicting_and_overload_states_fail_closed() {
    let query_digest = Digest32::of_bytes(b"query-binding");
    let mut registry = FederationAttemptRegistryV1::new(1).expect("registry");
    let unknown = registry
        .observe_cancel(
            &FederationCancelMessageV1 {
                query_id: id("unknown"),
                query_binding_digest: query_digest,
                cancellation_id: id("cancel-unknown"),
                reason: FederationCancellationReasonV1::AuthorityRevoked,
            },
            1_000,
        )
        .expect("unknown ack");
    assert_eq!(
        unknown.disposition,
        FederationCancellationDispositionV1::UnknownAttempt
    );

    let query_id = id("query-live");
    registry
        .begin(&query_id, query_digest, 10_000, 1_000)
        .expect("begin");
    assert_eq!(
        registry.begin(&id("query-overload"), query_digest, 10_000, 1_000),
        Err(AttemptRegistryError::CapacityExhausted)
    );
    registry
        .observe_cancel(
            &FederationCancelMessageV1 {
                query_id: query_id.clone(),
                query_binding_digest: query_digest,
                cancellation_id: id("cancel-a"),
                reason: FederationCancellationReasonV1::CallerCancelled,
            },
            1_100,
        )
        .expect("first cancel");
    assert_eq!(
        registry.observe_cancel(
            &FederationCancelMessageV1 {
                query_id: query_id.clone(),
                query_binding_digest: query_digest,
                cancellation_id: id("cancel-b"),
                reason: FederationCancellationReasonV1::CallerCancelled,
            },
            1_101,
        ),
        Err(AttemptRegistryError::ConflictingCancellation)
    );
    assert_eq!(
        registry.observe_cancel(
            &FederationCancelMessageV1 {
                query_id,
                query_binding_digest: query_digest,
                cancellation_id: id("cancel-a"),
                reason: FederationCancellationReasonV1::AuthorityRevoked,
            },
            1_102,
        ),
        Err(AttemptRegistryError::ConflictingCancellation)
    );
}

#[test]
fn attempt_observation_clock_cannot_regress() {
    let query_id = id("query-clock");
    let query_digest = Digest32::of_bytes(b"query-clock-binding");
    let terminal_digest = Digest32::of_bytes(b"terminal-clock");
    let cancel = FederationCancelMessageV1 {
        query_id: query_id.clone(),
        query_binding_digest: query_digest,
        cancellation_id: id("cancel-clock"),
        reason: FederationCancellationReasonV1::CallerCancelled,
    };
    let mut registry = FederationAttemptRegistryV1::new(4).expect("registry");
    assert_eq!(
        registry.begin(&query_id, query_digest, 10_000, 0),
        Err(AttemptRegistryError::ZeroObservationTime)
    );
    registry
        .begin(&query_id, query_digest, 10_000, 1_000)
        .expect("begin");
    assert_eq!(
        registry.observe_terminal(&query_id, query_digest, terminal_digest, 999),
        Err(AttemptRegistryError::ClockRegression)
    );
    assert_eq!(
        registry.observe_cancel(&cancel, 999),
        Err(AttemptRegistryError::ClockRegression)
    );
    let first = registry
        .observe_cancel(&cancel, 1_100)
        .expect("first cancel");
    assert_eq!(
        registry.observe_cancel(&cancel, 1_099),
        Err(AttemptRegistryError::ClockRegression)
    );
    assert_eq!(first.observed_unix_ms, 1_100);
}
