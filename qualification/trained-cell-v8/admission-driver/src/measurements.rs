//! Fixed scientific gates, independently aggregated from all bound contrasts.
use crate::Result;
use crate::ensure;
use crate::profile::HEADS;
use crate::profile::TASKS;
use crate::report::array;
use crate::report::hash;
use crate::report::key;
use crate::report::number;
use crate::report::string;
use codex_hepta_learning_artifacts::ScientificCandidatePolicyV1;
use codex_hepta_learning_artifacts::ScientificComparisonPolicyV1;
use codex_hepta_learning_artifacts::ScientificMeasurementStatusV1;
use codex_hepta_learning_artifacts::ScientificMeasurementV1;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeSet;

pub struct Scores {
    pub policy: ScientificCandidatePolicyV1,
    pub measurements: [ScientificMeasurementStatusV1; 3],
    pub aggregate: Value,
    pub passed: bool,
}

pub fn evaluate(protocol: &Value, report: &Value, gate: &Value, census: bool) -> Result<Scores> {
    let protocol_digest = hash(gate, "protocol_sha256")?;
    let report_digest = hash(gate, "report_sha256")?;
    let e = &protocol["evaluation"];
    let candidate = string(e, "candidate")?;
    let baselines = array(e, "primary_future_baselines")?;
    let primary = array(report, "primary_contrasts")?;
    let costs = array(report, "cost_contrasts")?;
    ensure(
        primary.len() == 12 && costs.len() == 4,
        "full12 science and4 cost contrasts required",
    )?;
    let mut seen = BTreeSet::new();
    let mut seen_cost = BTreeSet::new();
    let mut observations = [u64::MAX, u64::MAX, 3];
    let mut estimates = [f64::NEG_INFINITY; 3];
    let mut uppers = [f64::NEG_INFINITY; 3];
    let mut available = [census; 3];
    for row in primary {
        let task = string(row, "task")?;
        ensure(
            TASKS.contains(&task)
                && HEADS.contains(&string(row, "head")?)
                && row["candidate"] == candidate,
            "primary contrast identity differs",
        )?;
        let group = if row["split"] == "future" && baselines.contains(&row["baseline"]) {
            0
        } else if row["split"] == "old" && row["baseline"] == "warmup_old" {
            1
        } else {
            return Err("unregistered primary comparison".into());
        };
        ensure(
            seen.insert(key(row, &["task", "head", "split", "baseline"]))
                && number(row, "threshold")? == [-0.001, 0.0][group],
            "duplicate comparison or altered threshold",
        )?;
        if row["status"] != "completed" {
            available[group] = false;
            continue;
        }
        let count = row["source_components"]
            .as_u64()
            .ok_or("source census missing")?;
        let expected = protocol["source_counts"][task][if group == 0 {
            "future_test"
        } else {
            "old_test"
        }]
        .as_u64()
        .ok_or("frozen source count missing")?;
        ensure(
            count == expected && row["source_rows"] == expected,
            "source-component count differs",
        )?;
        observations[group] = observations[group].min(count);
        estimates[group] = estimates[group].max(number(row, "difference")?);
        uppers[group] = uppers[group].max(number(row, "upper_bound")?);
    }
    for row in costs {
        ensure(
            TASKS.contains(&string(row, "task")?)
                && HEADS.contains(&string(row, "head")?)
                && row["candidate"] == candidate
                && row["baseline"] == baselines[0]
                && number(row, "threshold")? == 3.0
                && seen_cost.insert(key(row, &["task", "head"])),
            "cost comparison identity differs",
        )?;
        if row["status"] != "completed" {
            available[2] = false;
            continue;
        }
        let ratios = array(row, "paired_seed_cpu_ratios")?;
        ensure(
            ratios.len() == 3
                && ratios
                    .iter()
                    .all(|v| v.as_f64().is_some_and(|n| n.is_finite() && n > 0.0)),
            "paired CPU census differs",
        )?;
        hepta_handoff_recovery_v7::census::verify_ratio(report, row)?;
        let ratio = number(row, "cpu_ratio")?;
        ensure(ratio > 0.0, "positive total measured CPU ratio required")?;
        estimates[2] = estimates[2].max(ratio);
        uppers[2] = uppers[2].max(ratio);
    }
    let thresholds = [-0.001, 0.0, 3.0];
    let minima = [512, 512, 3];
    let floors = [-710.0, -710.0, 0.0];
    let mut gates = Vec::new();
    let mut measurements = Vec::new();
    let mut aggregate = Vec::new();
    let mut passed = true;
    for (index, name) in ["task", "retention", "total_cost"].into_iter().enumerate() {
        let adapter = &gate["comparisons"][name];
        let canonical = string(adapter, "definition_json")?;
        let comparison = hash(adapter, "comparison_sha256")?;
        let definition = json!({"group":name,"protocol_sha256":protocol_digest.to_string(),
            "frozen_evaluation":e,"aggregation":"maximum over every registered constituent; no missing values",
            "operator":if index==0 {"strict_less"} else {"less_equal"},"threshold":thresholds[index],
            "observation_unit":if index==2 {"paired timed seed runs per fixed ratio"}
                else {"minimum distinct source components among constituent contrasts"}});
        ensure(
            serde_json::from_str::<Value>(canonical)? == definition
                && Digest32::of_bytes(canonical.as_bytes()) == comparison
                && hash(adapter, "evidence_sha256")? == report_digest,
            "comparison evidence or policy differs",
        )?;
        gates.push(ScientificComparisonPolicyV1 {
            comparison_digest: comparison,
            maximum_upper_bound: thresholds[index],
            minimum_observations: minima[index],
        });
        available[index] &= observations[index] >= minima[index]
            && estimates[index].is_finite()
            && uppers[index].is_finite()
            && floors[index] <= estimates[index]
            && estimates[index] <= uppers[index];
        let met = available[index]
            && if index == 0 {
                uppers[index] < thresholds[index]
            } else {
                uppers[index] <= thresholds[index]
            };
        passed &= met;
        let supplied = &adapter["measurement"];
        if available[index] {
            ensure(
                supplied["status"] == "measured"
                    && supplied["observations"] == observations[index]
                    && number(supplied, "lower_bound")? == floors[index]
                    && number(supplied, "estimate")? == estimates[index]
                    && number(supplied, "upper_bound")? == uppers[index],
                "adapter aggregate differs",
            )?;
            measurements.push(ScientificMeasurementStatusV1::Measured(
                ScientificMeasurementV1 {
                    comparison_digest: comparison,
                    evidence_digest: report_digest,
                    observations: observations[index],
                    lower_bound: floors[index],
                    estimate: estimates[index],
                    upper_bound: uppers[index],
                },
            ));
        } else {
            ensure(
                supplied["status"] == "unavailable",
                "missing measurements must stay unavailable",
            )?;
            measurements.push(ScientificMeasurementStatusV1::Unavailable);
        }
        aggregate.push(
            json!({"gate":name,"available":available[index],"observations":observations[index],
            "lower_bound":floors[index],"estimate":estimates[index],"upper_bound":uppers[index],
            "threshold":thresholds[index],"criterion_met":met,
            "lower_bound_semantics":"support floor, not a bootstrap confidence bound"}),
        );
    }
    ensure(
        report["all_registered_gates_met"] == passed && gate["all_registered_gates_met"] == passed,
        "recomputed scientific disposition differs",
    )?;
    Ok(Scores {
        policy: ScientificCandidatePolicyV1 {
            protocol_digest,
            candidate_definition_digest: hash(gate, "candidate_definition_sha256")?,
            task: gates[0].clone(),
            retention: gates[1].clone(),
            total_cost: gates[2].clone(),
        },
        measurements: measurements
            .try_into()
            .map_err(|_| "three groups required")?,
        aggregate: json!(aggregate),
        passed,
    })
}
