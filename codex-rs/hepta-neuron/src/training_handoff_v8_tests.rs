use super::*;
use crate::training_handoff_v7::tensor_digest;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

fn must<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("synthetic V8 fixture failed: {error:?}"),
    }
}
fn digest(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}

fn fixture(
    stride: u64,
    policy: &str,
    gated: bool,
) -> (TrainedCellBundleV5, CellTrainingCheckpointV8) {
    let (serving, checkpoint) = crate::training_handoff_v7::tests::fixture(gated);
    let mut wrapper: Value = must(serde_json::from_slice(
        checkpoint.controller_metadata_json(),
    ));
    let mut source: Value = must(serde_json::from_str(
        wrapper["source_controller_json"].as_str().unwrap(),
    ));
    let commit = if policy == "myopic_h1" {
        1
    } else {
        stride as usize
    };
    let forecast = if policy == "myopic_h1" { 1 } else { 8 };
    let p = checkpoint.state_vector().len() / 3;
    let actions = checkpoint.planned_actions()[..commit].to_vec();
    let future = checkpoint.planned_actions()[..forecast].to_vec();
    let flat = |rows: &[Vec<f64>]| rows.iter().flatten().copied().collect::<Vec<_>>();
    let resolved = tensor_digest(&[commit, p], &flat(&actions)).to_string();
    let forecast_hash = tensor_digest(&[forecast, p], &flat(&future)).to_string();
    source["schema"] = json!("hepta.cell-field-controller.v8");
    source["policy"] = json!(policy);
    source["plan_horizon"] = json!(commit);
    source["intended_actions"] = json!(actions);
    source["resolved_actions"] = json!(actions);
    source["intended_plan_sha256"] = json!(resolved);
    source["resolved_plan_sha256"] = json!(resolved);
    source["forecast_actions"] = json!(future);
    source["forecast_horizon"] = json!(forecast);
    source["forecast_plan_sha256"] = json!(forecast_hash);
    source["run_status"] = json!("active");
    source["failure_ledger"] = json!([]);
    source["receipt_chain"] = json!({"count":17,"sha256":digest("receipt chain").to_string()});
    let mut states: Vec<_> = (0..=commit)
        .map(|i| json!(digest(&format!("synthetic state {i}")).to_string()))
        .collect();
    states[0] = source["plan_origin_state_sha256"].clone();
    states[1] = source["full_state_sha256"].clone();
    source["plan_state_sha256"] = json!(states);
    source["plan_receipt_sha256"] = json!(
        (0..commit)
            .map(|i| digest(&format!("synthetic receipt {i}")).to_string())
            .collect::<Vec<_>>()
    );
    let mut chain = Vec::new();
    for origin in (0..=16).step_by(commit) {
        chain.push(json!({"origin_step":origin,"origin_state_sha256":digest("past origin").to_string(),
            "plan_sha256":digest("past plan").to_string(),"repair_sha256":digest("past repair").to_string(),
            "resolved_plan_sha256":resolved,"forecast_plan_sha256":forecast_hash}));
    }
    source["counters"] = json!({"plans":chain.len(),"proposal_calls":chain.len(),"response_optimizer_steps":chain.len()*forecast,
        "qp_calls":0,"actual_merit_rollout_steps":0,"repair_optimizer_updates":0,"repair_panel_evaluations":0,
        "resume_verification_updates":0,"committed_steps":17,"controller_cpu_ns":1});
    source["certificate_chain"] = json!(chain);
    let warmup = source["original_warmup_state_sha256"].clone();
    let contract = &mut source["contract"];
    contract["schema"] = json!("hepta.cell-field-controller-contract.v8");
    contract["policy"] = json!(policy);
    contract["original_warmup_state_sha256"] = warmup;
    contract["warmup_step_count"] = json!(64);
    contract["registered_steps"] = json!(32);
    contract["parameter_count"] = json!(p);
    contract["configuration"] = json!({"steps":32,"commit_stride":stride,"relinearizations":0,
        "dt":0.1,"effort_price":1.0,"action_bound":1.0,"old_weight":0.1,"current_dispersion":0.1});
    contract["forecast_tail_safety_claimed"] = json!(false);
    contract["independent_online_certificate"] = json!(false);
    contract["safety_filter"] = json!("single_ray_then_joint_v8");
    contract["proposal_rule"] = json!("risk_effort_box_v8");
    wrapper["schema"] = json!("hepta.cell-controller-handoff.v8");
    for key in [
        "plan_horizon",
        "intended_plan_sha256",
        "resolved_plan_sha256",
        "forecast_horizon",
        "forecast_plan_sha256",
    ] {
        wrapper[key] = source[key].clone();
    }
    let source = must(serde_json::to_string(&source));
    wrapper["source_controller_sha256"] = json!(digest(&source).to_string());
    wrapper["source_controller_json"] = json!(source);
    let checkpoint = must(CellTrainingCheckpointV8::new(
        checkpoint.cell_id().clone(),
        checkpoint.state_metadata_json().to_vec(),
        checkpoint.state_vector().to_vec(),
        must(serde_json::to_vec(&wrapper)),
        actions,
    ));
    (serving, checkpoint)
}

fn wrap(
    serving: TrainedCellBundleV5,
    checkpoint: CellTrainingCheckpointV8,
) -> Result<TrainingHandoffBundleV8, TrainingHandoffErrorV8> {
    TrainingHandoffBundleV8::new(
        serving,
        digest("protocol"),
        Some(digest("immutable predecessor")),
        vec![checkpoint],
    )
}

#[test]
fn all_stride_and_head_modes_keep_forecast_separate_from_pending_prefix() {
    for stride in [1, 2, 4, 8] {
        for gated in [false, true] {
            for policy in ["myopic_h1", "future_field_h8"] {
                let (serving, checkpoint) = fixture(stride, policy, gated);
                let expected = if policy == "myopic_h1" {
                    0
                } else {
                    stride as usize - 1
                };
                let bundle = must(wrap(serving, checkpoint));
                let decoded = must(TrainingHandoffBundleV8::decode(
                    &bundle.encode(),
                    bundle.content_digest(),
                ));
                assert_eq!(decoded, bundle);
                assert_eq!(decoded.checkpoints()[0].pending_actions().len(), expected);
                assert_eq!(&decoded.encode()[..8], b"HPTHOF08");
                assert!(
                    TrainingHandoffBundleV7::decode(&decoded.encode(), decoded.content_digest())
                        .is_err()
                );
            }
        }
    }
    assert_ne!(
        training_handoff_compatibility_digest_v8(),
        crate::training_handoff_compatibility_digest_v7()
    );
}

#[test]
fn old_wire_cannot_be_relabelled_as_v8_and_v8_cannot_be_relabelled_as_v7() {
    let (serving, checkpoint) = crate::training_handoff_v7::tests::fixture(false);
    let v7 = must(TrainingHandoffBundleV7::new(
        serving,
        digest("protocol"),
        None,
        vec![checkpoint],
    ));
    let mut bytes = v7.encode();
    bytes[..8].copy_from_slice(b"HPTHOF08");
    assert!(TrainingHandoffBundleV8::decode(&bytes, Digest32::of_bytes(&bytes)).is_err());
    let (serving, checkpoint) = fixture(2, "future_field_h8", false);
    let v8 = must(wrap(serving, checkpoint));
    let mut bytes = v8.encode();
    bytes[..8].copy_from_slice(b"HPTHOF07");
    assert!(TrainingHandoffBundleV7::decode(&bytes, Digest32::of_bytes(&bytes)).is_err());
}

#[test]
fn self_rehashed_forecast_prefix_counter_and_safety_claim_substitutions_reject() {
    for mutation in 0..6 {
        let (serving, checkpoint) = fixture(2, "future_field_h8", true);
        let mut wrapper: Value = must(serde_json::from_slice(
            checkpoint.controller_metadata_json(),
        ));
        let mut source: Value = must(serde_json::from_str(
            wrapper["source_controller_json"].as_str().unwrap(),
        ));
        match mutation {
            0 => {
                source["forecast_actions"][7][0] = json!(0.123);
            }
            1 => {
                source["intended_actions"][0][0] = json!(0.123);
            }
            2 => {
                source["contract"]["configuration"]["commit_stride"] = json!(4);
            }
            3 => {
                source["counters"]["response_optimizer_steps"] = json!(0);
            }
            4 => {
                source["contract"]["forecast_tail_safety_claimed"] = json!(true);
            }
            5 => {
                source["run_status"] = json!("stopped");
            }
            _ => unreachable!(),
        }
        let source = must(serde_json::to_string(&source));
        wrapper["source_controller_sha256"] = json!(digest(&source).to_string());
        wrapper["source_controller_json"] = json!(source);
        let changed = must(CellTrainingCheckpointV8::new(
            checkpoint.cell_id().clone(),
            checkpoint.state_metadata_json().to_vec(),
            checkpoint.state_vector().to_vec(),
            must(serde_json::to_vec(&wrapper)),
            checkpoint.planned_actions().to_vec(),
        ));
        assert!(wrap(serving, changed).is_err(), "mutation {mutation}");
    }
}
