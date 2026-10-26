//! Complete V8 controller fields for synthetic owner qualification only.
use super::*;
use codex_hepta_neuron::CellTrainingCheckpointV7;

pub fn snapshot(
    source: &mut Value,
    wrapper: &mut Value,
    checkpoint: &CellTrainingCheckpointV7,
) -> Result<()> {
    let p = checkpoint.state_vector().len() / 3;
    let horizon = checkpoint.planned_actions().len();
    let step = source["absolute_step"].as_u64().ok_or("step")?;
    let origin = source["plan_origin_step"].as_u64().ok_or("origin")?;
    let cursor = source["action_cursor"].as_u64().ok_or("cursor")? as usize;
    let actions = json!(checkpoint.planned_actions());
    source["schema"] = json!("hepta.cell-field-controller.v8");
    source["policy"] = json!("future_field_h8");
    source["intended_actions"] = actions.clone();
    source["resolved_actions"] = actions.clone();
    source["forecast_actions"] = actions;
    source["forecast_horizon"] = json!(horizon);
    source["forecast_plan_sha256"] = source["resolved_plan_sha256"].clone();
    let mut states: Vec<_> = (0..=horizon)
        .map(|i| json!(owner::digest(&format!("synthetic plan state {i}")).to_string()))
        .collect();
    states[0] = source["plan_origin_state_sha256"].clone();
    states[cursor] = source["full_state_sha256"].clone();
    source["plan_state_sha256"] = json!(states);
    source["plan_receipt_sha256"] = json!(
        (0..horizon)
            .map(|i| owner::digest(&format!("synthetic plan receipt {i}")).to_string())
            .collect::<Vec<_>>()
    );
    let mut chain = Vec::new();
    if horizon > 0 {
        for index in (0..=origin).step_by(8) {
            chain.push(json!({"origin_step":index,"origin_state_sha256":owner::digest("synthetic origin").to_string(),
                "plan_sha256":owner::digest("synthetic plan").to_string(),"repair_sha256":owner::digest("synthetic repair").to_string(),
                "resolved_plan_sha256":source["resolved_plan_sha256"],"forecast_plan_sha256":source["forecast_plan_sha256"]}));
        }
    }
    source["counters"] = json!({"plans":chain.len(),"proposal_calls":chain.len(),"response_optimizer_steps":8*chain.len(),
        "qp_calls":0,"actual_merit_rollout_steps":0,"repair_optimizer_updates":0,"repair_panel_evaluations":0,
        "resume_verification_updates":0,"committed_steps":step,"controller_cpu_ns":1});
    source["certificate_chain"] = json!(chain);
    let warmup = source["original_warmup_state_sha256"].clone();
    let contract = &mut source["contract"];
    contract["schema"] = json!("hepta.cell-field-controller-contract.v8");
    contract["policy"] = json!("future_field_h8");
    contract["original_warmup_state_sha256"] = warmup;
    contract["warmup_step_count"] = json!(64);
    contract["parameter_count"] = json!(p);
    contract["configuration"] = json!({"steps":32,"commit_stride":8,"relinearizations":0,
        "dt":0.1,"effort_price":1.0,"action_bound":1.0,"old_weight":0.1,"current_dispersion":0.1});
    contract["forecast_tail_safety_claimed"] = json!(false);
    contract["independent_online_certificate"] = json!(false);
    contract["safety_filter"] = json!("single_ray_then_joint_v8");
    contract["proposal_rule"] = json!("risk_effort_box_v8");
    wrapper["schema"] = json!("hepta.cell-controller-handoff.v8");
    wrapper["forecast_horizon"] = source["forecast_horizon"].clone();
    wrapper["forecast_plan_sha256"] = source["forecast_plan_sha256"].clone();
    let chain = json!({"certificate_chain":source["certificate_chain"],"receipt_chain":source["receipt_chain"],"counters":source["counters"]});
    wrapper["receipt_chain_sha256"] =
        json!(Digest32::of_bytes(&serde_json::to_vec(&chain)?).to_string());
    Ok(())
}
