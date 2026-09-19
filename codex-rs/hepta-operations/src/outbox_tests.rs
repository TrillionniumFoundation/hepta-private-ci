use super::*;
use crate::OperationLedger;

fn stable_id(value: &str) -> StableId {
    let result = StableId::new(value);
    let Ok(value) = result else {
        panic!("test identifier rejected");
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

fn intent() -> OutboxIntent {
    OutboxIntent {
        intent_id: stable_id("intent:1"),
        operation_id: stable_id("operation:1"),
        destination: stable_id("cognitive.store"),
        payload_digest: Digest32::of_bytes(b"payload"),
        operation_digest: Digest32::of_bytes(b"operation"),
    }
}

#[test]
fn claim_and_ack_are_generation_fenced() {
    let intent = intent();
    let mut outbox = Outbox::default();
    assert_eq!(outbox.enqueue(intent.clone()), Ok(()));
    assert!(outbox.claim(&intent.intent_id, generation(4)).is_ok());
    assert_eq!(
        outbox.acknowledge(&intent.intent_id, generation(3), Digest32::of_bytes(b"ack"),),
        Err(OperationError::StaleGeneration)
    );
    assert_eq!(
        outbox.acknowledge(&intent.intent_id, generation(4), Digest32::of_bytes(b"ack"),),
        Ok(())
    );
}

#[test]
fn acknowledged_replay_retains_generation_fence() {
    let intent = intent();
    let mut outbox = Outbox::default();
    let ack = Digest32::of_bytes(b"ack");
    assert_eq!(outbox.enqueue(intent.clone()), Ok(()));
    assert!(outbox.claim(&intent.intent_id, generation(4)).is_ok());
    assert_eq!(
        outbox.acknowledge(&intent.intent_id, generation(4), ack),
        Ok(())
    );
    assert_eq!(
        outbox.acknowledge(&intent.intent_id, generation(3), ack),
        Err(OperationError::StaleGeneration)
    );
    assert_eq!(
        outbox.acknowledge(
            &intent.intent_id,
            generation(4),
            Digest32::of_bytes(b"changed-ack"),
        ),
        Err(OperationError::Conflict(intent.intent_id.clone()))
    );
    assert!(matches!(
        outbox.state(&intent.intent_id),
        Some(OutboxState::Acknowledged {
            owner_generation,
            attempt,
            acknowledgement_digest,
        }) if *owner_generation == generation(4)
            && *attempt == 1
            && *acknowledgement_digest == ack
    ));
}

#[test]
fn exact_enqueue_claim_and_ack_replay_are_idempotent() {
    let intent = intent();
    let mut outbox = Outbox::default();
    assert_eq!(outbox.enqueue(intent.clone()), Ok(()));
    assert_eq!(outbox.enqueue(intent.clone()), Ok(()));
    assert!(outbox.claim(&intent.intent_id, generation(4)).is_ok());
    assert!(outbox.claim(&intent.intent_id, generation(4)).is_ok());
    let ack = Digest32::of_bytes(b"ack");
    assert_eq!(
        outbox.acknowledge(&intent.intent_id, generation(4), ack),
        Ok(())
    );
    assert_eq!(
        outbox.acknowledge(&intent.intent_id, generation(4), ack),
        Ok(())
    );
}

#[test]
fn zero_payload_and_acknowledgement_reject_without_mutation() {
    let mut invalid = intent();
    invalid.payload_digest = Digest32::ZERO;
    let mut outbox = Outbox::default();
    assert_eq!(
        outbox.enqueue(invalid),
        Err(OperationError::InvalidDigest("outbox payload"))
    );
    assert!(outbox.is_empty());

    let valid = intent();
    assert_eq!(outbox.enqueue(valid.clone()), Ok(()));
    assert!(outbox.claim(&valid.intent_id, generation(4)).is_ok());
    let claimed = outbox.clone();
    assert_eq!(
        outbox.acknowledge(&valid.intent_id, generation(4), Digest32::ZERO),
        Err(OperationError::InvalidDigest("outbox acknowledgement"))
    );
    assert_eq!(outbox, claimed);
}

#[test]
fn reference_outbox_capacity_is_bounded() {
    let first = intent();
    let mut outbox = Outbox::new(1);
    assert_eq!(outbox.enqueue(first), Ok(()));
    let second = OutboxIntent {
        intent_id: stable_id("intent:2"),
        operation_id: stable_id("operation:2"),
        destination: stable_id("cognitive.store"),
        payload_digest: Digest32::of_bytes(b"payload-2"),
        operation_digest: Digest32::of_bytes(b"operation-2"),
    };
    assert_eq!(
        outbox.enqueue(second),
        Err(OperationError::CapacityExceeded {
            resource: "reference outbox",
            maximum: 1,
        })
    );
}


fn operation_intent() -> OperationIntent {
    OperationIntent {
        key: OperationKey {
            id: stable_id("operation:bound:1"),
            payload_digest: Digest32::of_bytes(b"bound-payload"),
        },
        scope: stable_id("scope:bound"),
        owner: stable_id("owner:bound"),
        destination: stable_id("cognitive.store"),
        expected_predecessor: Some(Digest32::of_bytes(b"predecessor")),
    }
}

#[test]
fn bound_outbox_rejects_operation_semantic_drift() {
    let operation = operation_intent();
    let mut ledger = OperationLedger::default();
    assert!(ledger.prepare(operation.clone(), generation(4)).is_ok());
    let record = ledger.get(&operation.key.id).expect("prepared operation");

    let bound = OutboxIntent::for_operation(stable_id("intent:bound:1"), &operation);
    let mut outbox = Outbox::default();
    assert_eq!(outbox.enqueue_for_operation(record, bound.clone()), Ok(()));

    let mut changed_destination = bound.clone();
    changed_destination.destination = stable_id("prompt.registry");
    assert_eq!(
        outbox.enqueue_for_operation(record, changed_destination),
        Err(OperationError::OperationBindingMismatch(bound.intent_id.clone()))
    );

    let mut changed_digest = bound.clone();
    changed_digest.operation_digest = Digest32::of_bytes(b"wrong-operation");
    assert_eq!(
        outbox.enqueue_for_operation(record, changed_digest),
        Err(OperationError::OperationBindingMismatch(bound.intent_id))
    );
}

#[test]
fn leased_claim_expires_and_strictly_newer_generation_can_take_over() {
    let intent = intent();
    let mut outbox = Outbox::default();
    assert_eq!(outbox.enqueue(intent.clone()), Ok(()));

    assert!(
        outbox
            .claim_with_lease(&intent.intent_id, generation(4), 1_000, 100)
            .is_ok()
    );
    assert!(matches!(
        outbox.state(&intent.intent_id),
        Some(OutboxState::Claimed {
            owner_generation,
            attempt: 1,
            lease_expires_at_unix_ms: 1_100,
        }) if *owner_generation == generation(4)
    ));

    assert_eq!(
        outbox.claim_with_lease(&intent.intent_id, generation(5), 1_099, 100),
        Err(OperationError::StaleGeneration)
    );
    assert!(
        outbox
            .claim_with_lease(&intent.intent_id, generation(5), 1_100, 100)
            .is_ok()
    );
    assert!(matches!(
        outbox.state(&intent.intent_id),
        Some(OutboxState::Claimed {
            owner_generation,
            attempt: 2,
            lease_expires_at_unix_ms: 1_200,
        }) if *owner_generation == generation(5)
    ));

    let ack = Digest32::of_bytes(b"takeover-ack");
    assert_eq!(
        outbox.acknowledge_claim(&intent.intent_id, generation(4), 1, 1_101, ack),
        Err(OperationError::StaleGeneration)
    );
    assert_eq!(
        outbox.acknowledge_claim(&intent.intent_id, generation(5), 1, 1_101, ack),
        Err(OperationError::StaleClaim)
    );
    assert_eq!(
        outbox.acknowledge_claim(&intent.intent_id, generation(5), 2, 1_200, ack),
        Err(OperationError::LeaseExpired)
    );
    assert_eq!(
        outbox.acknowledge_claim(&intent.intent_id, generation(5), 2, 1_199, ack),
        Ok(())
    );
}

#[test]
fn leased_claim_requires_timestamped_ack_and_supports_renewal() {
    let intent = intent();
    let mut outbox = Outbox::default();
    assert_eq!(outbox.enqueue(intent.clone()), Ok(()));
    assert!(
        outbox
            .claim_with_lease(&intent.intent_id, generation(7), 10_000, 500)
            .is_ok()
    );
    assert_eq!(
        outbox.acknowledge(
            &intent.intent_id,
            generation(7),
            Digest32::of_bytes(b"legacy-ack"),
        ),
        Err(OperationError::LeaseTimeRequired)
    );
    assert!(
        outbox
            .renew_claim(&intent.intent_id, generation(7), 1, 10_100, 1_000)
            .is_ok()
    );
    assert!(matches!(
        outbox.state(&intent.intent_id),
        Some(OutboxState::Claimed {
            attempt: 1,
            lease_expires_at_unix_ms: 11_100,
            ..
        })
    ));
}
