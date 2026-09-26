//! Read-consumer fixtures use authenticated owner records, never raw fit APIs.
use codex_hepta_bellman_operator::TabularOperatorArtifactV1;
use codex_hepta_bellman_operator::TerminalCellProfileV1;
use codex_hepta_bellman_operator::fit_terminal_cell_from_owner_v1;
use codex_hepta_bellman_operator::freeze_terminal_cell_from_owner_v1;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
#[allow(dead_code)]
#[path = "../tests/support/terminal_cell_owner.rs"]
mod owner;

pub(crate) fn fit_owner_ranker(
    artifact: &str,
    sensor: StableId,
    actions: &[StableId],
    scores: &[i64],
) -> TabularOperatorArtifactV1 {
    assert_eq!(actions.len(), scores.len());
    let mut actions = actions.to_vec();
    let mut scores = scores.to_vec();
    if !actions.contains(&owner::id("abstain")) {
        actions.push(owner::id("abstain"));
        scores.push(0);
    }
    let files = owner::Fixture::new();
    let mut writer = files.writer_with_limit((actions.len() * 4).max(64));
    for (index, (action, score)) in actions.iter().zip(&scores).enumerate() {
        for replicate in 0..2 {
            let prefix = format!("ranker-{index}-{replicate}");
            let mut decision = owner::decision();
            decision.record_id = owner::id(&format!("{prefix}.decision"));
            decision.episode_id = owner::id(&format!("{prefix}.episode"));
            decision.candidate_ids = actions.to_vec();
            decision.selected_candidate_id = action.clone();
            decision.completeness.candidates_digest = candidate_ids_digest_v2(&actions);
            decision.completeness.canonical_order_digest = candidate_order_digest_v2(&actions);
            decision.completeness.candidate_count = u32::try_from(actions.len()).unwrap();
            let signature = owner::sign(
                writer.verifier(),
                "generator",
                LearningEvidenceRoleV1::Generator,
                &decision_signing_payload_v2(&decision).unwrap(),
            );
            let head = writer.witness_frontier().unwrap().anchor.chain_digest;
            let receipt = writer
                .append_decision(head, decision, &signature, 50)
                .unwrap();
            let mut outcome = owner::outcome(
                &format!("{prefix}.record"),
                &format!("{prefix}.outcome"),
                None,
                *score,
            );
            outcome.episode_id = owner::id(&format!("{prefix}.episode"));
            let signature = owner::sign(
                writer.verifier(),
                "observer",
                LearningEvidenceRoleV1::Observer,
                &outcome_signing_payload_v2(&outcome),
            );
            writer
                .append_outcome(receipt.chain_digest, outcome, &signature, 50)
                .unwrap();
        }
    }
    let plan = DatasetFreezePlanV2 {
        snapshot_id: owner::id(artifact),
        objective_digest: owner::digest("objective"),
        inclusion_policy_digest: owner::digest("all-active"),
    };
    let signature = owner::sign(
        writer.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &writer.dataset_freeze_signing_payload(&plan).unwrap(),
    );
    let dataset = writer.freeze_dataset(plan, &signature, 50).unwrap();
    let profile = TerminalCellProfileV1 {
        artifact_id: owner::id(artifact),
        producer_id: owner::id("fixture-trainer"),
        generation: Generation::new(1).unwrap(),
        sensor_id: sensor,
        objective_digest: owner::digest("objective"),
        run_snapshot_digest: owner::digest("run-snapshot"),
        unit_profile_digest: owner::digest("reward-units"),
        action_ids: actions.to_vec(),
        minimum_samples_per_action: 2,
    };
    let frozen = freeze_terminal_cell_from_owner_v1(&writer, &dataset, profile, 50).unwrap();
    let expected = fit_terminal_cell_from_owner_v1(&writer, frozen.clone(), 50).unwrap();
    // The same actual training input survives owner reopen without a new model.
    let frontier = writer.witness_frontier().unwrap();
    drop(writer);
    let reopened = files.recover_writer((actions.len() * 4).max(64), frontier);
    assert_eq!(
        fit_terminal_cell_from_owner_v1(&reopened, frozen, 50).unwrap(),
        expected
    );
    expected
}
