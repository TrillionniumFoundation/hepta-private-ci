use super::*;
use crate::CandidateSetCompleteness;
use crate::RetrievalPreparationFactV1;

fn preparation() -> RetrievalPreparationFactV1 {
    RetrievalPreparationFactV1 {
        assignment: RetrievalAssignmentFact {
            record_id: id("prepared-context"),
            episode_id: id("retrieval-episode"),
            cue_digest: digest("cue"),
            policy_digest: digest("policy"),
            source_completeness_digest: digest("complete"),
            candidate_union_digest: digest("union"),
            recall_packet_digest: digest("packet"),
            enumerated_candidate_digests: vec![digest("first"), digest("second")],
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
            support_digest: digest("support"),
        },
        prepared_candidate_indices: vec![1, 0],
        prepared_context_digest: Some(digest("exact-context")),
    }
}

#[test]
fn product_preparation_reopens_as_tag_ten_and_replays_without_exposure() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let preparation = preparation();
    let expected_order = preparation
        .prepared_candidate_indices
        .iter()
        .map(|index| preparation.assignment.enumerated_candidate_digests[*index as usize])
        .collect::<Vec<_>>();
    let first = writer
        .append_retrieval_preparation_current(preparation.clone())
        .unwrap();
    let witness = writer.witness_frontier().unwrap();
    let records = writer.records().unwrap();
    let LedgerEvent::RetrievalPrepared(actual) = &records[0].event else {
        panic!("product writer must retain the preparation event kind");
    };
    assert!(!actual.assignment.context_exposed);
    assert!(actual.assignment.delivered_candidate_indices.is_empty());
    assert_eq!(actual.assignment.published_context_digest, None);
    assert_eq!(
        actual
            .prepared_candidate_indices
            .iter()
            .map(|index| actual.assignment.enumerated_candidate_digests[*index as usize])
            .collect::<Vec<_>>(),
        expected_order
    );
    drop(writer);
    let ledger = DurableLedger::recover(
        fixture.file("ledger"),
        binding(),
        64,
        LedgerRecovery::Acknowledged(witness.anchor),
    )
    .unwrap();
    let witness_store = LedgerWitnessStore::recover(fixture.file("witness"), binding()).unwrap();
    let directory = fixture.directory();
    let mut reopened = LedgerWriter::from_durable(
        ledger,
        witness_store,
        activated_trust(),
        &directory,
        &directory,
    )
    .unwrap();
    assert_eq!(reopened.records().unwrap(), records);
    let retry = reopened
        .append_retrieval_preparation_current(preparation.clone())
        .unwrap();
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(retry.event_digest, first.event_digest);
    assert_eq!(reopened.witness_frontier().unwrap(), witness);
    let mut reordered = preparation;
    reordered.prepared_candidate_indices.reverse();
    assert!(
        reopened
            .append_retrieval_preparation_current(reordered)
            .is_err()
    );
    assert_eq!(reopened.records().unwrap(), records);
    assert_eq!(reopened.witness_frontier().unwrap(), witness);
}

#[test]
fn product_writer_rejects_forged_exposure_without_advancing_either_owner() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let before = writer.witness_frontier().unwrap();
    let mut prepared = preparation();
    prepared.assignment.context_exposed = true;
    assert!(
        writer
            .append_retrieval_preparation_current(prepared)
            .is_err()
    );
    assert!(writer.records().unwrap().is_empty());
    assert_eq!(writer.witness_frontier().unwrap(), before);
}
