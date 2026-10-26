//! Verify transport consistency of the V8 controller. Actual old-panel safety
//! still requires the pinned research loader and prospective nonlinear replay.
use crate::TrainingHandoffErrorV7 as Error;
use crate::training_handoff_v7::tensor_digest;
use codex_hepta_types::Digest32;
use serde_json::Value;
use std::collections::BTreeSet;

fn count(value: &Value, name: &str) -> Result<u64, Error> {
    value[name]
        .as_u64()
        .filter(|n| *n < (1_u64 << 63))
        .ok_or(Error::Controller)
}
fn hash(value: &Value, name: &str) -> Result<Digest32, Error> {
    let hash: Digest32 = value[name]
        .as_str()
        .ok_or(Error::Controller)?
        .parse()
        .map_err(|_| Error::Controller)?;
    if hash.is_zero() {
        return Err(Error::Controller);
    }
    Ok(hash)
}
fn number(value: &Value, name: &str) -> Result<f64, Error> {
    value[name]
        .as_f64()
        .filter(|n| n.is_finite())
        .ok_or(Error::Controller)
}
fn actions(value: &Value, name: &str, h: usize, p: usize, bound: f64) -> Result<Vec<f64>, Error> {
    let rows = value[name].as_array().ok_or(Error::Controller)?;
    if rows.len() != h {
        return Err(Error::Controller);
    }
    let mut values = Vec::with_capacity(h * p);
    for row in rows {
        let row = row.as_array().ok_or(Error::Controller)?;
        if row.len() != p {
            return Err(Error::Controller);
        }
        for v in row {
            values.push(
                v.as_f64()
                    .filter(|n| n.is_finite() && n.abs() <= bound)
                    .ok_or(Error::Controller)?,
            );
        }
    }
    Ok(values)
}

pub(crate) fn validate(
    wrapper: &Value,
    source: &Value,
    resolved: &[Vec<f64>],
    p: usize,
    step: u64,
    origin: u64,
    cursor: u64,
    registered: u64,
) -> Result<(), Error> {
    let contract = &source["contract"];
    let config = &contract["configuration"];
    let fields: BTreeSet<_> = config
        .as_object()
        .ok_or(Error::Controller)?
        .keys()
        .map(String::as_str)
        .collect();
    let expected = BTreeSet::from([
        "steps",
        "dt",
        "effort_price",
        "action_bound",
        "old_weight",
        "current_dispersion",
        "relinearizations",
        "commit_stride",
    ]);
    let policy = contract["policy"].as_str().ok_or(Error::Controller)?;
    let stride = count(config, "commit_stride")?;
    let dt = number(config, "dt")?;
    let effort = number(config, "effort_price")?;
    let bound = number(config, "action_bound")?;
    let old = number(config, "old_weight")?;
    let dispersion = number(config, "current_dispersion")?;
    if contract["schema"] != "hepta.cell-field-controller-contract.v8"
        || registered != 32
        || contract["registered_steps"] != 32
        || contract["parameter_count"] != p
        || source["policy"] != policy
        || fields != expected
        || config["steps"] != 32
        || ![1, 2, 4, 8].contains(&stride)
        || count(config, "relinearizations")? != 0
        || !(0.0 < dt
            && dt <= 1.0
            && 0.0 < effort
            && effort <= 100.0
            && 0.0 < bound
            && bound <= 1e6)
        || !(0.0..=10.0).contains(&old)
        || !(0.0..=0.5).contains(&dispersion)
        || !["myopic_h1", "loss2_h8", "full_h8", "future_field_h8"].contains(&policy)
        || contract["forecast_tail_safety_claimed"] != false
        || contract["independent_online_certificate"] != false
        || contract["safety_filter"] != "single_ray_then_joint_v8"
        || contract["proposal_rule"] != "risk_effort_box_v8"
        || source["original_warmup_state_sha256"] != contract["original_warmup_state_sha256"]
        || source["warmup_step_count"] != contract["warmup_step_count"]
        || source["failure_ledger"] != serde_json::json!([])
        || source["run_status"] != if step == 32 { "completed" } else { "active" }
    {
        return Err(Error::Controller);
    }
    let stride = if policy == "myopic_h1" { 1 } else { stride };
    let horizon = resolved.len();
    let forecast = count(source, "forecast_horizon")? as usize;
    let expected_forecast = if horizon == 0 {
        0
    } else {
        if policy == "myopic_h1" { 1 } else { 8 }.min(32 - origin)
    };
    if !origin.is_multiple_of(stride)
        || origin + horizon as u64 > 32
        || (horizon == 0 && (step != 0 || forecast != 0))
        || (horizon != 0 && horizon as u64 != stride.min(32 - origin))
        || forecast as u64 != expected_forecast
        || horizon > forecast
        || wrapper["forecast_horizon"] != source["forecast_horizon"]
        || hash(wrapper, "forecast_plan_sha256")? != hash(source, "forecast_plan_sha256")?
    {
        return Err(Error::Controller);
    }
    let box_limit = bound / (p as f64).sqrt();
    let forecast_actions = actions(source, "forecast_actions", forecast, p, box_limit)?;
    let intended = actions(source, "intended_actions", horizon, p, box_limit)?;
    let actual = actions(source, "resolved_actions", horizon, p, box_limit)?;
    if hash(source, "forecast_plan_sha256")? != tensor_digest(&[forecast, p], &forecast_actions)
        || hash(source, "intended_plan_sha256")? != tensor_digest(&[horizon, p], &intended)
        || hash(source, "resolved_plan_sha256")? != tensor_digest(&[horizon, p], &actual)
        || intended
            .iter()
            .zip(&forecast_actions)
            .any(|(a, b)| a.to_bits() != b.to_bits())
        || actual
            .iter()
            .zip(resolved.iter().flatten())
            .any(|(a, b)| a.to_bits() != b.to_bits())
    {
        return Err(Error::Controller);
    }
    let states = source["plan_state_sha256"]
        .as_array()
        .ok_or(Error::Controller)?;
    let receipts = source["plan_receipt_sha256"]
        .as_array()
        .ok_or(Error::Controller)?;
    let chain = source["certificate_chain"]
        .as_array()
        .ok_or(Error::Controller)?;
    let counters = &source["counters"];
    let counter_keys: BTreeSet<_> = counters
        .as_object()
        .ok_or(Error::Controller)?
        .keys()
        .map(String::as_str)
        .collect();
    if counter_keys
        != BTreeSet::from([
            "plans",
            "proposal_calls",
            "response_optimizer_steps",
            "qp_calls",
            "actual_merit_rollout_steps",
            "repair_optimizer_updates",
            "repair_panel_evaluations",
            "resume_verification_updates",
            "committed_steps",
            "controller_cpu_ns",
        ])
    {
        return Err(Error::Controller);
    }
    for value in counters.as_object().ok_or(Error::Controller)?.values() {
        if value.as_u64().is_none_or(|v| v >= (1_u64 << 63)) {
            return Err(Error::Controller);
        }
    }
    if states.len() != horizon + 1
        || receipts.len() != horizon
        || chain.len() > 32
        || states[0] != source["plan_origin_state_sha256"]
        || states[cursor as usize] != source["full_state_sha256"]
        || count(&source["receipt_chain"], "count")? != step
        || count(counters, "committed_steps")? != step
        || count(counters, "plans")? != chain.len() as u64
        || count(counters, "proposal_calls")? != chain.len() as u64
        || count(counters, "qp_calls")? != 0
        || count(counters, "actual_merit_rollout_steps")? != 0
    {
        return Err(Error::Controller);
    }
    for digest in states.iter().chain(receipts) {
        let value: Digest32 = digest
            .as_str()
            .ok_or(Error::Controller)?
            .parse()
            .map_err(|_| Error::Controller)?;
        if value.is_zero() {
            return Err(Error::Controller);
        }
    }
    let mut response_steps = 0;
    for (index, entry) in chain.iter().enumerate() {
        let origin = count(entry, "origin_step")?;
        if origin != index as u64 * stride || origin >= 32 {
            return Err(Error::Controller);
        }
        response_steps += if policy == "myopic_h1" { 1 } else { 8 }.min(32 - origin);
        for field in [
            "origin_state_sha256",
            "plan_sha256",
            "repair_sha256",
            "resolved_plan_sha256",
            "forecast_plan_sha256",
        ] {
            hash(entry, field)?;
        }
    }
    if count(counters, "response_optimizer_steps")? != response_steps
        || (horizon == 0 && !chain.is_empty())
        || (horizon > 0
            && chain.last().is_none_or(|entry| {
                entry["origin_step"] != origin
                    || entry["resolved_plan_sha256"] != source["resolved_plan_sha256"]
                    || entry["forecast_plan_sha256"] != source["forecast_plan_sha256"]
            }))
    {
        return Err(Error::Controller);
    }
    Ok(())
}
