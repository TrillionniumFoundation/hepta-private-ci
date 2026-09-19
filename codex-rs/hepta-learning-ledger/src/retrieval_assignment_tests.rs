use super::*;

use codex_hepta_memory_retrieval::RetrievalAssignmentCompletenessV1;
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;

use crate::AppendDisposition;
use crate::CandidateSetCompleteness;
use crate::LearningLedger;
use crate::RetrievalAssignmentFact;
use crate::ledger::encode_event;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn candidate(number: u64) -> RetrievalCandidateIdentityV1 {
    RetrievalCandidateIdentityV1 {
        record_id: id(&format!("memory:{number:04}")),
        record_revision: Revision::new(1).expect("revision"),
        record_digest: digest(&format!("record:{number:04}")),
    }
}

fn observation(count: usize, complete: bool) -> RetrievalAssignmentObservationV1 {
    let mut enumerated_candidates = (0..count)
        .map(|index| candidate(u64::try_from(index).expect("index")))
        .collect::<Vec<_>>();
    enumerated_candidates.sort();
    let legal_candidates = enumerated_candidates.clone();
    let selected_candidates = legal_candidates.iter().take(16).cloned().collect();
    let mut value = RetrievalAssignmentObservationV1 {
        cue_digest: digest("cue"),
        policy_digest: digest("policy"),
        source_completeness_digest: digest("source-completeness"),
        candidate_union_digest: digest("union"),
        recall_packet_digest: digest("packet"),
        enumerated_candidates,
        legal_candidates,
        selected_candidates,
        omitted_by_policy_limits: 0,
        completeness: if complete {
            RetrievalAssignmentCompletenessV1::Complete
        } else {
            RetrievalAssignmentCompletenessV1::GeneratorRelativeIncomplete
        },
        assignment_propensity: ProbabilityQ32::ONE,
        observation_digest: Digest32::ZERO,
        authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
    };
    value.observation_digest = value.compute_observation_digest();
    value.validate().expect("observation");
    value
}

#[test]
fn bridge_preserves_complete_and_incomplete_assignment_facts() {
    for (complete, expected) in [
        (true, CandidateSetCompleteness::Complete),
        (false, CandidateSetCompleteness::Incomplete),
    ] {
        let event = retrieval_assignment_event(
            id(if complete {
                "record:complete"
            } else {
                "record:incomplete"
            }),
            id("episode:retrieval"),
            &observation(3, complete),
        )
        .expect("bridge");
        let LedgerEvent::RetrievalAssignment(fact) = &event else {
            panic!("retrieval assignment event");
        };
        assert_eq!(fact.completeness, expected);
        assert_eq!(fact.enumerated_candidate_digests.len(), 3);
        assert_eq!(fact.legal_candidate_indices, vec![0, 1, 2]);
        assert_eq!(fact.selected_candidate_indices, vec![0, 1, 2]);
        assert_eq!(fact.delivered_candidate_indices, vec![0, 1, 2]);
        assert!(fact.context_exposed);

        let mut ledger = LearningLedger::new();
        let first = ledger.append(event.clone()).expect("append");
        let replay = ledger.append(event).expect("idempotent");
        assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
        assert_eq!(replay.event_digest, first.event_digest);
    }
}

#[test]
fn maximum_retrieval_assignment_fits_existing_bounded_event_frame() {
    let event =
        retrieval_assignment_event(id("record:max"), id("episode:max"), &observation(512, true))
            .expect("bridge");
    let encoded = encode_event(&event);
    assert!(encoded.len() <= crate::durable_codec::MAX_EVENT);
    let LedgerEvent::RetrievalAssignment(fact) = event else {
        panic!("retrieval assignment");
    };
    assert_eq!(fact.enumerated_candidate_digests.len(), 512);
    assert_eq!(fact.legal_candidate_indices.len(), 512);
    assert_eq!(fact.selected_candidate_indices.len(), 16);
    assert_eq!(fact.delivered_candidate_indices.len(), 16);
    assert!(fact.context_exposed);
}

#[test]
fn delivery_aware_bridge_binds_only_the_final_exposed_subset() {
    let observation = observation(20, true);
    let delivered = vec![observation.selected_candidates[3].clone()];
    let event = retrieval_assignment_event_with_delivery(
        id("record:delivery"),
        id("episode:delivery"),
        &observation,
        &delivered,
        true,
    )
    .expect("delivery-aware bridge");
    let LedgerEvent::RetrievalAssignment(fact) = event else {
        panic!("retrieval assignment");
    };
    assert_eq!(fact.delivered_candidate_indices.len(), 1);
    assert!(fact.selected_candidate_indices.len() > fact.delivered_candidate_indices.len());
    assert!(fact.context_exposed);

    let no_exposure = retrieval_assignment_event_with_delivery(
        id("record:no-exposure"),
        id("episode:no-exposure"),
        &observation,
        &[],
        false,
    )
    .expect("no exposure");
    let LedgerEvent::RetrievalAssignment(fact) = no_exposure else {
        panic!("retrieval assignment");
    };
    assert!(fact.delivered_candidate_indices.is_empty());
    assert!(!fact.context_exposed);

    assert_eq!(
        retrieval_assignment_event_with_delivery(
            id("record:invalid-exposure"),
            id("episode:invalid-exposure"),
            &observation,
            &[observation.legal_candidates[19].clone()],
            true,
        ),
        Err(RetrievalAssignmentBridgeError::DeliveredCandidateOutsideSelection)
    );
}

#[test]
fn owner_bridge_uses_canonical_digest_indices_not_input_positions() {
    let mut noncanonical = observation(3, true);
    noncanonical.enumerated_candidates.reverse();
    noncanonical.legal_candidates.reverse();
    noncanonical.selected_candidates.reverse();
    noncanonical.observation_digest = noncanonical.compute_observation_digest();
    assert!(noncanonical.validate().is_err());

    let canonical = observation(3, true);
    let event =
        retrieval_assignment_event(id("record:canonical"), id("episode:canonical"), &canonical)
            .expect("bridge");
    let LedgerEvent::RetrievalAssignment(RetrievalAssignmentFact {
        enumerated_candidate_digests,
        legal_candidate_indices,
        ..
    }) = event
    else {
        panic!("retrieval assignment");
    };
    assert!(
        enumerated_candidate_digests
            .windows(2)
            .all(|pair| pair[0] < pair[1])
    );
    assert_eq!(legal_candidate_indices, vec![0, 1, 2]);
}
