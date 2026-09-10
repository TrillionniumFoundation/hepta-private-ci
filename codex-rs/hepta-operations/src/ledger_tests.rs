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

fn witness_for(
    key: &OperationKey,
    authority_generation: Generation,
    expires_at_unix_ms: u64,
) -> ReferenceAuthorityWitness {
    let digest = ReferenceAuthorityWitness::expected_digest(
        &key.id,
        key.payload_digest,
        authority_generation,
        expires_at_unix_ms,
    );
    let result = ReferenceAuthorityWitness::new(
        key.id.clone(),
        key.payload_digest,
        authority_generation,
        expires_at_unix_ms,
        digest,
    );
    let Ok(value) = result else {
        panic!("reference witness rejected");
    };
    value
}

fn witness(key: &OperationKey) -> ReferenceAuthorityWitness {
    witness_for(key, generation(9), 2_000)
}

fn dispatched_ledger() -> (OperationKey, OperationLedger) {
    let key = key(b"payload");
    let mut ledger = OperationLedger::default();
    assert!(ledger.begin(key.clone(), generation(3)).is_ok());
    assert!(ledger.authorize(&key.id, &witness(&key), 1_000).is_ok());
    assert!(
        ledger
            .record_dispatch(&key.id, Digest32::of_bytes(b"dispatch"))
            .is_ok()
    );
    (key, ledger)
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
    let (key, mut ledger) = dispatched_ledger();
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
fn zero_digests_reject_without_mutation() {
    let zero = Digest32::from_array([0; 32]);
    let mut ledger = OperationLedger::default();
    let invalid_key = OperationKey {
        id: stable_id("operation:zero"),
        payload_digest: zero,
    };
    assert_eq!(
        ledger.begin(invalid_key, generation(3)),
        Err(OperationError::InvalidDigest("operation payload"))
    );
    assert!(ledger.is_empty());

    let (key, mut ledger) = dispatched_ledger();
    let dispatched = ledger.clone();
    assert_eq!(
        ledger.mark_indeterminate(&key.id, zero),
        Err(OperationError::InvalidDigest("indeterminate reason"))
    );
    assert_eq!(ledger, dispatched);
    assert_eq!(
        ledger.observe_terminal(&key.id, ReconciliationOutcome::Applied, zero, generation(3)),
        Err(OperationError::InvalidDigest("terminal outcome"))
    );
    assert_eq!(ledger, dispatched);
}

#[test]
fn exact_command_replay_is_idempotent_within_the_reference_model() {
    let original_key = key(b"payload");
    let mut ledger = OperationLedger::default();
    assert!(ledger.begin(original_key.clone(), generation(3)).is_ok());
    assert!(ledger.begin(original_key.clone(), generation(3)).is_ok());
    assert_eq!(ledger.len(), 1);
    assert!(
        ledger
            .authorize(&original_key.id, &witness(&original_key), 1_000)
            .is_ok()
    );
    let authorized = ledger.clone();
    assert!(
        ledger
            .authorize(&original_key.id, &witness(&original_key), 1_500)
            .is_ok()
    );
    assert_eq!(ledger, authorized);
    let dispatch = Digest32::of_bytes(b"dispatch");
    assert!(ledger.record_dispatch(&original_key.id, dispatch).is_ok());
    let dispatched = ledger.clone();
    assert!(ledger.record_dispatch(&original_key.id, dispatch).is_ok());
    assert_eq!(ledger, dispatched);
    let outcome = Digest32::of_bytes(b"observed");
    assert!(
        ledger
            .observe_terminal(
                &original_key.id,
                ReconciliationOutcome::Applied,
                outcome,
                generation(3),
            )
            .is_ok()
    );
    let terminal = ledger.clone();
    assert!(
        ledger
            .observe_terminal(
                &original_key.id,
                ReconciliationOutcome::Applied,
                outcome,
                generation(3),
            )
            .is_ok()
    );
    assert_eq!(ledger, terminal);
}

#[test]
fn reference_witness_digest_binds_every_semantic_field() {
    let original = key(b"payload");
    let original_digest = ReferenceAuthorityWitness::expected_digest(
        &original.id,
        original.payload_digest,
        generation(9),
        2_000,
    );
    let changed_payload = key(b"changed");
    assert_eq!(
        ReferenceAuthorityWitness::new(
            changed_payload.id,
            changed_payload.payload_digest,
            generation(9),
            2_000,
            original_digest,
        ),
        Err(OperationError::AuthorityWitnessDigestMismatch)
    );
    assert_eq!(
        ReferenceAuthorityWitness::new(
            stable_id("operation:test:other"),
            original.payload_digest,
            generation(9),
            2_000,
            original_digest,
        ),
        Err(OperationError::AuthorityWitnessDigestMismatch)
    );
    assert_eq!(
        ReferenceAuthorityWitness::new(
            original.id.clone(),
            original.payload_digest,
            generation(10),
            2_000,
            original_digest,
        ),
        Err(OperationError::AuthorityWitnessDigestMismatch)
    );
    assert_eq!(
        ReferenceAuthorityWitness::new(
            original.id,
            original.payload_digest,
            generation(9),
            2_001,
            original_digest,
        ),
        Err(OperationError::AuthorityWitnessDigestMismatch)
    );
}

#[test]
fn authorized_replay_revalidates_payload_operation_and_expiry() {
    let original = key(b"payload");
    let mut ledger = OperationLedger::default();
    assert!(ledger.begin(original.clone(), generation(3)).is_ok());
    assert!(
        ledger
            .authorize(&original.id, &witness(&original), 1_000)
            .is_ok()
    );
    let authorized = ledger.clone();

    let changed_payload = key(b"changed");
    assert_eq!(
        ledger.authorize(&original.id, &witness(&changed_payload), 1_500),
        Err(OperationError::AuthorityRejected)
    );
    let changed_operation = OperationKey {
        id: stable_id("operation:test:other"),
        payload_digest: original.payload_digest,
    };
    assert_eq!(
        ledger.authorize(&original.id, &witness(&changed_operation), 1_500),
        Err(OperationError::AuthorityRejected)
    );
    assert_eq!(
        ledger.authorize(&original.id, &witness(&original), 2_000),
        Err(OperationError::AuthorityRejected)
    );
    assert_eq!(ledger, authorized);
}

#[test]
fn payload_drift_conflicts() {
    let original_key = key(b"payload");
    let mut ledger = OperationLedger::default();
    assert!(ledger.begin(original_key.clone(), generation(3)).is_ok());
    assert_eq!(
        ledger.begin(key(b"changed"), generation(3)),
        Err(OperationError::Conflict(original_key.id))
    );
}

#[test]
fn reference_ledger_capacity_is_bounded() {
    let mut ledger = OperationLedger::new(1);
    assert!(ledger.begin(key(b"one"), generation(3)).is_ok());
    let second = OperationKey {
        id: stable_id("operation:test:2"),
        payload_digest: Digest32::of_bytes(b"two"),
    };
    assert_eq!(
        ledger.begin(second, generation(3)),
        Err(OperationError::CapacityExceeded {
            resource: "reference operation ledger",
            maximum: 1,
        })
    );
}

#[test]
fn expired_or_payload_mismatched_witness_is_rejected() {
    let original = key(b"payload");
    let mut ledger = OperationLedger::default();
    assert!(ledger.begin(original.clone(), generation(3)).is_ok());
    assert_eq!(
        ledger.authorize(&original.id, &witness(&original), 2_000),
        Err(OperationError::AuthorityRejected)
    );
    let changed = key(b"changed");
    assert_eq!(
        ledger.authorize(&original.id, &witness(&changed), 1_000),
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
