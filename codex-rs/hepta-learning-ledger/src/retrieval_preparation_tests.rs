use super::*;
use crate::AppendDisposition;
use crate::CandidateSetCompleteness;
use crate::LearningLedger;

fn must<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("preparation fixture failed: {error:?}"),
    }
}

fn preparation() -> RetrievalPreparationFactV1 {
    RetrievalPreparationFactV1 {
        assignment: RetrievalAssignmentFact {
            record_id: must(StableId::new("preparation-1")),
            episode_id: must(StableId::new("retrieval-episode-1")),
            cue_digest: Digest32::of_bytes(b"cue"),
            policy_digest: Digest32::of_bytes(b"policy"),
            source_completeness_digest: Digest32::of_bytes(b"completeness"),
            candidate_union_digest: Digest32::of_bytes(b"union"),
            recall_packet_digest: Digest32::of_bytes(b"packet"),
            enumerated_candidate_digests: vec![
                Digest32::of_bytes(b"candidate-b"),
                Digest32::of_bytes(b"candidate-a"),
            ],
            legal_candidate_indices: vec![0, 1],
            selected_candidate_indices: vec![0, 1],
            delivered_candidate_indices: Vec::new(),
            context_exposed: false,
            published_context_digest: None,
            omitted_by_policy_limits: 0,
            assignment_propensity: ProbabilityQ32::ONE,
            downstream_policy_digest: None,
            delivery_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: Digest32::of_bytes(b"support"),
        },
        prepared_candidate_indices: vec![1, 0],
        prepared_context_digest: Some(Digest32::of_bytes(b"exact-response")),
    }
}

#[test]
fn preparation_replay_preserves_order_without_asserting_exposure() {
    let prepared = preparation();
    let expected_order = prepared
        .prepared_candidate_indices
        .iter()
        .map(|index| prepared.assignment.enumerated_candidate_digests[*index as usize])
        .collect::<Vec<_>>();
    let event = LedgerEvent::RetrievalPrepared(prepared.clone());
    let mut ledger = LearningLedger::new();
    let first = must(ledger.append(event.clone()));
    let replay = must(ledger.append(event));
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(first.chain_digest, replay.chain_digest);
    assert_eq!(ledger.records().len(), 1);
    let LedgerEvent::RetrievalPrepared(actual) = &ledger.records()[0].event else {
        panic!("prepared evidence changed its event kind");
    };
    assert!(!actual.assignment.context_exposed);
    assert!(actual.assignment.delivered_candidate_indices.is_empty());
    assert!(actual.assignment.published_context_digest.is_none());
    assert_eq!(
        actual.prepared_context_digest,
        prepared.prepared_context_digest
    );
    let actual_order = actual
        .prepared_candidate_indices
        .iter()
        .map(|index| actual.assignment.enumerated_candidate_digests[*index as usize])
        .collect::<Vec<_>>();
    assert_eq!(actual_order, expected_order);
    let mut reordered = prepared;
    reordered.prepared_candidate_indices.reverse();
    assert!(matches!(
        ledger.append(LedgerEvent::RetrievalPrepared(reordered)),
        Err(LedgerError::IdentityConflict(_))
    ));
}

#[test]
fn preparation_codec_is_distinct_and_legacy_exposure_is_not_reinterpreted() {
    let prepared = preparation();
    let legacy = LedgerEvent::RetrievalAssignment(prepared.wire_assignment());
    let event = LedgerEvent::RetrievalPrepared(prepared);
    let encoded = crate::ledger::encode_event(&event);
    let legacy_encoded = crate::ledger::encode_event(&legacy);
    let tag_offset = b"hepta.learning-ledger.event.v1".len();
    assert_eq!(encoded[tag_offset], 10);
    assert_eq!(legacy_encoded[tag_offset], 9);
    assert_ne!(
        Digest32::of_bytes(&encoded),
        Digest32::of_bytes(&legacy_encoded)
    );
    assert_eq!(must(crate::durable_codec::decode_event(&encoded)), event);
    assert_eq!(
        must(crate::durable_codec::decode_event(&legacy_encoded)),
        legacy
    );
    for length in 0..encoded.len() {
        assert!(
            crate::durable_codec::decode_event(&encoded[..length]).is_err(),
            "truncated preparation decoded at {length}"
        );
    }
}

#[test]
fn preparation_rejects_forged_exposure_fields_and_oversized_vectors() {
    for mutation in 0..4 {
        let mut prepared = preparation();
        match mutation {
            0 => prepared.assignment.context_exposed = true,
            1 => prepared.assignment.delivered_candidate_indices.push(0),
            2 => prepared.assignment.published_context_digest = Some(Digest32::of_bytes(b"fake")),
            3 => prepared.prepared_candidate_indices = vec![0; 17],
            _ => unreachable!(),
        }
        assert!(
            LearningLedger::new()
                .append(LedgerEvent::RetrievalPrepared(prepared))
                .is_err()
        );
    }
}

#[test]
fn malformed_preparation_wire_cannot_discard_an_inconsistent_state_bit() {
    let mut shape = preparation().wire_assignment();
    shape.context_exposed = false;
    let mut bytes = crate::ledger::encode_event(&LedgerEvent::RetrievalAssignment(shape));
    bytes[b"hepta.learning-ledger.event.v1".len()] = 10;
    assert!(crate::durable_codec::decode_event(&bytes).is_err());
}
