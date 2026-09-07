use super::*;

fn stable_id(value: &str) -> StableId {
    let result = StableId::new(value);
    let Ok(value) = result else {
        panic!("test id rejected");
    };
    value
}

fn generation(value: u64) -> Generation {
    let result = Generation::new(value);
    let Ok(value) = result else {
        panic!("test generation rejected");
    };
    value
}

fn key(payload: &[u8]) -> OperationKey {
    OperationKey {
        id: stable_id("operation:test:1"),
        payload_digest: Digest32::of_bytes(payload),
    }
}

fn witness(key: &OperationKey) -> AuthorityWitness {
    AuthorityWitness {
        operation_id: key.id.clone(),
        final_payload_digest: key.payload_digest,
        authority_generation: generation(9),
        expires_at_unix_ms: 2_000,
        witness_digest: Digest32::of_bytes(b"independent-witness"),
    }
}

#[test]
fn dispatch_ack_is_not_terminal_success() {
    let key = key(b"payload");
    let mut ledger = OperationLedger::default();
    assert!(ledger.begin(key.clone(), generation(3)).is_ok());
    assert!(ledger.authorize(&key.id, &witness(&key), 1_000).is_ok());
    assert!(
        ledger
            .record_dispatch(&key.id, Digest32::of_bytes(b"accepted-by-transport"))
            .is_ok()
    );
    let record = ledger.get(&key.id);
    assert!(matches!(
        record.map(|value| &value.state),
        Some(OperationState::Dispatched { .. })
    ));
}

#[test]
fn indeterminate_requires_current_fence_reconciliation() {
    let key = key(b"payload");
    let mut ledger = OperationLedger::default();
    assert!(ledger.begin(key.clone(), generation(3)).is_ok());
    assert!(ledger.authorize(&key.id, &witness(&key), 1_000).is_ok());
    assert!(
        ledger
            .record_dispatch(&key.id, Digest32::of_bytes(b"dispatch"))
            .is_ok()
    );
    assert!(
        ledger
            .mark_indeterminate(&key.id, Digest32::of_bytes(b"ack-lost"))
            .is_ok()
    );
    assert_eq!(
        ledger.observe_terminal(
            &key.id,
            ReconciliationOutcome::Applied,
            Digest32::of_bytes(b"observed"),
            generation(2),
        ),
        Err(OperationError::StaleGeneration)
    );
    assert!(
        ledger
            .observe_terminal(
                &key.id,
                ReconciliationOutcome::Applied,
                Digest32::of_bytes(b"observed"),
                generation(3),
            )
            .is_ok()
    );
    assert!(matches!(
        ledger.get(&key.id).map(|value| &value.state),
        Some(OperationState::Applied { .. })
    ));
}

#[test]
fn exact_replay_survives_reopen_and_payload_drift_conflicts() {
    let original_key = key(b"payload");
    let mut ledger = OperationLedger::default();
    let first = ledger.begin(original_key.clone(), generation(3));
    assert!(first.is_ok());
    let restored = ledger.clone();
    let mut restored = restored;
    assert!(restored.begin(original_key.clone(), generation(3)).is_ok());
    assert_eq!(restored.len(), 1);
    assert_eq!(
        restored.begin(key(b"changed"), generation(3)),
        Err(OperationError::Conflict(original_key.id))
    );
}

#[test]
fn expired_or_payload_mismatched_witness_is_rejected() {
    let key = key(b"payload");
    let mut ledger = OperationLedger::default();
    assert!(ledger.begin(key.clone(), generation(3)).is_ok());
    assert_eq!(
        ledger.authorize(&key.id, &witness(&key), 2_000),
        Err(OperationError::AuthorityRejected)
    );
}

#[test]
fn exhausted_revision_preserves_every_transition_and_terminal_outcome() {
    let key = key(b"payload");
    let Ok(revision) = Revision::new(u64::MAX) else {
        panic!("maximum revision must be representable");
    };
    let digest = Digest32::of_bytes(b"transition");
    for state in [
        OperationState::Pending,
        OperationState::Authorized {
            witness_digest: digest,
            authority_generation: generation(9),
        },
        OperationState::Dispatched {
            dispatch_digest: digest,
        },
        OperationState::Indeterminate {
            reason_digest: digest,
        },
    ] {
        let mut ledger = OperationLedger::default();
        ledger.records.insert(
            key.id.clone(),
            OperationRecord {
                key: key.clone(),
                owner_generation: generation(3),
                revision,
                state: state.clone(),
            },
        );
        let original = ledger.clone();
        let error = Err(OperationError::Conflict(key.id.clone()));
        match &state {
            OperationState::Pending => {
                assert_eq!(ledger.authorize(&key.id, &witness(&key), 1_000), error);
            }
            OperationState::Authorized { .. } => {
                assert_eq!(ledger.record_dispatch(&key.id, digest), error);
            }
            OperationState::Dispatched { .. } => {
                assert_eq!(ledger.mark_indeterminate(&key.id, digest), error);
                assert_eq!(ledger, original);
            }
            OperationState::Indeterminate { .. } => {}
            OperationState::Applied { .. }
            | OperationState::NotApplied { .. }
            | OperationState::Quarantined { .. } => panic!("fixture is nonterminal"),
        }
        assert_eq!(ledger, original);
        if matches!(
            state,
            OperationState::Dispatched { .. } | OperationState::Indeterminate { .. }
        ) {
            for outcome in [
                ReconciliationOutcome::Applied,
                ReconciliationOutcome::NotApplied,
                ReconciliationOutcome::Quarantined,
            ] {
                assert_eq!(
                    ledger.observe_terminal(&key.id, outcome, digest, generation(3)),
                    error
                );
                assert_eq!(ledger, original);
            }
        }
    }
}
