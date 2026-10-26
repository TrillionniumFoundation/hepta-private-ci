//! Reconstruct the full registered family; policy count is profile-bound rather
//! than fixed to one historical study. Independent audits redo the statistics.
use crate::Result;
use crate::ensure;
use crate::profile::HEADS;
use crate::profile::SEEDS;
use crate::profile::TASKS;
use crate::report::array;
use crate::report::key;
use crate::report::string;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeMap;
use std::collections::BTreeSet;

pub fn verify(report: &Value, gate: &Value, protocol: &Value) -> Result<bool> {
    let e = &protocol["evaluation"];
    let policies = array(e, "policies")?;
    let required = array(e, "required_completed_policies")?;
    let fields = ["task", "head", "seed", "policy"];
    let mut expected_costs = BTreeSet::new();
    let mut expected_complete = BTreeSet::new();
    let mut expected_predictions = BTreeSet::new();
    for task in TASKS {
        for head in HEADS {
            for seed in SEEDS {
                for policy in policies {
                    let row = json!({"task":task,"head":head,"seed":seed,"policy":policy});
                    expected_costs.insert(key(&row, &fields));
                    if required.contains(policy) {
                        expected_complete.insert(key(&row, &fields));
                    }
                    for split in ["current", "future", "old"] {
                        expected_predictions.insert(key(
                            &json!({"task":task,"head":head,"seed":seed,
                    "policy":policy,"split":split}),
                            &["task", "head", "seed", "policy", "split"],
                        ));
                    }
                }
                expected_predictions.insert(key(
                    &json!({"task":task,"head":head,"seed":seed,
            "policy":"warmup_old","split":"old"}),
                    &["task", "head", "seed", "policy", "split"],
                ));
            }
        }
    }
    let costs = array(report, "cost_records")?;
    let by_key: BTreeMap<_, _> = costs.iter().map(|row| (key(row, &fields), row)).collect();
    ensure(
        costs.len() == expected_costs.len()
            && by_key.len() == costs.len()
            && by_key.keys().cloned().collect::<BTreeSet<_>>() == expected_costs,
        "cost record census differs",
    )?;
    let records = array(report, "records")?;
    let keys: BTreeSet<_> = records
        .iter()
        .map(|row| key(row, &["task", "head", "seed", "policy", "split"]))
        .collect();
    ensure(
        records.len() == expected_predictions.len()
            && keys.len() == records.len()
            && keys == expected_predictions
            && report["registered_fits"] == 12
            && report["registered_policy_outputs"] == costs.len(),
        "prediction census differs",
    )?;
    for row in records.iter().filter(|row| row["policy"] != "warmup_old") {
        let cost = by_key
            .get(&key(row, &fields))
            .ok_or("matching execution missing")?;
        ensure(
            row["execution_status"] == cost["status"]
                && row["completed_steps"] == cost["completed_steps"],
            "prediction/execution completion differs",
        )?;
    }
    let completion = array(report, "completion_gates")?;
    let keys: BTreeSet<_> = completion.iter().map(|row| key(row, &fields)).collect();
    ensure(
        completion.len() == 36 && keys.len() == 36 && keys == expected_complete,
        "required completion census differs",
    )?;
    let valid_cost =
        |row: &Value| row["valid_record"] == true && row["cpu_ns"].as_u64().is_some_and(|n| n > 0);
    let mut all_completed = true;
    let mut candidate_count = 0;
    for row in completion {
        let cost = by_key
            .get(&key(row, &fields))
            .ok_or("required execution missing")?;
        let complete = valid_cost(cost)
            && cost["status"] == "completed"
            && cost["completed_steps"] == 32
            && cost["registered_steps"] == 32;
        ensure(
            row["required_steps"] == 32
                && row["status"] == cost["status"]
                && row["completed_steps"] == cost["completed_steps"]
                && row["criterion_met"] == complete,
            "completion attestation differs",
        )?;
        all_completed &= complete;
        if row["policy"] == string(e, "candidate")? && complete {
            candidate_count += 1;
        }
    }
    let cost_census = costs.iter().all(valid_cost);
    let census = records.iter().all(|row| row["status"] == "completed")
        && costs.iter().all(|row| row["valid_record"] == true);
    for value in [report, gate] {
        ensure(
            value["census_complete"] == census
                && value["cost_census_complete"] == cost_census
                && value["required_completion_met"] == all_completed,
            "recomputed census flags differ",
        )?;
    }
    ensure(
        report["candidate_completed_fits"] == candidate_count,
        "candidate completion count differs",
    )?;
    Ok(census && cost_census && all_completed)
}
