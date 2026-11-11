//! Test-only crash boundaries on actual retained source and original journals.
//! These helpers never construct a completed task or a Ready capability.

use super::*;

pub(crate) fn retained_decision(
    producer: &OriginalCellQ24TaskLedgerProducerV1,
) -> Result<SignedLearningEvidenceV1, Error> {
    let mut state = producer
        .state
        .lock()
        .map_err(|_| Error::Binding("test owner lock"))?;
    let bytes = state.journal.read(&producer.decision_key)?;
    Ok(binding::decode(&bytes)?.2)
}

pub(crate) fn save_decision_before_ledger(
    producer: &OriginalCellQ24TaskLedgerProducerV1,
) -> Result<SignedLearningEvidenceV1, Error> {
    let mut state = producer
        .state
        .lock()
        .map_err(|_| Error::Binding("test owner lock"))?;
    let captured = producer.capture(&mut state)?;
    let ledger = producer
        .ledger
        .lock()
        .map_err(|_| Error::Binding("test ledger lock"))?;
    producer.require_ledger(&ledger)?;
    let cut = witnessed_snapshot(&ledger)?;
    let payload = decision_signing_payload_v2(&captured.decision)?;
    let State { journal, key, .. } = &mut *state;
    let bytes = journal.commit_once(&producer.decision_key, || {
        producer.require_source(&captured).map_err(owner_binding)?;
        let signed = binding::sign(producer, &ledger, key, &payload).map_err(owner_binding)?;
        binding::encode(cut.head_digest, &payload, &signed)
    })?;
    Ok(binding::decode(&bytes)?.2)
}

pub(crate) fn save_outcome_before_ledger(
    producer: &OriginalCellQ24TaskLedgerProducerV1,
    outcome: &AuthenticatedOutcomeV1,
    signed: &SignedLearningEvidenceV1,
) -> Result<(), Error> {
    if !matches!(
        producer.readback()?,
        OriginalCellQ24TaskLedgerStatusV1::AwaitingOutcome { .. }
    ) {
        return Err(Error::Binding("test crash needs original Decision"));
    }
    let mut state = producer
        .state
        .lock()
        .map_err(|_| Error::Binding("test owner lock"))?;
    let captured = producer.capture(&mut state)?;
    let ledger = producer
        .ledger
        .lock()
        .map_err(|_| Error::Binding("test ledger lock"))?;
    let cut = witnessed_snapshot(&ledger)?;
    ledger.validate_observed_outcome(outcome, signed, now()?)?;
    let payload = outcome_signing_payload_v2(outcome);
    state.journal.commit_once(&producer.outcome_key, || {
        producer.require_source(&captured).map_err(owner_binding)?;
        binding::encode(cut.head_digest, &payload, signed)
    })?;
    Ok(())
}

pub(crate) fn leave_generator_claim_pending(
    producer: &OriginalCellQ24TaskLedgerProducerV1,
) -> Result<(), Error> {
    let mut state = producer
        .state
        .lock()
        .map_err(|_| Error::Binding("test owner lock"))?;
    let captured = producer.capture(&mut state)?;
    producer.require_source(&captured)?;
    let result = state.journal.commit_once(&producer.decision_key, || {
        Err(LearningOriginalOwnerErrorV1::Binding(
            "test crash after original durable claim",
        ))
    });
    match result {
        Err(LearningOriginalOwnerErrorV1::Binding("test crash after original durable claim")) => {
            Ok(())
        }
        _ => Err(Error::Binding("test did not stop at durable Pending")),
    }
}

#[test]
fn original_outcome_codec_rejects_truncation_trailing_and_unknown_tags()
-> Result<(), Box<dyn std::error::Error>> {
    let principal = AuthenticatedPrincipalV1 {
        principal_id: StableId::new("observer")?,
        credential_chain_digest: Digest32::of_bytes(b"chain"),
        signing_key_digest: Digest32::of_bytes(b"key"),
        scope_digest: Digest32::of_bytes(b"scope"),
        authority_epoch: 7,
        authenticated_at: 10,
        expires_at: 100,
    };
    let outcome = AuthenticatedOutcomeV1 {
        record_id: StableId::new("record")?,
        outcome_id: StableId::new("outcome")?,
        episode_id: StableId::new("episode")?,
        observer: principal,
        observed_at: Some(20),
        value: Some(codex_hepta_types::FixedQ32::from_raw(2_i64 << 32)),
        unit_profile_digest: Digest32::of_bytes(b"unit"),
        support_digest: Digest32::of_bytes(b"support"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 20,
            expected_delay_profile_digest: Digest32::of_bytes(b"delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(20),
        },
    };
    let encoded = outcome_signing_payload_v2(&outcome);
    assert!(outcome_codec::decode(&encoded)? == outcome);
    for length in 0..encoded.len() {
        assert!(outcome_codec::decode(&encoded[..length]).is_err());
    }
    let mut trailing = encoded.clone();
    trailing.push(0);
    assert!(outcome_codec::decode(&trailing).is_err());
    let mut unknown = encoded;
    let terminal = unknown.len() - 12;
    unknown[terminal] = 255;
    assert!(outcome_codec::decode(&unknown).is_err());
    Ok(())
}

/// An explicitly synthetic, authenticated unrelated Ledger event advances the
/// fixture cut. It creates no original task, Dataset row or Ready capability.
pub(crate) fn append_unrelated_decision(
    producer: &OriginalCellQ24TaskLedgerProducerV1,
) -> Result<(), Error> {
    use ed25519_dalek::Signer;

    let mut state = producer
        .state
        .lock()
        .map_err(|_| Error::Binding("test owner lock"))?;
    let captured = producer.capture(&mut state)?;
    let mut decision = captured.decision;
    decision.record_id =
        StableId::new("fixture-unrelated-decision").map_err(|_| Error::Binding("test id"))?;
    decision.episode_id =
        StableId::new("fixture-unrelated-episode").map_err(|_| Error::Binding("test id"))?;
    decision.completeness.set_id =
        StableId::new("fixture-unrelated-set").map_err(|_| Error::Binding("test id"))?;
    let mut ledger = producer
        .ledger
        .lock()
        .map_err(|_| Error::Binding("test ledger lock"))?;
    let predecessor = witnessed_snapshot(&ledger)?.head_digest;
    let payload = decision_signing_payload_v2(&decision)?;
    let mut signed = binding::sign(producer, &ledger, &state.key, &payload)?;
    signed.evidence_id =
        StableId::new("fixture-unrelated-evidence").map_err(|_| Error::Binding("test id"))?;
    signed.signature = state.key.sign(&signed.signing_bytes()).to_bytes();
    ledger.append_decision(predecessor, decision, &signed, now()?)?;
    Ok(())
}
