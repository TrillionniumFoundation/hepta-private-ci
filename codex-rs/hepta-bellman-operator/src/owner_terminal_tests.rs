use super::*;
use codex_hepta_types::FixedQ32;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn plan(target: i64) -> TabularOperatorPlanV1 {
    TabularOperatorPlanV1 {
        artifact_id: id("terminal-cell"),
        producer_id: id("operator.native.owner"),
        generation: Generation::new(1).expect("generation"),
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        sensor_core_digest: digest("run-snapshot"),
        training_profile_digest: digest("profile"),
        minimum_samples_per_cell: 1,
        sensor_ids: vec![id("state")],
        action_ids: vec![id("read")],
        samples: vec![TabularOperatorSampleV1 {
            sample_id: id("outcome"),
            sensor_id: id("state"),
            action_id: id("read"),
            target: FixedQ32::from_raw(target),
            evidence_digest: digest("same-owner-event"),
        }],
    }
}

#[test]
fn owner_materialization_rejects_same_evidence_with_changed_training_content() {
    let frozen = plan(10);
    let changed_target = plan(11);
    assert!(matches!(
        require_exact_owner_materialization(&frozen, &changed_target),
        Err(TerminalCellError::Unsupported(
            "owner materialization changed before fit"
        ))
    ));

    let mut changed_action = plan(10);
    changed_action.samples[0].action_id = id("abstain");
    assert!(require_exact_owner_materialization(&frozen, &changed_action).is_err());
    assert!(require_exact_owner_materialization(&frozen, &frozen).is_ok());
}

#[path = "owner_terminal_test_support.rs"]
mod support;

fn collect(writer: &mut LedgerWriter, suffix: &str, action: &str, raw: i64) {
    use codex_hepta_learning_ledger::*;
    let mut decision = support::decision();
    decision.record_id = id(&format!("{suffix}.decision"));
    decision.episode_id = id(&format!("{suffix}.episode"));
    decision.selected_candidate_id = id(action);
    let signature = support::sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&decision).unwrap(),
    );
    let head = writer.witness_frontier().unwrap().anchor.chain_digest;
    let receipt = writer
        .append_decision(head, decision, &signature, 50)
        .unwrap();
    let mut outcome = support::outcome(
        &format!("{suffix}.record"),
        &format!("{suffix}.outcome"),
        None,
        raw,
    );
    outcome.episode_id = id(&format!("{suffix}.episode"));
    let signature = support::sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&outcome),
    );
    writer
        .append_outcome(receipt.chain_digest, outcome, &signature, 50)
        .unwrap();
}

fn owner_dataset(writer: &LedgerWriter) -> DatasetSnapshotReceiptV3 {
    use codex_hepta_learning_ledger::*;
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("owner-dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("all-active"),
    };
    let signature = support::sign(
        writer.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &writer.dataset_freeze_signing_payload(&plan).unwrap(),
    );
    writer.freeze_dataset(plan, &signature, 50).unwrap()
}

fn owner_profile() -> TerminalCellProfileV1 {
    TerminalCellProfileV1 {
        artifact_id: id("actual-owner-model"),
        producer_id: id("trainer"),
        generation: Generation::new(1).unwrap(),
        sensor_id: id("constant-state"),
        objective_digest: digest("objective"),
        run_snapshot_digest: digest("run-snapshot"),
        unit_profile_digest: digest("reward-units"),
        action_ids: vec![id("read"), id("abstain")],
        minimum_samples_per_action: 1,
    }
}

fn populate(writer: &mut LedgerWriter) {
    collect(writer, "read-0", "read", FixedQ32::ONE.raw());
    collect(writer, "abstain-0", "abstain", 0);
}

#[test]
fn actual_owner_rejects_target_action_and_profile_replacement_under_same_receipt() {
    let files = support::Fixture::new();
    let mut writer = files.writer();
    populate(&mut writer);
    let dataset = owner_dataset(&writer);
    let original =
        freeze_terminal_cell_from_owner_v1(&writer, &dataset, owner_profile(), 50).unwrap();
    for mutation in 0..5 {
        let mut frozen = original.clone();
        match mutation {
            0 => frozen.plan.samples[0].target = FixedQ32::from_raw(999_999),
            1 => frozen.plan.samples[0].action_id = id("invented-action"),
            2 => frozen.plan.samples[0].sensor_id = id("invented-state"),
            3 => frozen.plan.training_profile_digest = digest("replacement-profile"),
            4 => frozen.plan.generation = Generation::new(2).unwrap(),
            _ => unreachable!(),
        }
        assert_eq!(frozen.dataset, original.dataset);
        assert!(matches!(
            fit_terminal_cell_from_owner_v1(&writer, frozen, 50),
            Err(TerminalCellError::Unsupported(
                "owner materialization changed before fit"
            ))
        ));
    }
    let fitted = fit_terminal_cell_from_owner_v1(&writer, original, 50).unwrap();
    assert_eq!(
        fitted
            .cells
            .iter()
            .find(|cell| cell.action_id == id("read"))
            .unwrap()
            .mean_target,
        FixedQ32::ONE
    );
}

#[test]
fn frozen_owner_trust_rotation_invalidates_prepared_training() {
    let files = support::Fixture::new();
    let mut writer = files.writer();
    populate(&mut writer);
    let frozen =
        freeze_terminal_cell_from_owner_v1(&writer, &owner_dataset(&writer), owner_profile(), 50)
            .unwrap();
    support::rotate_trust(&mut writer);
    assert!(matches!(
        fit_terminal_cell_from_owner_v1(&writer, frozen, 50),
        Err(TerminalCellError::Unsupported(
            "learning trust changed before fit"
        ))
    ));
}

#[test]
fn actual_owner_correction_expiry_and_restart_preserve_training_identity() {
    use codex_hepta_learning_ledger::*;
    let files = support::Fixture::new();
    let mut writer = files.writer();
    populate(&mut writer);
    let dataset = owner_dataset(&writer);
    let frozen =
        freeze_terminal_cell_from_owner_v1(&writer, &dataset, owner_profile(), 50).unwrap();
    let expected = fit_terminal_cell_from_owner_v1(&writer, frozen.clone(), 50).unwrap();
    assert!(fit_terminal_cell_from_owner_v1(&writer, frozen.clone(), 101).is_err());
    let frontier = writer.witness_frontier().unwrap();
    drop(writer);
    let mut writer = files.recover_writer(64, frontier);
    assert_eq!(
        fit_terminal_cell_from_owner_v1(&writer, frozen.clone(), 50).unwrap(),
        expected
    );
    let mut correction = support::outcome(
        "correction-record",
        "correction-outcome",
        Some("read-0.outcome"),
        0,
    );
    correction.episode_id = id("read-0.episode");
    let signed = support::sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&correction),
    );
    let head = writer.witness_frontier().unwrap().anchor.chain_digest;
    writer
        .append_outcome(head, correction, &signed, 50)
        .unwrap();
    assert!(fit_terminal_cell_from_owner_v1(&writer, frozen.clone(), 50).is_err());
    let frontier = writer.witness_frontier().unwrap();
    drop(writer);
    let writer = files.recover_writer(64, frontier);
    assert!(fit_terminal_cell_from_owner_v1(&writer, frozen, 50).is_err());
}

#[path = "owner_terminal_benchmark.rs"]
mod benchmark;
