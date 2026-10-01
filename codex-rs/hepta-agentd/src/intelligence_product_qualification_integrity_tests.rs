use super::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn qualification_appends_reject_mutated_prepared_decision_before_ledger_write() {
    let (fixture, trust) = signed::signed_fixture();
    let temp = tempfile::tempdir().expect("tempdir");
    let authority = temp.path().join("intelligence-authority.json");
    write_authority_file(
        &authority,
        &fixture.owners,
        fixture.request.snapshot.revocation_frontier_digest(),
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(authority, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("host-root trust");
    let outcome = runner
        .prepare(&product_test_coordinator(), fixture.request, fixture.inputs)
        .await
        .expect("prepare");
    let AgentdIntelligenceProductOutcomeV1::Ready(prepared) = outcome else {
        panic!("ready");
    };
    let AdvisoryDecisionV1::Selected {
        candidate_id,
        propensity,
    } = &prepared.envelope.decision.decision
    else {
        panic!("selected decision");
    };
    let another_candidate = prepared
        .candidate_ids()
        .iter()
        .find(|candidate| *candidate != candidate_id)
        .expect("another legal candidate")
        .clone();
    let mut mutated = prepared.clone();
    mutated.envelope.decision.decision = AdvisoryDecisionV1::Selected {
        candidate_id: another_candidate,
        propensity: *propensity,
    };

    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(temp.path().join("ledger"))
        .expect("create ledger");
    let mut ledger = DurableLedger::create(file, digest("binding"), 16).expect("ledger");
    assert!(matches!(
        runner.append_decision(
            &mut ledger,
            Digest32::ZERO,
            &mutated,
            id("episode.agentd"),
            id("intuition.policy"),
        ),
        Err(AgentdIntelligenceLedgerError::Currentness(
            CanonicalIntelligenceError::InvalidCandidateSet("decision digest")
        ))
    ));
    assert!(ledger.records().expect("records").is_empty());

    let decision = runner
        .append_decision(
            &mut ledger,
            Digest32::ZERO,
            &prepared,
            id("episode.agentd"),
            id("intuition.policy"),
        )
        .expect("unchanged owner decision append");
    let original_records = ledger.records().expect("records").to_vec();
    assert!(matches!(
        runner.append_outcome(
            &mut ledger,
            decision.chain_digest,
            &mutated,
            id("outcome-record.agentd"),
            id("outcome.agentd"),
            id("episode.agentd"),
            id("observer.independent"),
            FixedQ32::ONE,
            OutcomeFinality::Terminal,
            digest("terminal-observation"),
        ),
        Err(AgentdIntelligenceLedgerError::Currentness(
            CanonicalIntelligenceError::InvalidCandidateSet("decision digest")
        ))
    ));
    assert_eq!(ledger.records().expect("records"), original_records);
}
