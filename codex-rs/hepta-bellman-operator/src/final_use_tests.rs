use super::*;
use crate::legacy::fit_tabular_operator;
use crate::world_model_v2::predict_world_model_v2;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn tabular_candidate() -> FinalUseTabularCandidateV1 {
    let artifact = fit_tabular_operator(TabularOperatorPlanV1 {
        artifact_id: id("artifact"),
        producer_id: id("generator"),
        generation: Generation::new(1).expect("fixture generation"),
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        sensor_core_digest: digest("sensors"),
        training_profile_digest: digest("training"),
        minimum_samples_per_cell: 2,
        sensor_ids: vec![id("sensor")],
        action_ids: vec![id("action")],
        samples: [4, 6]
            .into_iter()
            .enumerate()
            .map(|(index, target)| TabularOperatorSampleV1 {
                sample_id: id(&format!("row-{index}")),
                sensor_id: id("sensor"),
                action_id: id("action"),
                target: FixedQ32::from_raw(target),
                evidence_digest: digest(&format!("evidence-{index}")),
            })
            .collect(),
    })
    .expect("real fit");
    let payload = encode_tabular_payload_v1(&artifact).expect("encode").into();
    FinalUseTabularCandidateV1 {
        artifact,
        payload,
        runtime_profile_digest: digest("runtime"),
        trust_digest: digest("training-trust"),
        ledger_head_digest: digest("ledger"),
        authority_epoch: 7,
        stop_epoch: 3,
        fit_receipt_digest: digest("fit-receipt"),
        published_at_unix_micros: 51_000_000,
    }
}

fn selection(artifact_digest: Digest32) -> SelectionCurrentnessV1 {
    SelectionCurrentnessV1::new(
        artifact_digest,
        digest("selection"),
        digest("runtime"),
        digest("training-trust"),
        digest("registry"),
        digest("ledger"),
        Generation::new(1).expect("fixture generation"),
        /*authority_epoch*/ 7,
        /*stop_epoch*/ 3,
        /*observed_at_unix_micros*/ 52_000_000,
        /*expires_at_unix_micros*/ 60_000_000,
        /*stop_requested*/ false,
    )
    .expect("host selection fixture")
}

#[test]
fn selected_tabular_load_and_repeated_predictions_retain_selection_window() {
    let candidate = tabular_candidate();
    let current = selection(candidate.artifact_digest());
    let selected = candidate.pin_for_selection(current).expect("select");
    assert!(matches!(
        selected.load(/*now*/ 51_000_000),
        Err(FinalUseErrorV1::ClockRegression)
    ));
    let loaded = selected
        .load(/*now*/ 52_000_000)
        .expect("load in selected window");
    for now in [52_000_000, 59_000_000] {
        let predicted = loaded
            .predict(&id("sensor"), &id("action"), now)
            .expect("predict");
        assert!(predicted.value == FixedQ32::from_raw(5));
        assert!(!predicted.authority.grants_any());
    }
    assert!(matches!(
        loaded.predict(&id("sensor"), &id("action"), /*now*/ 51_000_000),
        Err(FinalUseErrorV1::ClockRegression)
    ));
    assert!(matches!(
        loaded.predict(&id("sensor"), &id("action"), /*now*/ 60_000_000),
        Err(FinalUseErrorV1::SelectionBinding(_))
    ));
    assert!(matches!(
        selected.load(/*now*/ 60_000_000),
        Err(FinalUseErrorV1::SelectionBinding(_))
    ));
}

#[test]
fn selected_tabular_clock_cannot_reset_across_loads_or_revive_after_expiry() {
    let candidate = tabular_candidate();
    let current = selection(candidate.artifact_digest());
    let selected = candidate.pin_for_selection(current).expect("select");
    let first = selected.load(/*now*/ 52_000_000).expect("first load");
    let second = selected.load(/*now*/ 54_000_000).expect("second load");
    first
        .predict(&id("sensor"), &id("action"), /*now*/ 56_000_000)
        .expect("first prediction");
    assert!(matches!(
        second.predict(&id("sensor"), &id("action"), /*now*/ 55_000_000),
        Err(FinalUseErrorV1::ClockRegression)
    ));
    assert!(matches!(
        selected.load(/*now*/ 55_000_000),
        Err(FinalUseErrorV1::ClockRegression)
    ));
    assert!(matches!(
        second.predict(&id("sensor"), &id("action"), /*now*/ 60_000_000),
        Err(FinalUseErrorV1::SelectionBinding(_))
    ));
    assert!(matches!(
        first.predict(&id("sensor"), &id("action"), /*now*/ 59_000_000),
        Err(FinalUseErrorV1::ClockRegression)
    ));
    assert!(matches!(
        selected.load(/*now*/ 59_000_000),
        Err(FinalUseErrorV1::ClockRegression)
    ));
}

#[test]
fn selected_tabular_cannot_relabel_training_trust() {
    let candidate = tabular_candidate();
    let mut current = selection(candidate.artifact_digest());
    current.trust_digest = digest("foreign-trust");
    assert!(matches!(
        candidate.pin_for_selection(current),
        Err(FinalUseErrorV1::SelectionBinding(_))
    ));
}

#[test]
fn selected_world_model_expires_with_selection_before_model_retention() {
    let artifact = fit_world_model_v2(
        WorldModelPlanV2 {
            model_id: id("model"),
            generation: Generation::new(1).expect("fixture generation"),
            objective_digest: digest("objective"),
            dataset_digest: digest("dataset"),
            training_profile_digest: digest("training"),
            runtime_profile_digest: digest("runtime"),
            trust_digest: digest("training-trust"),
            registry_head_digest: digest("registry"),
            row_commitment_root: digest("rows"),
            train_window_digest: digest("train-window"),
            holdout_window_digest: digest("holdout-window"),
            future_window_digest: digest("future-window"),
            predecessor_model_digest: None,
            authority_epoch: 7,
            minimum_support: 1,
            one_step_calibration_error: FixedQ32::ZERO,
            multistep_calibration_error: FixedQ32::ZERO,
            ood_false_acceptance: ProbabilityQ32::ZERO,
            drift_score: FixedQ32::ZERO,
            change_point_digest: digest("change-point"),
            retained_until: 100_000_000,
            expires_at: 200_000_000,
            samples: vec![WorldModelSampleV1 {
                sample_id: id("observation"),
                state_id: id("sensor"),
                action_id: id("action"),
                next_state_id: id("next-state"),
                outcome: FixedQ32::from_raw(5),
                evidence_digest: digest("observed-evidence"),
            }],
        },
        OperatorResourceBudgetV1::qualification_default(),
    )
    .expect("real world-model fit");
    let candidate = FinalUseWorldModelCandidateV1 {
        artifact,
        ledger_head_digest: digest("ledger"),
        stop_epoch: 3,
        published_at_unix_micros: 51_000_000,
    };
    let current = selection(candidate.artifact_digest());
    let selected = candidate.pin_for_selection(current).expect("select");
    assert!(
        predict_world_model_v2(
            &selected.artifact,
            &id("sensor"),
            &id("action"),
            &selected.pin,
            /*now*/ 60
        )
        .is_ok()
    );
    assert!(
        selected
            .predict(&id("sensor"), &id("action"), /*now*/ 59_000_000)
            .is_ok()
    );
    assert!(matches!(
        selected.predict(&id("sensor"), &id("action"), /*now*/ 51_000_000),
        Err(FinalUseErrorV1::ClockRegression)
    ));
    assert!(matches!(
        selected.predict(&id("sensor"), &id("action"), /*now*/ 60_000_000),
        Err(FinalUseErrorV1::SelectionBinding(_))
    ));
    assert!(matches!(
        selected.predict(&id("sensor"), &id("action"), /*now*/ 59_000_000),
        Err(FinalUseErrorV1::ClockRegression)
    ));
}
