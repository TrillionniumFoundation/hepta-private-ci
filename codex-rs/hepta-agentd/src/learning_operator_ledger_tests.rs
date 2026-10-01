//! Two real durable owners under the original root-authenticated learning trust.
use super::paired;
use codex_hepta_agent_components::learning_ledger::*;
use codex_hepta_agent_components::types::*;
use std::fs::File;
use std::fs::OpenOptions;

pub(super) struct LearningFixture {
    pub(super) owner: LedgerWriter,
    pub(super) receipt: DatasetSnapshotReceiptV3,
    pub(super) freeze: SignedLearningEvidenceV1,
    _directory: tempfile::TempDir,
}

impl LearningFixture {
    pub(super) fn new(prefix: &str, signing: &paired::SigningFixture) -> Self {
        let directory = tempfile::tempdir().unwrap();
        let file = |name| {
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(directory.path().join(name))
                .unwrap()
        };
        let binding = paired::digest(&format!("{prefix}-ledger-binding"));
        let ledger = DurableLedger::create(file("ledger"), binding, 64).unwrap();
        let witness = LedgerWitnessStore::create(file("witness"), binding).unwrap();
        let dir = File::open(directory.path()).unwrap();
        let mut owner =
            LedgerWriter::from_durable(ledger, witness, signing.trust.clone(), &dir, &dir).unwrap();
        let candidates = vec![paired::id("action"), paired::id("abstain")];
        let tagged = |name| paired::id(&format!("{prefix}-{name}"));
        let decision = ProductionDecisionV2 {
            record_id: tagged("decision"),
            episode_id: tagged("episode"),
            run_snapshot_digest: paired::digest(&format!("{prefix}-run")),
            objective_digest: signing.verifier.objective_digest(),
            policy_digest: paired::digest("installed-policy"),
            candidate_ids: candidates.clone(),
            selected_candidate_id: paired::id("action"),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompletenessReceiptV1 {
                set_id: tagged("set"),
                state_digest: paired::digest("state"),
                generator_id: signing.principals[0].principal_id.clone(),
                generator_code_digest: paired::digest("generator-code"),
                grammar_digest: paired::digest("grammar"),
                hard_filter_digest: paired::digest("filter"),
                truncation_digest: paired::digest("truncation"),
                candidates_digest: candidate_ids_digest_v2(&candidates),
                candidate_count: 2,
                omitted_count_bound: 0,
                canonical_order_digest: candidate_order_digest_v2(&candidates),
                complete_for_generator: true,
            },
            support_digest: paired::digest(&format!("{prefix}-decision-support")),
        };
        let now = paired::now_millis();
        let signed = signing.sign(0, &decision_signing_payload_v2(&decision).unwrap(), now);
        let appended = owner
            .append_decision(Digest32::ZERO, decision, &signed, paired::now_millis())
            .unwrap();
        let outcome = AuthenticatedOutcomeV1 {
            record_id: tagged("outcome-record"),
            outcome_id: tagged("outcome"),
            episode_id: tagged("episode"),
            observer: signing.principals[1].clone(),
            observed_at: Some(now),
            value: Some(FixedQ32::from_raw(20)),
            unit_profile_digest: paired::digest("utility-q32"),
            support_digest: paired::digest(&format!("{prefix}-outcome-support")),
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: now,
                expected_delay_profile_digest: paired::digest("delay"),
                terminality: OutcomeTerminalityV1::Terminal,
                censoring_reason: None,
                correction_predecessor: None,
                finalized_at: Some(now),
            },
        };
        let signed = signing.sign(
            1,
            &outcome_signing_payload_v2(&outcome),
            paired::now_millis(),
        );
        owner
            .append_outcome(
                appended.chain_digest,
                outcome,
                &signed,
                paired::now_millis(),
            )
            .unwrap();
        let plan = DatasetFreezePlanV2 {
            snapshot_id: tagged("dataset"),
            objective_digest: signing.verifier.objective_digest(),
            inclusion_policy_digest: paired::digest(&format!("{prefix}-fixed-cut")),
        };
        let freeze = signing.sign(
            2,
            &dataset_freeze_signing_payload_v2(&owner.snapshot().unwrap(), &plan).unwrap(),
            paired::now_millis(),
        );
        let receipt = owner
            .freeze_dataset(plan, &freeze, paired::now_millis())
            .unwrap();
        Self {
            owner,
            receipt,
            freeze,
            _directory: directory,
        }
    }
}
