use super::*;

use std::fs::OpenOptions;

use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_memory_retrieval::RetrievalAssignmentCompletenessV1;
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000141").expect("owner")
}

fn observation(label: &str) -> RetrievalAssignmentObservationV1 {
    let candidate = RetrievalCandidateIdentityV1 {
        record_id: id("memory:1"),
        record_revision: Revision::new(1).expect("revision"),
        record_digest: digest("record"),
    };
    let mut value = RetrievalAssignmentObservationV1 {
        cue_digest: digest("cue"),
        policy_digest: digest("policy"),
        source_completeness_digest: digest("source-complete"),
        candidate_union_digest: digest("union"),
        recall_packet_digest: digest(label),
        enumerated_candidates: vec![candidate.clone()],
        legal_candidates: vec![candidate.clone()],
        selected_candidates: vec![candidate],
        omitted_by_policy_limits: 0,
        completeness: RetrievalAssignmentCompletenessV1::Complete,
        assignment_propensity: ProbabilityQ32::ONE,
        observation_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    value.observation_digest = value.compute_observation_digest();
    value.validate().expect("observation");
    value
}

fn sink() -> (tempfile::TempDir, CognitiveRetrievalLearningSink) {
    let temp = tempfile::tempdir().expect("temp");
    let path = temp.path().join("learning.ledger");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(path)
        .expect("file");
    let ledger =
        DurableLedger::create(file, digest("agentd-retrieval-learning"), 128).expect("ledger");
    (temp, CognitiveRetrievalLearningSink::new(ledger))
}

#[test]
fn same_rpc_and_observation_replays_idempotently() {
    let (_temp, sink) = sink();
    let observation = observation("packet");
    let first = sink
        .append(&owner(), 1, 77, &observation)
        .expect("first append");
    let second = sink.append(&owner(), 1, 77, &observation).expect("replay");
    assert_eq!(first.disposition, AppendDisposition::Appended);
    assert_eq!(second.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(first.event_digest, second.event_digest);
    let snapshot = sink
        .ledger
        .lock()
        .expect("lock")
        .snapshot()
        .expect("snapshot");
    assert_eq!(snapshot.records().len(), 1);
}

#[test]
fn same_rpc_with_different_assignment_is_identity_conflict() {
    let (_temp, sink) = sink();
    sink.append(&owner(), 1, 88, &observation("packet-a"))
        .expect("first append");
    assert!(
        sink.append(&owner(), 1, 88, &observation("packet-b"))
            .is_err()
    );
    let snapshot = sink
        .ledger
        .lock()
        .expect("lock")
        .snapshot()
        .expect("snapshot");
    assert_eq!(snapshot.records().len(), 1);
}

#[test]
fn different_rpc_ids_create_distinct_assignment_records() {
    let (_temp, sink) = sink();
    let observation = observation("packet");
    sink.append(&owner(), 1, 1, &observation).expect("first");
    sink.append(&owner(), 1, 2, &observation).expect("second");
    let snapshot = sink
        .ledger
        .lock()
        .expect("lock")
        .snapshot()
        .expect("snapshot");
    assert_eq!(snapshot.records().len(), 2);
}
