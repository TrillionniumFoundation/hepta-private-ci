use super::*;

use codex_hepta_memory_retrieval::RetrievalAssignmentCompletenessV1;
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Revision;

use crate::AppendDisposition;
use crate::RetrievalAssignmentBridgeError;
use crate::RetrievalAssignmentFact;
use crate::Revocation;
use crate::build_ledger_index_checkpoint;
use crate::retrieval_assignment_intent_v2;
use crate::verify_ledger_index_checkpoint;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn observation(count: usize) -> RetrievalAssignmentObservationV1 {
    let mut candidates = (0..count)
        .map(|index| RetrievalCandidateIdentityV1 {
            record_id: id(&format!("memory:{index:04}")),
            record_revision: Revision::new(1).unwrap(),
            record_digest: digest(&format!("memory:{index:04}")),
        })
        .collect::<Vec<_>>();
    candidates.sort();
    let mut value = RetrievalAssignmentObservationV1 {
        cue_digest: digest("cue"),
        policy_digest: digest("policy"),
        source_completeness_digest: digest("complete"),
        candidate_union_digest: digest("union"),
        recall_packet_digest: digest("packet"),
        legal_candidates: candidates.clone(),
        selected_candidates: candidates.iter().take(16).cloned().collect(),
        enumerated_candidates: candidates,
        omitted_by_policy_limits: 0,
        completeness: RetrievalAssignmentCompletenessV1::Complete,
        assignment_propensity: ProbabilityQ32::ONE,
        observation_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    value.observation_digest = value.compute_observation_digest();
    value
}

pub(crate) fn intent(request_id: u64) -> RetrievalAssignmentIntentV2 {
    let observation = observation(2);
    let frame = b"{\"context\":\"qualification-fixture\"}\n";
    retrieval_assignment_intent_v2(
        id("owner"),
        1,
        request_id,
        &observation,
        &observation.selected_candidates[..1],
        digest("snapshot"),
        RETRIEVAL_PUBLICATION_CONTROL_SCHEMA_VERSION_V2,
        Digest32::of_bytes(frame),
        u32::try_from(frame.len()).unwrap(),
        Some(digest("downstream")),
        ProbabilityQ32::ONE,
    )
    .unwrap()
}

pub(crate) fn legacy(request_id: u64, exposed: bool) -> RetrievalAssignmentFact {
    let planned = intent(request_id);
    let mut identity = b"hepta.agentd.retrieval-assignment.v1".to_vec();
    identity.extend_from_slice(&5_u64.to_be_bytes());
    identity.extend_from_slice(b"owner");
    identity.extend_from_slice(&1_u64.to_be_bytes());
    identity.extend_from_slice(&request_id.to_be_bytes());
    RetrievalAssignmentFact {
        record_id: id(&format!(
            "retrieval-assignment:{}",
            Digest32::of_bytes(&identity)
        )),
        episode_id: planned.episode_id,
        cue_digest: planned.cue_digest,
        policy_digest: planned.policy_digest,
        source_completeness_digest: planned.source_completeness_digest,
        candidate_union_digest: planned.candidate_union_digest,
        recall_packet_digest: planned.recall_packet_digest,
        enumerated_candidate_digests: planned.enumerated_candidate_digests,
        legal_candidate_indices: planned.legal_candidate_indices,
        selected_candidate_indices: planned.selected_candidate_indices,
        delivered_candidate_indices: if exposed {
            planned.planned_candidate_indices
        } else {
            Vec::new()
        },
        context_exposed: exposed,
        published_context_digest: exposed.then_some(planned.snapshot_digest),
        omitted_by_policy_limits: planned.omitted_by_policy_limits,
        assignment_propensity: planned.assignment_propensity,
        downstream_policy_digest: planned.downstream_policy_digest,
        delivery_propensity: planned.delivery_propensity,
        completeness: planned.completeness,
        support_digest: planned.support_digest,
    }
}

#[test]
fn intent_is_unknown_request_zero_is_legal_and_identity_excludes_itself() {
    let value = intent(0);
    let mut without_identity = value.clone();
    without_identity.record_id = id("placeholder-does-not-enter-identity");
    assert_eq!(
        value.record_id,
        retrieval_assignment_record_id_v2(&without_identity).unwrap()
    );
    assert_ne!(value.record_id, legacy(0, false).record_id);
    let mut ledger = LearningLedger::new();
    assert!(
        ledger
            .retrieval_publication(&value.record_id)
            .unwrap()
            .is_none()
    );
    let receipt = ledger
        .append(LedgerEvent::RetrievalAssignmentIntentV2(value.clone()))
        .unwrap();
    let projection = ledger
        .retrieval_publication(&value.record_id)
        .unwrap()
        .unwrap();
    assert_eq!(projection.state, RetrievalPublicationStateV2::Unknown);
    assert_eq!(projection.intent_event_digest, Some(receipt.event_digest));
    assert!(!projection.ledger_lineage_active);
    assert_eq!(projection.confirmation_event_digest, None);
}

#[test]
fn canonical_remapping_preserves_planned_identity_and_exact_retry() {
    let value = intent(1);
    let mut shuffled = value.clone();
    shuffled.enumerated_candidate_digests.reverse();
    for indices in [
        &mut shuffled.legal_candidate_indices,
        &mut shuffled.selected_candidate_indices,
        &mut shuffled.planned_candidate_indices,
    ] {
        for index in indices.iter_mut() {
            *index = 1 - *index;
        }
        indices.reverse();
    }
    let mut ledger = LearningLedger::new();
    let first = ledger
        .append(LedgerEvent::RetrievalAssignmentIntentV2(shuffled))
        .unwrap();
    let retry = ledger
        .append(LedgerEvent::RetrievalAssignmentIntentV2(value))
        .unwrap();
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(retry.event_digest, first.event_digest);
    assert_eq!(ledger.records().len(), 1);
}

#[test]
fn intent_rejects_identity_schema_size_and_snapshot_drift() {
    let valid = intent(2);
    let mut invalid = Vec::new();
    let mut value = valid.clone();
    value.owner_id = id("other-owner");
    invalid.push(value);
    let mut value = valid.clone();
    value.body_generation = 2;
    invalid.push(value);
    let mut value = valid.clone();
    value.body_generation = 0;
    invalid.push(value);
    let mut value = valid.clone();
    value.request_id = 3;
    invalid.push(value);
    let mut value = valid.clone();
    value.episode_id = id("another-episode");
    invalid.push(value);
    for schema in [0, 1, 3, u32::MAX] {
        let mut value = valid.clone();
        value.control_schema_version = schema;
        invalid.push(value);
    }
    for size in [0, RETRIEVAL_PUBLICATION_MAX_FRAME_BYTES_V2 + 1] {
        let mut value = valid.clone();
        value.response_frame_bytes = size;
        invalid.push(value);
    }
    let mut value = valid.clone();
    value.snapshot_digest = Digest32::ZERO;
    invalid.push(value);
    let mut value = valid;
    value.response_frame_digest = Digest32::ZERO;
    invalid.push(value);
    for value in invalid {
        assert!(
            LearningLedger::new()
                .append(LedgerEvent::RetrievalAssignmentIntentV2(value))
                .is_err()
        );
    }
}

#[test]
fn intent_bounds_and_selection_subset_are_validated_without_legacy_exposure() {
    let mut invalid = intent(3);
    invalid.planned_candidate_indices = vec![2];
    assert_eq!(
        LearningLedger::new().append(LedgerEvent::RetrievalAssignmentIntentV2(invalid)),
        Err(LedgerError::RetrievalIndexOutOfRange)
    );
    let mut invalid = intent(3);
    invalid.planned_candidate_indices = vec![0, 0];
    assert_eq!(
        LearningLedger::new().append(LedgerEvent::RetrievalAssignmentIntentV2(invalid)),
        Err(LedgerError::DuplicateRetrievalIndex)
    );
    let mut invalid = intent(3);
    invalid.selected_candidate_indices.clear();
    invalid.record_id = retrieval_assignment_record_id_v2(&invalid).unwrap();
    assert_eq!(
        LearningLedger::new().append(LedgerEvent::RetrievalAssignmentIntentV2(invalid)),
        Err(LedgerError::RetrievalDeliveryOutsideSelection)
    );
    let mut invalid = intent(3);
    invalid.legal_candidate_indices.resize(513, 0);
    assert_eq!(
        LearningLedger::new().append(LedgerEvent::RetrievalAssignmentIntentV2(invalid)),
        Err(LedgerError::RetrievalCandidateLimitExceeded)
    );
    let mut empty = intent(3);
    empty.planned_candidate_indices.clear();
    empty.record_id = retrieval_assignment_record_id_v2(&empty).unwrap();
    let mut ledger = LearningLedger::new();
    let receipt = ledger
        .append(LedgerEvent::RetrievalAssignmentIntentV2(empty.clone()))
        .unwrap();
    let confirmation = retrieval_publication_confirmation_v2(&empty, receipt.event_digest).unwrap();
    ledger
        .append(LedgerEvent::RetrievalPublicationConfirmedV2(confirmation))
        .unwrap();
    assert_eq!(
        ledger
            .retrieval_publication(&empty.record_id)
            .unwrap()
            .unwrap()
            .state,
        RetrievalPublicationStateV2::HostTransportWriteCompleted
    );
}

#[test]
fn bridge_rejects_oversized_legal_and_selected_sets_before_native_validation() {
    let mut oversized_legal = observation(2);
    oversized_legal.legal_candidates = observation(513).legal_candidates;
    let mut oversized_selected = observation(17);
    oversized_selected.selected_candidates = oversized_selected.enumerated_candidates.clone();
    oversized_selected.observation_digest = oversized_selected.compute_observation_digest();
    // The retrieval observation accepts 17 selected candidates; the narrower
    // publication profile must enforce its own limit before bridging identities.
    oversized_selected.validate().unwrap();
    for observation in [oversized_legal, oversized_selected] {
        let result = retrieval_assignment_intent_v2(
            id("owner"),
            1,
            9,
            &observation,
            &[],
            digest("snapshot"),
            RETRIEVAL_PUBLICATION_CONTROL_SCHEMA_VERSION_V2,
            digest("frame"),
            100,
            None,
            ProbabilityQ32::ONE,
        );
        assert_eq!(
            result,
            Err(RetrievalAssignmentBridgeError::CandidateLimitExceeded)
        );
    }
}

#[test]
fn confirmation_requires_exact_existing_intent_and_complete_frame_binding() {
    let value = intent(4);
    let mut ledger = LearningLedger::new();
    let orphan = retrieval_publication_confirmation_v2(&value, digest("orphan")).unwrap();
    assert_eq!(
        ledger.append(LedgerEvent::RetrievalPublicationConfirmedV2(orphan)),
        Err(LedgerError::RetrievalPublicationIntentRequired)
    );
    let receipt = ledger
        .append(LedgerEvent::RetrievalAssignmentIntentV2(value.clone()))
        .unwrap();
    let confirmed = retrieval_publication_confirmation_v2(&value, receipt.event_digest).unwrap();
    let wrong_digest =
        retrieval_publication_confirmation_v2(&value, digest("other-intent")).unwrap();
    let mut wrong_id = confirmed.clone();
    wrong_id.record_id = id("second-confirmation");
    let mut wrong_frame = confirmed.clone();
    wrong_frame.response_frame_digest = digest("error-or-another-request-frame");
    let mut wrong_size = confirmed.clone();
    wrong_size.response_frame_bytes += 1;
    for wrong in [wrong_digest, wrong_id, wrong_frame, wrong_size] {
        assert_eq!(
            ledger.append(LedgerEvent::RetrievalPublicationConfirmedV2(wrong)),
            Err(LedgerError::RetrievalPublicationBindingMismatch)
        );
    }
    let first = ledger
        .append(LedgerEvent::RetrievalPublicationConfirmedV2(
            confirmed.clone(),
        ))
        .unwrap();
    let retry = ledger
        .append(LedgerEvent::RetrievalPublicationConfirmedV2(
            confirmed.clone(),
        ))
        .unwrap();
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(retry.event_digest, first.event_digest);
    let mut changed = confirmed;
    changed.response_frame_bytes += 1;
    assert!(matches!(
        ledger.append(LedgerEvent::RetrievalPublicationConfirmedV2(changed)),
        Err(LedgerError::IdentityConflict(_))
    ));
    let projection = ledger
        .retrieval_publication(&value.record_id)
        .unwrap()
        .unwrap();
    assert_eq!(
        projection.state,
        RetrievalPublicationStateV2::HostTransportWriteCompleted
    );
    assert!(projection.ledger_lineage_active);
}

#[test]
fn withdrawal_does_not_erase_or_prevent_historical_transport_confirmation() {
    for revoke_before_confirmation in [true, false] {
        let value = intent(5);
        let mut ledger = LearningLedger::new();
        let receipt = ledger
            .append(LedgerEvent::RetrievalAssignmentIntentV2(value.clone()))
            .unwrap();
        let confirmation =
            retrieval_publication_confirmation_v2(&value, receipt.event_digest).unwrap();
        let revoke = LedgerEvent::Revocation(Revocation {
            record_id: id("withdraw-intent"),
            target_record_id: value.record_id.clone(),
            authority_id: id("privacy-owner"),
            reason_digest: digest("withdrawn"),
        });
        if revoke_before_confirmation {
            ledger.append(revoke.clone()).unwrap();
        }
        ledger
            .append(LedgerEvent::RetrievalPublicationConfirmedV2(confirmation))
            .unwrap();
        if !revoke_before_confirmation {
            ledger.append(revoke).unwrap();
        }
        let projection = ledger
            .retrieval_publication(&value.record_id)
            .unwrap()
            .unwrap();
        assert_eq!(
            projection.state,
            RetrievalPublicationStateV2::HostTransportWriteCompleted
        );
        assert!(!projection.ledger_lineage_active);
        assert!(ledger.active_records().iter().all(|record| !matches!(
            record.event,
            LedgerEvent::RetrievalAssignmentIntentV2(_)
                | LedgerEvent::RetrievalPublicationConfirmedV2(_)
        )));
        let reopened = LearningLedger::from_snapshot(ledger.snapshot()).unwrap();
        assert_eq!(
            reopened
                .retrieval_publication(&value.record_id)
                .unwrap()
                .unwrap(),
            projection
        );
    }
}

#[test]
fn legacy_true_and_false_remain_unqualified_beside_new_v2_intents() {
    for exposed in [true, false] {
        let legacy = legacy(6, exposed);
        let value = intent(6);
        let mut ledger = LearningLedger::new();
        let receipt = ledger
            .append(LedgerEvent::RetrievalAssignment(legacy.clone()))
            .unwrap();
        let projection = ledger
            .retrieval_publication(&legacy.record_id)
            .unwrap()
            .unwrap();
        assert_eq!(
            projection.state,
            RetrievalPublicationStateV2::LegacyOwnerAsserted
        );
        assert!(!projection.ledger_lineage_active);
        assert_ne!(legacy.record_id, value.record_id);
        ledger
            .append(LedgerEvent::RetrievalAssignmentIntentV2(value.clone()))
            .unwrap();
        assert_eq!(
            ledger
                .retrieval_publication(&value.record_id)
                .unwrap()
                .unwrap()
                .state,
            RetrievalPublicationStateV2::Unknown
        );
        let mut fake_intent = value;
        fake_intent.record_id = legacy.record_id.clone();
        let confirmation =
            retrieval_publication_confirmation_v2(&fake_intent, receipt.event_digest).unwrap();
        assert_eq!(
            ledger.append(LedgerEvent::RetrievalPublicationConfirmedV2(confirmation)),
            Err(LedgerError::RetrievalPublicationIntentRequired)
        );
        let reopened = LearningLedger::from_snapshot(ledger.snapshot()).unwrap();
        assert_eq!(
            reopened
                .retrieval_publication(&legacy.record_id)
                .unwrap()
                .unwrap(),
            projection
        );
    }
}

#[test]
fn client_local_request_reuse_keeps_distinct_frames_and_semantic_drift_conflicts() {
    let first = intent(1);
    let mut second = first.clone();
    second.response_frame_digest = digest("another-real-response-frame");
    second.snapshot_digest = digest("another-snapshot");
    second.record_id = retrieval_assignment_record_id_v2(&second).unwrap();
    let mut different_cue_same_frame = first.clone();
    different_cue_same_frame.cue_digest = digest("another-query-same-snapshot-and-frame");
    different_cue_same_frame.support_digest = digest("another-causal-assignment");
    different_cue_same_frame.record_id =
        retrieval_assignment_record_id_v2(&different_cue_same_frame).unwrap();
    let mut ledger = LearningLedger::new();
    let receipt_a = ledger
        .append(LedgerEvent::RetrievalAssignmentIntentV2(first.clone()))
        .unwrap();
    let receipt_b = ledger
        .append(LedgerEvent::RetrievalAssignmentIntentV2(second.clone()))
        .unwrap();
    let receipt_c = ledger
        .append(LedgerEvent::RetrievalAssignmentIntentV2(
            different_cue_same_frame.clone(),
        ))
        .unwrap();
    assert_ne!(first.record_id, second.record_id);
    assert_eq!(first.episode_id, second.episode_id);
    assert_ne!(first.record_id, different_cue_same_frame.record_id);
    assert_eq!(
        first.response_frame_digest,
        different_cue_same_frame.response_frame_digest
    );
    let mut changed = first.clone();
    changed.support_digest = digest("changed-observation-same-frame");
    assert!(matches!(
        ledger.append(LedgerEvent::RetrievalAssignmentIntentV2(changed)),
        Err(LedgerError::IdentityConflict(_))
    ));
    for (intent, receipt) in [
        (first, receipt_a),
        (second, receipt_b),
        (different_cue_same_frame, receipt_c),
    ] {
        let confirmation =
            retrieval_publication_confirmation_v2(&intent, receipt.event_digest).unwrap();
        ledger
            .append(LedgerEvent::RetrievalPublicationConfirmedV2(confirmation))
            .unwrap();
        let projection = ledger
            .retrieval_publication(&intent.record_id)
            .unwrap()
            .unwrap();
        assert_eq!(
            projection.state,
            RetrievalPublicationStateV2::HostTransportWriteCompleted
        );
        assert!(projection.ledger_lineage_active);
    }
    assert_eq!(ledger.records().len(), 6);
}

#[test]
fn maximum_intent_codec_and_mixed_checkpoint_preserve_exact_event_kinds() {
    let observation = observation(512);
    let intent = retrieval_assignment_intent_v2(
        id("owner"),
        1,
        7,
        &observation,
        &observation.selected_candidates,
        digest("snapshot"),
        2,
        digest("frame"),
        65536,
        None,
        ProbabilityQ32::ONE,
    )
    .unwrap();
    let event = LedgerEvent::RetrievalAssignmentIntentV2(intent.clone());
    let encoded = crate::ledger::encode_event(&event);
    assert!(encoded.len() <= crate::durable_codec::MAX_EVENT);
    assert_eq!(crate::durable_codec::decode_event(&encoded).unwrap(), event);
    assert!(crate::durable_codec::decode_event(&encoded[..encoded.len() - 1]).is_err());
    let mut trailing = encoded;
    trailing.push(0);
    assert!(crate::durable_codec::decode_event(&trailing).is_err());
    let mut ledger = LearningLedger::new();
    ledger
        .append(LedgerEvent::RetrievalAssignment(legacy(8, true)))
        .unwrap();
    let receipt = ledger.append(event).unwrap();
    let confirmation =
        retrieval_publication_confirmation_v2(&intent, receipt.event_digest).unwrap();
    let event = LedgerEvent::RetrievalPublicationConfirmedV2(confirmation);
    assert_eq!(
        crate::durable_codec::decode_event(&crate::ledger::encode_event(&event)).unwrap(),
        event
    );
    ledger.append(event).unwrap();
    let checkpoint = build_ledger_index_checkpoint(&ledger.snapshot()).unwrap();
    verify_ledger_index_checkpoint(&ledger.snapshot(), &checkpoint).unwrap();
    assert_eq!(checkpoint.lookup(&intent.record_id).unwrap().event_kind, 10);
    let mut kinds = checkpoint
        .entries
        .iter()
        .map(|entry| entry.event_kind)
        .collect::<Vec<_>>();
    kinds.sort();
    assert_eq!(kinds, vec![9, 10, 11]);
}

#[test]
fn legacy_tag_nine_golden_digest_and_shape_are_unchanged() {
    let event = LedgerEvent::RetrievalAssignment(RetrievalAssignmentFact {
        record_id: id("legacy-golden"),
        episode_id: id("legacy-episode"),
        cue_digest: digest("cue"),
        policy_digest: digest("policy"),
        source_completeness_digest: digest("complete"),
        candidate_union_digest: digest("union"),
        recall_packet_digest: digest("packet"),
        enumerated_candidate_digests: Vec::new(),
        legal_candidate_indices: Vec::new(),
        selected_candidate_indices: Vec::new(),
        delivered_candidate_indices: Vec::new(),
        context_exposed: false,
        published_context_digest: None,
        omitted_by_policy_limits: 0,
        assignment_propensity: ProbabilityQ32::ONE,
        downstream_policy_digest: None,
        delivery_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompleteness::Complete,
        support_digest: digest("support"),
    });
    let bytes = crate::ledger::encode_event(&event);
    assert_eq!(bytes.len(), 298);
    assert_eq!(
        Digest32::of_bytes(&bytes).to_string(),
        "ed79f532f79e8526131a818f92f226f4850e8695e34f4b9850b50359de3feb8f"
    );
    assert_eq!(crate::durable_codec::decode_event(&bytes).unwrap(), event);
}
