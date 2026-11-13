use super::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use crate::AuthenticatedDecisionRecordV2;
use crate::AuthenticatedOutcomeRecordV2;
use crate::AuthenticatedOutcomeTerminality;
use crate::CandidateSetCompleteness;
use crate::CreditAllocationBatchRecordV2;
use crate::CreditAllocationRecordV2;
use crate::CreditAssignment;
use crate::EpisodeDecision;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::PromptDeliveryObservation;
use crate::RetrievalAssignmentFact;
use crate::Revocation;
use crate::UnlearningLineageEventV1;

fn must<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn decision(index: usize) -> LedgerEvent {
    LedgerEvent::Decision(EpisodeDecision {
        record_id: id(&format!("decision-{index}")),
        episode_id: id(&format!("episode-{index}")),
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: id("policy"),
        candidate_ids: vec![id("choice"), id("abstain")],
        selected_candidate_id: id("choice"),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(b"decision-support"),
    })
}

fn single_snapshot() -> LedgerSnapshot {
    let mut core = LearningLedger::new();
    must(core.append(decision(/*index*/ 0)));
    core.snapshot()
}

fn complete_snapshot() -> LedgerSnapshot {
    let mut core = LearningLedger::new();
    for event in [
        decision(/*index*/ 0),
        LedgerEvent::PromptDelivery(PromptDeliveryObservation {
            record_id: id("delivery"),
            episode_id: id("episode-0"),
            compilation_id: id("compilation"),
            observer_id: id("runtime-observer"),
            portfolio_receipt_digest: Digest32::of_bytes(b"portfolio"),
            provider_request_digest: Digest32::of_bytes(b"request"),
            delivered: true,
            rejected_reason_digest: None,
            observed_token_positions_digest: Some(Digest32::of_bytes(b"positions")),
            truncation_observed: false,
            context_delivery_observation_digest: Digest32::of_bytes(b"context"),
            support_digest: Digest32::of_bytes(b"delivery"),
        }),
        LedgerEvent::Outcome(OutcomeObservation {
            record_id: id("observation"),
            outcome_id: id("outcome"),
            episode_id: id("episode-0"),
            observer_id: id("observer"),
            value: FixedQ32::ONE,
            finality: OutcomeFinality::Terminal,
            support_digest: Digest32::of_bytes(b"outcome"),
        }),
        LedgerEvent::Credit(CreditAssignment {
            record_id: id("credit-record"),
            credit_id: id("credit"),
            episode_id: id("episode-0"),
            outcome_id: id("outcome"),
            target_artifact_id: id("artifact"),
            allocator_id: id("allocator"),
            credit: FixedQ32::ONE,
            support_digest: Digest32::of_bytes(b"credit"),
        }),
        LedgerEvent::Revocation(Revocation {
            record_id: id("revocation"),
            target_record_id: id("decision-0"),
            authority_id: id("privacy-owner"),
            reason_digest: Digest32::of_bytes(b"revocation"),
        }),
        LedgerEvent::RetrievalAssignment(RetrievalAssignmentFact {
            record_id: id("retrieval"),
            episode_id: id("retrieval-episode"),
            cue_digest: Digest32::of_bytes(b"cue"),
            policy_digest: Digest32::of_bytes(b"retrieval-policy"),
            source_completeness_digest: Digest32::of_bytes(b"source"),
            candidate_union_digest: Digest32::of_bytes(b"union"),
            recall_packet_digest: Digest32::of_bytes(b"recall"),
            enumerated_candidate_digests: vec![
                Digest32::of_bytes(b"candidate-b"),
                Digest32::of_bytes(b"candidate-a"),
            ],
            legal_candidate_indices: vec![1, 0],
            selected_candidate_indices: vec![1],
            delivered_candidate_indices: vec![1],
            context_exposed: true,
            published_context_digest: Some(Digest32::of_bytes(b"published")),
            omitted_by_policy_limits: 0,
            assignment_propensity: ProbabilityQ32::ONE,
            downstream_policy_digest: Some(Digest32::of_bytes(b"ranker")),
            delivery_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: Digest32::of_bytes(b"retrieval-support"),
        }),
        LedgerEvent::AuthenticatedDecisionV2(AuthenticatedDecisionRecordV2 {
            record_id: id("authenticated-decision"),
            episode_id: id("authenticated-episode"),
            run_snapshot_digest: Digest32::of_bytes(b"run"),
            objective_digest: Digest32::of_bytes(b"auth-objective"),
            policy_digest: Digest32::of_bytes(b"auth-policy"),
            generator_id: id("generator"),
            generator_controller_id: id("generator-controller"),
            generator_credential_chain_digest: Digest32::of_bytes(b"generator-credential"),
            generator_signing_key_digest: Digest32::of_bytes(b"generator-key"),
            generator_scope_digest: Digest32::of_bytes(b"generator-scope"),
            generator_authority_epoch: 1,
            candidate_ids: vec![id("choice"), id("abstain")],
            selected_candidate_id: id("choice"),
            selected_propensity: ProbabilityQ32::ONE,
            candidate_completeness_digest: Digest32::of_bytes(b"candidate-completeness"),
            support_digest: Digest32::of_bytes(b"auth-decision-support"),
            authentication_digest: Digest32::of_bytes(b"auth-decision"),
        }),
        LedgerEvent::AuthenticatedOutcomeV2(AuthenticatedOutcomeRecordV2 {
            record_id: id("authenticated-observation"),
            outcome_id: id("authenticated-outcome"),
            episode_id: id("authenticated-episode"),
            observer_id: id("independent-observer"),
            observer_controller_id: id("observer-controller"),
            observer_credential_chain_digest: Digest32::of_bytes(b"observer-credential"),
            observer_signing_key_digest: Digest32::of_bytes(b"observer-key"),
            observer_scope_digest: Digest32::of_bytes(b"observer-scope"),
            observer_authority_epoch: 1,
            observed_at: Some(5),
            value: Some(FixedQ32::ONE),
            unit_profile_digest: Digest32::of_bytes(b"unit"),
            support_digest: Digest32::of_bytes(b"auth-outcome-support"),
            latest_observable_at: 10,
            expected_delay_profile_digest: Digest32::of_bytes(b"delay"),
            terminality: AuthenticatedOutcomeTerminality::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(6),
            authentication_digest: Digest32::of_bytes(b"auth-outcome"),
        }),
        LedgerEvent::CreditBatchV2(CreditAllocationBatchRecordV2 {
            record_id: id("batch-record"),
            batch_id: id("batch"),
            episode_id: id("authenticated-episode"),
            outcome_id: id("authenticated-outcome"),
            allocator_id: id("independent-allocator"),
            allocator_controller_id: id("allocator-controller"),
            allocator_credential_chain_digest: Digest32::of_bytes(b"allocator-credential"),
            allocator_signing_key_digest: Digest32::of_bytes(b"allocator-key"),
            allocator_scope_digest: Digest32::of_bytes(b"allocator-scope"),
            allocator_authority_epoch: 1,
            terminal_outcome: FixedQ32::ONE,
            allocations: vec![CreditAllocationRecordV2 {
                target_artifact_id: id("authenticated-artifact"),
                credit: FixedQ32::ONE,
            }],
            conservation_residual: FixedQ32::ZERO,
            support_digest: Digest32::of_bytes(b"batch-support"),
            authentication_digest: Digest32::of_bytes(b"auth-batch"),
        }),
    ] {
        must(core.append(event));
    }
    let source = core.records().last().expect("batch record");
    let unlearning = UnlearningLineageEventV1 {
        record_id: id("unlearning-record"),
        lineage_id: id("unlearning"),
        source_record_id: source.event.record_id().clone(),
        source_event_digest: source.event_digest,
        dataset_snapshot_id: id("dataset"),
        dataset_digest: Digest32::of_bytes(b"dataset"),
        artifact_id: id("authenticated-artifact"),
        authority_id: id("privacy-owner"),
        reason_digest: Digest32::of_bytes(b"unlearning-reason"),
        authentication_digest: Digest32::of_bytes(b"auth-unlearning"),
    };
    must(core.append(LedgerEvent::UnlearningLineageV1(unlearning)));
    core.snapshot()
}

// Build checksum-valid hostile fixtures without passing through the new encoder.
fn unchecked_wire(snapshot: &LedgerSnapshot) -> Vec<u8> {
    let mut bytes = DOMAIN.to_vec();
    bytes.extend_from_slice(&must(u32::try_from(snapshot.records.len())).to_be_bytes());
    bytes.extend_from_slice(snapshot.head_digest.as_array());
    for record in &snapshot.records {
        bytes.extend_from_slice(&must(encode_frame(record)));
    }
    bytes
}

#[test]
fn empty_and_complete_snapshots_roundtrip_all_records_and_head() {
    for expected in [LearningLedger::new().snapshot(), complete_snapshot()] {
        let bytes = must(encode_original_ledger_snapshot_v1(&expected));
        let actual = must(decode_original_ledger_snapshot_v1(&bytes));
        assert_eq!(actual, expected);
        assert_eq!(must(LearningLedger::from_snapshot(actual.clone())).snapshot(), expected);
        assert_eq!(must(encode_original_ledger_snapshot_v1(&actual)), bytes);
        assert_eq!(bytes, unchecked_wire(&expected));
    }
}

#[test]
fn encoder_rejects_changed_original_record_fields_and_head() {
    let original = single_snapshot();
    let changed_digest = Digest32::of_bytes(b"changed");
    let mut sequence = original.clone();
    sequence.records[0].sequence = must(LogicalSequence::new(/*value*/ 2));
    let mut predecessor = original.clone();
    predecessor.records[0].predecessor_chain_digest = changed_digest;
    let mut event_digest = original.clone();
    event_digest.records[0].event_digest = changed_digest;
    let mut chain = original.clone();
    chain.records[0].chain_digest = changed_digest;
    let mut head = original;
    head.head_digest = changed_digest;
    for changed in [sequence, predecessor, event_digest, chain, head] {
        assert_eq!(
            encode_original_ledger_snapshot_v1(&changed),
            Err(CodecError::Corrupt),
        );
    }
}

#[test]
fn every_truncation_trailing_byte_and_changed_domain_is_rejected() {
    let bytes = must(encode_original_ledger_snapshot_v1(&single_snapshot()));
    for end in 0..bytes.len() {
        assert!(decode_original_ledger_snapshot_v1(&bytes[..end]).is_err());
    }
    let mut trailing = bytes.clone();
    trailing.push(0);
    assert_eq!(decode_original_ledger_snapshot_v1(&trailing), Err(CodecError::Corrupt));
    let mut domain = bytes;
    domain[0] ^= 1;
    assert_eq!(decode_original_ledger_snapshot_v1(&domain), Err(CodecError::Corrupt));
}

#[test]
fn declared_counts_and_frame_lengths_cannot_expand_the_input_budget() {
    let bytes = must(encode_original_ledger_snapshot_v1(&single_snapshot()));
    let mut count = bytes.clone();
    count[DOMAIN.len()..DOMAIN.len() + 4].copy_from_slice(&u32::MAX.to_be_bytes());
    assert_eq!(decode_original_ledger_snapshot_v1(&count), Err(CodecError::Capacity));
    let mut missing_record = bytes.clone();
    missing_record[DOMAIN.len()..DOMAIN.len() + 4].copy_from_slice(&2_u32.to_be_bytes());
    assert!(decode_original_ledger_snapshot_v1(&missing_record).is_err());
    let mut length = bytes.clone();
    length[HEADER_BYTES..HEADER_BYTES + 4].copy_from_slice(&u32::MAX.to_be_bytes());
    length[HEADER_BYTES + 4..HEADER_BYTES + 8].copy_from_slice(&0_u32.to_be_bytes());
    assert_eq!(decode_original_ledger_snapshot_v1(&length), Err(CodecError::Capacity));
    let mut complement = bytes;
    complement[HEADER_BYTES + 4] ^= 1;
    assert_eq!(decode_original_ledger_snapshot_v1(&complement), Err(CodecError::Corrupt));
    let oversized = vec![0; MAX_ORIGINAL_LEDGER_SNAPSHOT_BYTES_V1 + 1];
    assert_eq!(decode_original_ledger_snapshot_v1(&oversized), Err(CodecError::Capacity));
}

#[test]
fn checksums_do_not_replace_sequence_predecessor_chain_or_head_validation() {
    let bytes = must(encode_original_ledger_snapshot_v1(&single_snapshot()));
    let mut bad_checksum = bytes.clone();
    *bad_checksum.last_mut().expect("checksum") ^= 1;
    assert_eq!(
        decode_original_ledger_snapshot_v1(&bad_checksum),
        Err(CodecError::Corrupt),
    );
    let checksum_at = bytes.len() - 32;
    for offset in [HEADER_BYTES + 8, HEADER_BYTES + 16, bytes.len() - 64] {
        let mut altered = bytes.clone();
        altered[offset] ^= 1;
        let checksum = Digest32::of_bytes(&altered[HEADER_BYTES..checksum_at]);
        altered[checksum_at..].copy_from_slice(checksum.as_array());
        assert_eq!(
            decode_original_ledger_snapshot_v1(&altered),
            Err(CodecError::Corrupt),
        );
    }
    let mut head = bytes;
    head[DOMAIN.len() + 4] ^= 1;
    assert_eq!(decode_original_ledger_snapshot_v1(&head), Err(CodecError::Corrupt));
}

#[test]
fn checksum_valid_noncanonical_candidate_order_is_rejected_not_repaired() {
    let mut changed = single_snapshot();
    let LedgerEvent::Decision(value) = &mut changed.records[0].event else {
        panic!("decision fixture");
    };
    value.candidate_ids.reverse();
    assert_eq!(encode_original_ledger_snapshot_v1(&changed), Err(CodecError::Corrupt));
    assert_eq!(
        decode_original_ledger_snapshot_v1(&unchecked_wire(&changed)),
        Err(CodecError::Corrupt),
    );
}

#[test]
fn repeated_or_reordered_checksum_valid_frames_are_rejected() {
    let original = complete_snapshot();
    let mut repeated = original.clone();
    repeated.records.insert(1, repeated.records[0].clone());
    let mut reordered = original;
    reordered.records.swap(0, 1);
    for changed in [repeated, reordered] {
        assert!(encode_original_ledger_snapshot_v1(&changed).is_err());
        assert!(decode_original_ledger_snapshot_v1(&unchecked_wire(&changed)).is_err());
    }
}

#[test]
fn checksum_valid_event_cannot_bypass_original_causal_validation() {
    let mut changed = complete_snapshot();
    let LedgerEvent::Outcome(value) = &mut changed.records[2].event else {
        panic!("outcome fixture");
    };
    value.episode_id = id("missing-episode");
    let expected = CodecError::Semantic(LedgerError::EpisodeNotFound(
        "missing-episode".to_string(),
    ));
    assert_eq!(encode_original_ledger_snapshot_v1(&changed), Err(expected.clone()));
    assert_eq!(
        decode_original_ledger_snapshot_v1(&unchecked_wire(&changed)),
        Err(expected),
    );
}

#[test]
fn oversized_in_memory_event_is_rejected_before_encoding_or_cloning_it() {
    let mut changed = single_snapshot();
    let LedgerEvent::Decision(value) = &mut changed.records[0].event else {
        panic!("decision fixture");
    };
    value.candidate_ids = vec![id("candidate"); 129];
    assert_eq!(encode_original_ledger_snapshot_v1(&changed), Err(CodecError::Capacity));
    assert_eq!(
        decode_original_ledger_snapshot_v1(&unchecked_wire(&changed)),
        Err(CodecError::Corrupt),
    );
}

#[test]
fn aggregate_output_cap_rejects_complete_history_without_truncation() {
    let mut core = LearningLedger::new();
    let mut expected_bytes = HEADER_BYTES;
    let mut last_fitting = core.snapshot();
    let mut index = 0;
    while expected_bytes <= MAX_ORIGINAL_LEDGER_SNAPSHOT_BYTES_V1 {
        must(core.append(decision(index)));
        index += 1;
        expected_bytes += must(encode_frame(core.records().last().expect("record"))).len();
        if expected_bytes <= MAX_ORIGINAL_LEDGER_SNAPSHOT_BYTES_V1 {
            last_fitting = core.snapshot();
        }
    }
    let bytes = must(encode_original_ledger_snapshot_v1(&last_fitting));
    assert_eq!(must(decode_original_ledger_snapshot_v1(&bytes)), last_fitting);
    assert_eq!(
        encode_original_ledger_snapshot_v1(&core.snapshot()),
        Err(CodecError::Capacity),
    );
}
