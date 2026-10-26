use super::*;
use crate::TrainedCellHeadV5;
use crate::TrainedCellModeV5;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

fn must<T, E: fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}
fn id(value: &str) -> StableId {
    must(StableId::new(value))
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn fixture(gated: bool) -> (TrainedCellBundleV5, CellTrainingCheckpointV7) {
    let mode = if gated { "gated" } else { "linear" };
    let cell = id(&format!("development-{mode}-seed7"));
    let mut weights = [[0.125; 4]; 8];
    weights[0][0] = 0.0;
    let bias = [-0.2, 0.0, 0.1, 0.2];
    let a = [0.15; 8];
    let g = [-0.3; 8];
    let mut theta: Vec<f64> = weights.iter().flatten().copied().collect();
    if gated {
        theta.extend_from_slice(&a);
    }
    theta.extend_from_slice(&bias);
    if gated {
        theta.extend_from_slice(&g);
    }
    let p = theta.len();
    let mut vector = theta;
    vector.extend(vec![0.01; p]);
    vector.extend(vec![0.02; p]);
    let metadata = json!({"schema":"hepta.cell-field-training-state.v1",
        "head":{"width":8,"classes":4,"mode":mode,"rank":2,"max_parameters":100},
        "protocol":{"optimizer":"adam","normalization":"l2_times_sqrt_width"},
        "bindings":{"protocol_sha256":digest("historical-optimizer-protocol").to_string(),"task":"development",
            "head_mode":mode,"seed":7,"feature_identity":digest("features").to_string()},
        "contexts":{"current_train":digest("data").to_string()},"active_context":"current_train",
        "step_count":81,"sampler_draw_count":2592,"external_batch_count":0,
        "rng":{"bit_generator":"PCG64","state":{"state":123,"inc":9},"has_uint32":0,"uinteger":0},
        "parameter_names":if gated {json!(["W","a","b","g"])} else {json!(["W","b"])}});
    let metadata = must(serde_json::to_vec(&metadata));
    let state_sha = state::state_digest(&metadata, &vector);
    let head = must(TrainedCellHeadV5::new(
        cell.clone(),
        state_sha,
        digest("features"),
        weights,
        bias,
        if gated {
            TrainedCellModeV5::Gated { a, g }
        } else {
            TrainedCellModeV5::Linear
        },
    ));
    let serving = must(TrainedCellBundleV5::new(
        id("development-candidate"),
        must(Generation::new(2)),
        digest("encoder"),
        vec![0.01; 384 * 8],
        vec![head],
    ));
    let actions: Vec<Vec<f64>> = (0..8).map(|step| vec![0.001 * (step as f64); p]).collect();
    let plan = state::tensor_digest(
        &[8, p],
        &actions.iter().flatten().copied().collect::<Vec<_>>(),
    );
    let source = must(serde_json::to_string(
        &json!({"schema":"hepta.cell-field-controller.v7",
        "authority":"DENY_ALL","production_authority":false,
        "warmup_step_count":64,"registered_steps":32,
        "plan_origin_state_sha256":digest("origin16").to_string(),
        "original_warmup_state_sha256":digest("warmup").to_string(),
        "intended_plan_sha256":digest("intended").to_string(),
        "protocol_sha256":digest("protocol").to_string(),"contract":{
            "protocol_sha256":digest("protocol").to_string(),
            "optimizer_origin_protocol_sha256":digest("historical-optimizer-protocol").to_string(),
            "controller_source_sha256":digest("controller-code").to_string()},
        "full_state_sha256":state_sha.to_string(),"absolute_step":17,"plan_origin_step":16,
        "action_cursor":1,"plan_horizon":8,"resolved_plan_sha256":plan.to_string(),
        "qualification_only":true}),
    ));
    let controller = json!({"schema":"hepta.cell-controller-handoff.v7",
        "resume_boundary":"committed-state-with-frozen-plan","protocol_sha256":digest("protocol").to_string(),
        "optimizer_origin_protocol_sha256":digest("historical-optimizer-protocol").to_string(),
        "controller_source_sha256":digest("controller-code").to_string(),
        "state_sha256":state_sha.to_string(),"warmup_step_count":64,"absolute_step":17,"registered_steps":32,
        "plan_origin_step":16,"action_cursor":1,"plan_horizon":8,"resolved_plan_sha256":plan.to_string(),
        "source_controller_json":source,"source_controller_sha256":digest(&source).to_string(),
        "plan_origin_state_sha256":digest("origin16").to_string(),"original_warmup_state_sha256":digest("warmup").to_string(),
        "intended_plan_sha256":digest("intended").to_string(),"panel_anchors_sha256":digest("original-anchors").to_string(),
        "panel_identity_sha256":digest("panels").to_string(),"controller_config_sha256":digest("config").to_string(),
        "receipt_chain_sha256":digest("receipts").to_string()});
    let checkpoint = must(CellTrainingCheckpointV7::new(
        cell,
        metadata,
        vector,
        must(serde_json::to_vec(&controller)),
        actions,
    ));
    (serving, checkpoint)
}

fn wrap(
    serving: TrainedCellBundleV5,
    checkpoint: CellTrainingCheckpointV7,
) -> Result<TrainingHandoffBundleV7, TrainingHandoffErrorV7> {
    TrainingHandoffBundleV7::new(
        serving,
        digest("protocol"),
        Some(digest("immutable-predecessor")),
        vec![checkpoint],
    )
}

#[test]
fn exact_linear_and_gated_full_state_roundtrip_preserves_seven_pending_actions() {
    for gated in [false, true] {
        let (serving, checkpoint) = fixture(gated);
        let bundle = must(wrap(serving.clone(), checkpoint.clone()));
        let decoded = must(TrainingHandoffBundleV7::decode(
            &bundle.encode(),
            bundle.content_digest(),
        ));
        assert_eq!(decoded, bundle);
        assert_eq!(
            decoded.checkpoints()[0].pending_actions(),
            &checkpoint.planned_actions()[1..]
        );
        assert_eq!(decoded.checkpoints()[0].pending_actions().len(), 7);
        let cell = serving.heads()[0].cell_id();
        let input = vec![0.3; 384];
        assert_eq!(
            must(
                decoded
                    .serving()
                    .evaluate(&serving.input_binding(), cell, &input)
            ),
            must(serving.evaluate(&serving.input_binding(), cell, &input))
        );
    }
}

#[test]
fn absent_external_digest_truncation_extension_and_tampering_reject() {
    let (serving, checkpoint) = fixture(/*gated*/ true);
    let bundle = must(wrap(serving, checkpoint));
    let bytes = bundle.encode();
    assert_eq!(
        TrainingHandoffBundleV7::decode(&bytes, Digest32::ZERO),
        Err(TrainingHandoffErrorV7::Digest)
    );
    for count in [0, 8, 41, 100, bytes.len() - 1] {
        assert!(
            TrainingHandoffBundleV7::decode(&bytes[..count], Digest32::of_bytes(&bytes[..count]))
                .is_err()
        );
    }
    let mut extra = bytes.clone();
    extra.push(0);
    assert!(TrainingHandoffBundleV7::decode(&extra, Digest32::of_bytes(&extra)).is_err());
    let mut changed = bytes;
    let n = changed.len();
    changed[n - 1] ^= 1;
    assert!(TrainingHandoffBundleV7::decode(&changed, bundle.content_digest()).is_err());
}

#[test]
fn serving_theta_and_all_optimizer_metadata_are_bound() {
    for field in [
        "step_count",
        "sampler_draw_count",
        "external_batch_count",
        "rng",
        "active_context",
    ] {
        let (serving, mut checkpoint) = fixture(/*gated*/ true);
        let mut metadata: Value = must(serde_json::from_slice(&checkpoint.state_metadata_json));
        metadata[field] = json!(1);
        checkpoint.state_metadata_json = must(serde_json::to_vec(&metadata));
        assert!(wrap(serving, checkpoint).is_err(), "{field}");
    }
    for offset in [0, 52, 104] {
        let (serving, mut checkpoint) = fixture(/*gated*/ true);
        checkpoint.state_vector[offset] += 0.1;
        assert!(wrap(serving, checkpoint).is_err());
    }
    let (serving, mut checkpoint) = fixture(/*gated*/ false);
    checkpoint.state_vector[0] = -0.0;
    // Even replacing the serving head's complete-state commitment cannot
    // disguise different theta bits in the two representations.
    let mut wire = serving.encode();
    let offset = 8
        + 2
        + serving.artifact_id().as_str().len()
        + 8
        + 32
        + 384 * 8 * 8
        + 2
        + 2
        + serving.heads()[0].cell_id().as_str().len();
    wire[offset..offset + 32].copy_from_slice(
        state::state_digest(&checkpoint.state_metadata_json, &checkpoint.state_vector).as_array(),
    );
    let rebound = must(TrainedCellBundleV5::decode(
        &wire,
        Digest32::of_bytes(&wire),
    ));
    assert_eq!(
        wrap(rebound, checkpoint),
        Err(TrainingHandoffErrorV7::State)
    );
}

#[test]
fn plan_cursor_clock_original_source_and_frozen_actions_cannot_diverge() {
    for (field, value) in [
        ("action_cursor", json!(2)),
        ("absolute_step", json!(18)),
        (
            "optimizer_origin_protocol_sha256",
            json!(digest("rewritten-history").to_string()),
        ),
        (
            "controller_source_sha256",
            json!(digest("unbound-controller").to_string()),
        ),
        ("warmup_step_count", json!(63)),
        ("plan_origin_step", json!(15)),
        ("plan_horizon", json!(7)),
        ("resume_boundary", json!("interrupted-inner-solve")),
        ("source_controller_json", json!("{}")),
        ("resolved_plan_sha256", json!(digest("other").to_string())),
    ] {
        let (serving, mut checkpoint) = fixture(/*gated*/ true);
        let mut controller: Value =
            must(serde_json::from_slice(&checkpoint.controller_metadata_json));
        controller[field] = value;
        checkpoint.controller_metadata_json = must(serde_json::to_vec(&controller));
        assert!(wrap(serving, checkpoint).is_err(), "{field}");
    }
    let (serving, mut checkpoint) = fixture(/*gated*/ true);
    checkpoint.planned_actions[7][0] += 0.01;
    assert!(wrap(serving, checkpoint).is_err());
}

#[test]
fn rehashed_controller_cannot_hide_a_different_original_snapshot() {
    let (serving, mut checkpoint) = fixture(/*gated*/ false);
    let mut controller: Value = must(serde_json::from_slice(&checkpoint.controller_metadata_json));
    let mut original: Value = must(serde_json::from_str(must(
        controller["source_controller_json"]
            .as_str()
            .ok_or("source"),
    )));
    original["action_cursor"] = json!(2);
    let source = must(serde_json::to_string(&original));
    controller["source_controller_json"] = json!(source);
    controller["source_controller_sha256"] = json!(digest(&source).to_string());
    checkpoint.controller_metadata_json = must(serde_json::to_vec(&controller));
    assert!(wrap(serving, checkpoint).is_err());
}
