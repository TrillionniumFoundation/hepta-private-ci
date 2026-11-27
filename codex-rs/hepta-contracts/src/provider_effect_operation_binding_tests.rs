use super::*;
use pretty_assertions::assert_eq;

fn quarantined_operation() -> (
    ProviderEffectJournal,
    ProviderEffectIntent,
    ProviderEffectAck,
) {
    let intent = ProviderEffectIntent::new(
        ProviderEffectKey::for_operation("provider", "run", "step").expect("effect key"),
        Sha256Digest::for_bytes(b"exact payload"),
    );
    let accepted = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"original provider operation"),
        ProviderEffectAckStatus::Accepted,
    );
    let mut journal = ProviderEffectJournal::default();
    journal.record_intent(intent.clone()).expect("intent");
    journal.record_ack(accepted.clone()).expect("accepted");
    journal
        .mark_indeterminate(&intent.key, "provider_lookup_unknown")
        .expect("quarantine");
    (journal, intent, accepted)
}

#[test]
fn operation_binding_unknown_never_allows_a_different_provider_operation() {
    for status in [
        ProviderEffectAckStatus::Accepted,
        ProviderEffectAckStatus::Completed,
    ] {
        let (mut journal, intent, accepted) = quarantined_operation();
        let before = journal.clone();
        let substituted = ProviderEffectStatusObservation::new(
            intent.key.clone(),
            intent.payload_sha256.clone(),
            Sha256Digest::for_bytes(b"different provider operation"),
            status,
        );
        assert_eq!(
            journal.record_status_observation(substituted),
            Err(ProviderEffectBindingError::AckConflict)
        );
        assert_eq!(journal, before);
        assert_eq!(
            journal.state(&intent.key),
            Some(ProviderEffectState::Indeterminate)
        );

        // Rejection must preserve a usable journal. A later lookup for the
        // original accepted operation may still close the lost-response gap.
        let encoded = serde_json::to_vec(&journal).expect("encode quarantine");
        let mut reopened: ProviderEffectJournal =
            serde_json::from_slice(&encoded).expect("reopen quarantine");
        let completion = ProviderEffectStatusObservation::new(
            intent.key.clone(),
            intent.payload_sha256,
            accepted.provider_operation_id_sha256,
            ProviderEffectAckStatus::Completed,
        );
        assert_eq!(
            reopened.reconcile_status_observation(completion),
            Ok(ProviderEffectState::Completed)
        );
    }
}

#[test]
fn operation_binding_reopen_rejects_rebinding_hidden_after_uncertainty() {
    let (mut journal, intent, accepted) = quarantined_operation();
    let completion = ProviderEffectStatusObservation::new(
        intent.key.clone(),
        intent.payload_sha256,
        accepted.provider_operation_id_sha256,
        ProviderEffectAckStatus::Completed,
    );
    journal
        .record_status_observation(completion)
        .expect("original operation completed");

    // Model an imported journal that is internally shaped correctly, with
    // matching ACK/status provenance, but substitutes another operation ID.
    let substituted = Sha256Digest::for_bytes(b"different provider operation");
    journal
        .acknowledgements
        .get_mut(intent.key.as_str())
        .expect("acknowledgements")
        .last_mut()
        .expect("completed acknowledgement")
        .provider_operation_id_sha256 = substituted.clone();
    journal
        .status_observations
        .get_mut(intent.key.as_str())
        .expect("status observations")
        .last_mut()
        .expect("completed status")
        .provider_operation_id_sha256 = substituted;

    assert_eq!(
        journal.validate(),
        Err(ProviderEffectBindingError::AckConflict)
    );
    let encoded = serde_json::to_vec(&journal).expect("encode imported journal");
    assert!(serde_json::from_slice::<ProviderEffectJournal>(&encoded).is_err());
    assert_eq!(
        journal.state(&intent.key),
        Some(ProviderEffectState::Indeterminate)
    );
}
