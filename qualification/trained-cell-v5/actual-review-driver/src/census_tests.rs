use super::*;
use pretty_assertions::assert_eq;

fn fixture() -> (Value, Value, Value) {
    let policies = ["zero", "h1", "guarded", "loss2", "adjoint", "candidate"];
    let required = ["candidate", "h1", "loss2"];
    let mut records = Vec::new();
    let mut costs = Vec::new();
    let mut completion = Vec::new();
    for task in TASKS {
        for head in HEADS {
            for seed in SEEDS {
                for policy in policies {
                    costs.push(json!({"task":task,"head":head,"seed":seed,"policy":policy,"valid_record":true,"status":"completed","completed_steps":32,"registered_steps":32,"cpu_ns":if policy=="candidate" {6} else {3}}));
                    for split in ["current", "future", "old"] {
                        records.push(json!({"task":task,"head":head,"seed":seed,"policy":policy,"split":split,"status":"completed","execution_status":"completed","completed_steps":32}));
                    }
                    if required.contains(&policy) {
                        completion.push(json!({"task":task,"head":head,"seed":seed,"policy":policy,"required_steps":32,"status":"completed","completed_steps":32,"criterion_met":true}));
                    }
                }
                records.push(json!({"task":task,"head":head,"seed":seed,"policy":"warmup_old","split":"old","status":"completed"}));
            }
        }
    }
    (
        json!({"records":records,"cost_records":costs,"completion_gates":completion,"registered_fits":12,"registered_policy_outputs":72,
        "census_complete":true,"cost_census_complete":true,"required_completion_met":true,"candidate_completed_fits":12}),
        json!({"census_complete":true,"cost_census_complete":true,"required_completion_met":true}),
        json!({"evaluation":{"policies":policies,"required_completed_policies":required,"required_completed_steps":32,"candidate":"candidate"}}),
    )
}

fn stop(report: &mut Value, policy: &str) {
    for row in report["cost_records"].as_array_mut().into_iter().flatten() {
        if row["task"] == TASKS[0]
            && row["head"] == HEADS[0]
            && row["seed"] == SEEDS[0]
            && row["policy"] == policy
        {
            row["status"] = json!("not_executed_infeasible");
            row["completed_steps"] = json!(24);
        }
    }
    for row in report["records"].as_array_mut().into_iter().flatten() {
        if row["task"] == TASKS[0]
            && row["head"] == HEADS[0]
            && row["seed"] == SEEDS[0]
            && row["policy"] == policy
        {
            row["execution_status"] = json!("not_executed_infeasible");
            row["completed_steps"] = json!(24);
        }
    }
    for row in report["completion_gates"]
        .as_array_mut()
        .into_iter()
        .flatten()
    {
        if row["task"] == TASKS[0]
            && row["head"] == HEADS[0]
            && row["seed"] == SEEDS[0]
            && row["policy"] == policy
        {
            row["status"] = json!("not_executed_infeasible");
            row["completed_steps"] = json!(24);
            row["criterion_met"] = json!(false);
        }
    }
}

#[test]
fn complete_fixed_census_and_stopped_nonrequired_diagnostic_remain_distinct() {
    let (mut report, gate, protocol) = fixture();
    assert_eq!(verify(&report, &gate, &protocol).ok(), Some(true));
    stop(&mut report, "zero");
    assert_eq!(verify(&report, &gate, &protocol).ok(), Some(true));
}

#[test]
fn candidate_stopping_at24_is_unavailable_and_forged_completion_flags_reject() {
    let (mut report, mut gate, protocol) = fixture();
    stop(&mut report, "candidate");
    report["required_completion_met"] = json!(false);
    report["candidate_completed_fits"] = json!(11);
    gate["required_completion_met"] = json!(false);
    assert_eq!(verify(&report, &gate, &protocol).ok(), Some(false));
    gate["required_completion_met"] = json!(true);
    assert!(verify(&report, &gate, &protocol).is_err());
}

#[test]
fn missing_or_duplicated_fixed_family_members_cannot_pass() {
    let (report, gate, protocol) = fixture();
    let mut changed = report.clone();
    changed["cost_records"][1] = changed["cost_records"][0].clone();
    assert!(verify(&changed, &gate, &protocol).is_err());
    let mut changed = report.clone();
    changed["completion_gates"].as_array_mut().map(Vec::pop);
    assert!(verify(&changed, &gate, &protocol).is_err());
    let mut changed = report;
    changed["records"][0]["policy"] = json!("unregistered");
    assert!(verify(&changed, &gate, &protocol).is_err());
}

#[test]
fn aggregate_cpu_ratio_must_equal_raw_paired_timings() {
    let (report, _, _) = fixture();
    let mut row = json!({"task":TASKS[0],"head":HEADS[0],"candidate":"candidate","baseline":"h1","cpu_ratio":2.0,"paired_seed_cpu_ratios":[2.0,2.0,2.0]});
    assert!(verify_ratio(&report, &row).is_ok());
    row["cpu_ratio"] = json!(1.0);
    assert!(verify_ratio(&report, &row).is_err());
}
