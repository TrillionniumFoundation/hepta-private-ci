use super::*;

use std::fs::File;
use std::fs::OpenOptions;

use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::candidate_ids_digest_v2;
use codex_hepta_learning_ledger::candidate_order_digest_v2;
use codex_hepta_learning_ledger::decision_signing_payload_v2;

fn learning_request(
    prepared: &PreparedAgentdIntelligenceRunV1,
    candidates: Vec<StableId>,
    mut evidence: SignedLearningEvidenceV1,
) -> crate::AgentdIntelligenceDecisionAppendV1 {
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: id("candidate-set.learning"),
        state_digest: digest("learning-state"),
        generator_id: evidence.principal_id.clone(),
        generator_code_digest: digest("generator-code"),
        grammar_digest: digest("learning-grammar"),
        hard_filter_digest: digest("hard-filter"),
        truncation_digest: digest("truncation"),
        candidates_digest: candidate_ids_digest_v2(&candidates),
        candidate_count: u32::try_from(candidates.len()).expect("bounded candidate count"),
        omitted_count_bound: 0,
        canonical_order_digest: candidate_order_digest_v2(&candidates),
        complete_for_generator: true,
    };
    let codex_hepta_intelligence::AdvisoryDecisionV1::Selected {
        candidate_id,
        propensity,
    } = &prepared.envelope.decision.decision
    else {
        panic!("selected fixture");
    };
    let production = ProductionDecisionV2 {
        record_id: prepared.envelope.run_id.clone(),
        episode_id: id("episode.learning"),
        run_snapshot_digest: crate::intelligence_run_snapshot_digest_v1(prepared)
            .expect("snapshot binding"),
        objective_digest: prepared.envelope.objective_digest,
        policy_digest: digest("learning-policy"),
        candidate_ids: candidates,
        selected_candidate_id: candidate_id.clone(),
        selected_propensity: *propensity,
        completeness: completeness.clone(),
        support_digest: prepared.dispatch_proposal_digest,
    };
    let payload = decision_signing_payload_v2(&production).expect("provider signing payload");
    evidence.evidence_id = id("evidence.learning-decision");
    evidence.payload_digest = Digest32::of_bytes(&payload);
    evidence.signature = SigningKey::from_bytes(&[31; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    crate::AgentdIntelligenceDecisionAppendV1 {
        expected_ledger_predecessor: Digest32::ZERO,
        episode_id: production.episode_id,
        policy_digest: production.policy_digest,
        completeness,
        evidence,
        now: wall_clock_ms().expect("clock"),
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn default_learning_writer_requires_signed_intrinsic_complete_candidates() {
    let (value, trust) = signed::signed_fixture();
    let generator_evidence = value
        .inputs
        .signed_evaluation
        .as_ref()
        .expect("signed fixture")
        .evidence
        .generator_plan
        .clone();
    assert_eq!(generator_evidence.role, LearningEvidenceRoleV1::Generator);
    let directory = tempfile::tempdir().expect("directory");
    // Resolve the OS temporary-directory alias while provisioning this fixture.
    // Production authority reads still reject every symlink at final use.
    let root = directory
        .path()
        .canonicalize()
        .expect("canonical test root");
    let authority = root.join("authority.json");
    write_authority_file(
        &authority,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(authority, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust.clone())
        .expect("host trust");
    let AgentdIntelligenceProductOutcomeV1::Ready(prepared) = runner
        .prepare(&product_test_coordinator(), value.request, value.inputs)
        .await
        .expect("signed preparation")
    else {
        panic!("ready fixture");
    };
    let original = prepared.clone();
    assert_eq!(
        prepared.candidate_ids(),
        &[id("action.noop"), id("action.read")]
    );

    let binding = digest("product-learning-ledger");
    let ledger_file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(root.join("learning.ledger"))
        .expect("ledger file");
    let witness_file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(root.join("learning.witness"))
        .expect("witness file");
    let ledger = codex_hepta_learning_ledger::DurableLedger::create(ledger_file, binding, 16)
        .expect("durable ledger");
    let witness = LedgerWitnessStore::create(witness_file, binding).expect("witness");
    let ledger_directory = File::open(&root).expect("ledger directory");
    let witness_directory = File::open(&root).expect("witness directory");
    let mut writer = LedgerWriter::from_durable(
        ledger,
        witness,
        trust,
        &ledger_directory,
        &witness_directory,
    )
    .expect("sole product writer");

    let action_only = learning_request(
        &prepared,
        prepared.candidate_ids().to_vec(),
        generator_evidence.clone(),
    );
    assert!(matches!(
        crate::append_intelligence_decision_v1(&mut writer, &prepared, action_only),
        Err(crate::AgentdIntelligenceLearningErrorV1::Ledger(
            ProductionLedgerError::Binding("candidate completeness")
        ))
    ));
    assert!(writer.records().expect("records").is_empty());

    let complete_candidates = vec![id("abstain"), id("action.noop"), id("action.read")];
    let request = learning_request(&prepared, complete_candidates.clone(), generator_evidence);
    let mut unsigned_change = request.clone();
    unsigned_change.evidence.signature[0] ^= 1;
    assert!(matches!(
        crate::append_intelligence_decision_v1(&mut writer, &prepared, unsigned_change),
        Err(crate::AgentdIntelligenceLearningErrorV1::Ledger(
            ProductionLedgerError::Evidence(_)
        ))
    ));
    assert!(writer.records().expect("records").is_empty());

    let first = crate::append_intelligence_decision_v1(&mut writer, &prepared, request.clone())
        .expect("complete signed decision append");
    assert_eq!(first.disposition, AppendDisposition::Appended);
    let replay = crate::append_intelligence_decision_v1(&mut writer, &prepared, request)
        .expect("exact replay");
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(replay.event_digest, first.event_digest);
    let records = writer.records().expect("records");
    assert_eq!(records.len(), 1);
    let LedgerEvent::AuthenticatedDecisionV2(record) = &records[0].event else {
        panic!("authenticated V2 decision");
    };
    assert_eq!(record.candidate_ids, complete_candidates);
    assert_eq!(record.selected_candidate_id, id("action.read"));
    assert_eq!(prepared, original);
}
