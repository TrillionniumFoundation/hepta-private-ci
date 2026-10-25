//! Independently reconstruct the fixed prediction, execution and completion
//! census from the bound evaluator report. This does not redo the bootstrap.

use crate::Result;
use crate::ensure;
use crate::report::HEADS;
use crate::report::SEEDS;
use crate::report::TASKS;
use crate::report::array;
use crate::report::key;
use crate::report::number;
use crate::report::string;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeMap;
use std::collections::BTreeSet;

fn policies(protocol: &Value, field: &str) -> Result<Vec<String>> {
    array(&protocol["evaluation"], field)?
        .iter()
        .map(|v| {
            v.as_str()
                .map(str::to_owned)
                .ok_or_else(|| "invalid policy identity".into())
        })
        .collect()
}

fn valid_cost(row: &Value) -> bool {
    row["valid_record"] == true && row["cpu_ns"].as_u64().is_some_and(|v| v > 0)
}

fn completed(row: &Value) -> bool {
    valid_cost(row)
        && row["status"] == "completed"
        && row["completed_steps"] == 32
        && row["registered_steps"] == 32
}

pub fn verify(report: &Value, gate: &Value, protocol: &Value) -> Result<bool> {
    let all = policies(protocol, "policies")?;
    let required = policies(protocol, "required_completed_policies")?;
    let candidate = string(&protocol["evaluation"], "candidate")?;
    ensure(
        all.len() == 6
            && all.iter().collect::<BTreeSet<_>>().len() == 6
            && required.len() == 3
            && required.iter().collect::<BTreeSet<_>>().len() == 3
            && required.iter().all(|p| all.contains(p))
            && protocol["evaluation"]["required_completed_steps"] == 32,
        "unexpected frozen completion policy",
    )?;
    let fields = ["task", "head", "seed", "policy"];
    let mut cost_keys = BTreeSet::new();
    let mut completion_keys = BTreeSet::new();
    let mut prediction_keys = BTreeSet::new();
    for task in TASKS {
        for head in HEADS {
            for seed in SEEDS {
                for policy in &all {
                    let row = json!({"task":task,"head":head,"seed":seed,"policy":policy});
                    cost_keys.insert(key(&row, &fields));
                    if required.contains(policy) {
                        completion_keys.insert(key(&row, &fields));
                    }
                    for split in ["current", "future", "old"] {
                        prediction_keys.insert(key(&json!({"task":task,"head":head,"seed":seed,"policy":policy,"split":split}),&["task","head","seed","policy","split"]));
                    }
                }
                prediction_keys.insert(key(&json!({"task":task,"head":head,"seed":seed,"policy":"warmup_old","split":"old"}),&["task","head","seed","policy","split"]));
            }
        }
    }
    let costs = array(report, "cost_records")?;
    let by_key: BTreeMap<_, _> = costs.iter().map(|row| (key(row, &fields), row)).collect();
    ensure(
        costs.len() == 72
            && by_key.len() == costs.len()
            && by_key.keys().cloned().collect::<BTreeSet<_>>() == cost_keys,
        "cost record census differs",
    )?;
    let records = array(report, "records")?;
    let keys: BTreeSet<_> = records
        .iter()
        .map(|row| key(row, &["task", "head", "seed", "policy", "split"]))
        .collect();
    ensure(
        records.len() == 228
            && keys.len() == records.len()
            && keys == prediction_keys
            && report["registered_fits"] == 12
            && report["registered_policy_outputs"] == 72,
        "prediction census differs",
    )?;
    for row in records.iter().filter(|row| row["policy"] != "warmup_old") {
        let cost = by_key
            .get(&key(row, &fields))
            .ok_or("missing matching execution")?;
        ensure(
            row["execution_status"] == cost["status"]
                && row["completed_steps"] == cost["completed_steps"],
            "prediction/execution status disagrees",
        )?;
    }
    let completion = array(report, "completion_gates")?;
    let keys: BTreeSet<_> = completion.iter().map(|row| key(row, &fields)).collect();
    ensure(
        completion.len() == 36 && keys.len() == completion.len() && keys == completion_keys,
        "required completion census differs",
    )?;
    let mut all_completed = true;
    let mut candidate_count = 0;
    for row in completion {
        let cost = by_key
            .get(&key(row, &fields))
            .ok_or("missing required execution")?;
        let complete = completed(cost);
        ensure(
            row["required_steps"] == 32
                && row["status"] == cost["status"]
                && row["completed_steps"] == cost["completed_steps"]
                && row["criterion_met"] == complete,
            "required execution attestation disagrees",
        )?;
        all_completed &= complete;
        if row["policy"] == candidate && complete {
            candidate_count += 1;
        }
    }
    let cost_census = costs.iter().all(valid_cost);
    let census = records.iter().all(|row| row["status"] == "completed")
        && costs.iter().all(|row| row["valid_record"] == true);
    ensure(
        report["census_complete"] == census
            && report["cost_census_complete"] == cost_census
            && report["required_completion_met"] == all_completed
            && report["candidate_completed_fits"] == candidate_count
            && gate["census_complete"] == census
            && gate["cost_census_complete"] == cost_census
            && gate["required_completion_met"] == all_completed,
        "recomputed census flags disagree",
    )?;
    Ok(census && cost_census && all_completed)
}

pub fn verify_ratio(report: &Value, row: &Value) -> Result<()> {
    let mut sums = [0_u64; 2];
    let mut ratios = Vec::new();
    for seed in SEEDS {
        let mut pair = [0_u64; 2];
        for (index, policy) in [string(row, "candidate")?, string(row, "baseline")?]
            .iter()
            .enumerate()
        {
            let cost = array(report, "cost_records")?
                .iter()
                .find(|r| {
                    r["task"] == row["task"]
                        && r["head"] == row["head"]
                        && r["seed"] == seed
                        && r["policy"] == *policy
                })
                .ok_or("paired CPU record missing")?;
            ensure(valid_cost(cost), "invalid paired CPU observation")?;
            pair[index] = cost["cpu_ns"].as_u64().ok_or("integer CPU time required")?;
            sums[index] = sums[index]
                .checked_add(pair[index])
                .ok_or("CPU total overflow")?;
        }
        ratios.push(pair[0] as f64 / pair[1] as f64);
    }
    ensure(
        number(row, "cpu_ratio")? == sums[0] as f64 / sums[1] as f64
            && row["paired_seed_cpu_ratios"] == json!(ratios),
        "CPU ratio differs from raw paired timings",
    )?;
    Ok(())
}

#[cfg(test)]
#[path = "census_tests.rs"]
mod tests;
