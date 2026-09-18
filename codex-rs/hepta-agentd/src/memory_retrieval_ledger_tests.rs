use super::*;

use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid fixture id: {error}"))
}

fn decision(index: u64) -> EpisodeDecision {
    EpisodeDecision {
        record_id: id(&format!("decision-{index}")),
        episode_id: id(&format!("episode-{index}")),
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: id("policy"),
        candidate_ids: vec![id(&format!("choice-{index}")), id("abstain")],
        selected_candidate_id: id(&format!("choice-{index}")),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(format!("support-{index}").as_bytes()),
    }
}

#[test]
fn durable_sink_appends_syncs_and_exposes_owner_anchor() {
    let file = tempfile::tempfile().unwrap_or_else(|error| panic!("temp file: {error}"));
    let ledger = DurableLedger::create(
        file,
        Digest32::of_bytes(b"memory-retrieval-decision-owner"),
        16,
    )
    .unwrap_or_else(|error| panic!("create durable ledger: {error}"));
    let sink = DurableMemoryRetrievalDecisionSink::new(ledger)
        .unwrap_or_else(|error| panic!("create sink: {error}"));

    assert_eq!(sink.current_anchor().unwrap(), None);
    let first = decision(1);
    let first_digest = sink
        .append_decision(first.clone())
        .unwrap_or_else(|error| panic!("append first: {error}"));
    assert_eq!(
        sink.append_decision(first)
            .unwrap_or_else(|error| panic!("idempotent first: {error}")),
        first_digest
    );
    let second_digest = sink
        .append_decision(decision(2))
        .unwrap_or_else(|error| panic!("append second: {error}"));

    let anchor = sink
        .current_anchor()
        .unwrap_or_else(|error| panic!("anchor: {error}"))
        .unwrap_or_else(|| panic!("non-empty ledger has an anchor"));
    assert_eq!(anchor.sequence, 2);
    assert_eq!(anchor.chain_digest, second_digest);
}

#[test]
fn durable_sink_rejects_same_identity_with_changed_content() {
    let file = tempfile::tempfile().unwrap_or_else(|error| panic!("temp file: {error}"));
    let ledger = DurableLedger::create(
        file,
        Digest32::of_bytes(b"memory-retrieval-decision-conflict"),
        16,
    )
    .unwrap_or_else(|error| panic!("create durable ledger: {error}"));
    let sink = DurableMemoryRetrievalDecisionSink::new(ledger)
        .unwrap_or_else(|error| panic!("create sink: {error}"));

    let first = decision(1);
    sink.append_decision(first.clone())
        .unwrap_or_else(|error| panic!("append first: {error}"));
    let mut changed = first;
    changed.support_digest = Digest32::of_bytes(b"changed");
    assert!(sink.append_decision(changed).is_err());
}
