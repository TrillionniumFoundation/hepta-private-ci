use std::collections::BTreeSet;
use std::fs;
use std::path::Path;

use codex_hepta_learning_artifacts::ScientificCandidatePolicyV1;
use codex_hepta_learning_artifacts::ScientificComparisonPolicyV1;
use codex_hepta_learning_artifacts::ScientificMeasurementStatusV1;
use codex_hepta_learning_artifacts::ScientificMeasurementV1;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

use crate::Result;
use crate::ensure;

const PROFILES: &[(&str, &str)] = &[
    (
        "654994abfb66e8872b0d6632b7d80d5058ad5af06adc2d2dea0de628395ba05e",
        "hepta.cell-field-fresh-evaluation.v5",
    ),
    (
        "cdd777f64265acfd6b8e44960a4f3c3bfbd5d856f76bc7c9d9c696bf4e11f41f",
        "hepta.cell-field-fresh-evaluation.v6",
    ),
];

pub fn accepted_profile(digest: Digest32) -> Result<&'static str> {
    let encoded = digest.to_string();
    PROFILES
        .iter()
        .find(|(value, _)| *value == encoded)
        .map(|(_, schema)| *schema)
        .ok_or_else(|| "frozen protocol changed or unreviewed profile".into())
}
pub const TASKS: [&str; 2] = ["agnews", "dbpedia"];
pub const HEADS: [&str; 2] = ["linear", "gated"];
pub const SEEDS: [u64; 3] = [7, 17, 29];

pub struct Inputs {
    pub policy: ScientificCandidatePolicyV1,
    pub measurements: [ScientificMeasurementStatusV1; 3],
    pub aggregate: Value,
    pub report_digest: Digest32,
    pub gate_digest: Digest32,
    pub candidate: Vec<u8>,
    pub predecessor: Vec<u8>,
    pub code_digest: Digest32,
    pub runtime_digest: Digest32,
    pub dataset_digest: Digest32,
    pub all_numeric_gates_pass: bool,
}

pub fn read(path: &Path) -> Result<Vec<u8>> {
    let metadata = fs::symlink_metadata(path)?;
    ensure(
        metadata.is_file()
            && !metadata.file_type().is_symlink()
            && metadata.len() <= 64 * 1024 * 1024,
        "bounded regular input required",
    )?;
    Ok(fs::read(path)?)
}

pub fn string<'a>(value: &'a Value, field: &str) -> Result<&'a str> {
    value[field]
        .as_str()
        .ok_or_else(|| format!("missing text field: {field}").into())
}

pub fn hash(value: &Value, field: &str) -> Result<Digest32> {
    let digest: Digest32 = string(value, field)?.parse()?;
    ensure(!digest.is_zero(), "zero input digest")?;
    Ok(digest)
}

pub fn number(value: &Value, field: &str) -> Result<f64> {
    let number = value[field]
        .as_f64()
        .ok_or_else(|| format!("missing number: {field}"))?;
    ensure(number.is_finite(), "nonfinite measurement")?;
    Ok(number)
}

pub fn array<'a>(value: &'a Value, field: &str) -> Result<&'a Vec<Value>> {
    value[field]
        .as_array()
        .ok_or_else(|| format!("missing array: {field}").into())
}

pub fn key(row: &Value, fields: &[&str]) -> String {
    fields
        .iter()
        .map(|field| row[*field].to_string())
        .collect::<Vec<_>>()
        .join("/")
}

pub fn load(
    protocol: &Path,
    evaluation: &Path,
    gate: &Path,
    predecessor: &Path,
    candidate: &Path,
    conversion: &Path,
) -> Result<Inputs> {
    let protocol_bytes = read(protocol)?;
    let report_bytes = read(evaluation)?;
    let gate_bytes = read(gate)?;
    let predecessor = read(predecessor)?;
    let candidate = read(candidate)?;
    let protocol: Value = serde_json::from_slice(&protocol_bytes)?;
    let report: Value = serde_json::from_slice(&report_bytes)?;
    let gate: Value = serde_json::from_slice(&gate_bytes)?;
    let protocol_digest = Digest32::of_bytes(&protocol_bytes);
    let report_digest = Digest32::of_bytes(&report_bytes);
    let protocol_hash = protocol_digest.to_string();
    let schema = accepted_profile(protocol_digest)?;
    let candidate_name = string(&protocol["evaluation"], "candidate")?;
    let baselines = array(&protocol["evaluation"], "primary_future_baselines")?;
    ensure(
        baselines.len() == 2,
        "two frozen primary baselines required",
    )?;
    ensure(
        hash(&report, "protocol_sha256")? == protocol_digest
            && hash(&gate, "protocol_sha256")? == protocol_digest,
        "protocol binding mismatch",
    )?;
    ensure(
        hash(&gate, "report_sha256")? == report_digest,
        "report binding mismatch",
    )?;
    ensure(
        hash(&gate, "candidate_sha256")? == Digest32::of_bytes(&candidate)
            && hash(&gate, "predecessor_sha256")? == Digest32::of_bytes(&predecessor),
        "parameter bundle binding mismatch",
    )?;
    ensure(
        string(&gate, "candidate_format")? == "hepta.trained-cell-bundle.v5",
        "research bundle format mismatch",
    )?;
    ensure(
        string(&report, "schema")? == schema && string(&report, "candidate")? == candidate_name,
        "evaluation identity mismatch",
    )?;
    let candidate_definition = json!({"mpc":protocol["mpc"],"models":protocol["models"],"evaluation":protocol["evaluation"]});
    let candidate_canonical = string(&gate, "candidate_definition_json")?;
    ensure(
        serde_json::from_str::<Value>(candidate_canonical)? == candidate_definition
            && Digest32::of_bytes(candidate_canonical.as_bytes())
                == hash(&gate, "candidate_definition_sha256")?,
        "candidate definition changed",
    )?;
    let datasets = string(&gate, "source_dataset_definition_json")?;
    ensure(
        Digest32::of_bytes(datasets.as_bytes()) == hash(&gate, "source_dataset_sha256")?,
        "source dataset definition mismatch",
    )?;
    crate::payload::verify(&gate, conversion, &predecessor, &candidate)?;
    let census = crate::census::verify(&report, &gate, &protocol)?;
    let primary = array(&report, "primary_contrasts")?;
    let cost = array(&report, "cost_contrasts")?;
    ensure(
        primary.len() == 12 && cost.len() == 4,
        "contrast census size mismatch",
    )?;
    let mut seen_primary = BTreeSet::new();
    let mut seen_cost = BTreeSet::new();
    let mut observations = [u64::MAX, u64::MAX, 3];
    let mut estimates = [f64::NEG_INFINITY; 3];
    let mut uppers = [f64::NEG_INFINITY; 3];
    let mut available = [census; 3];
    for row in primary {
        let task = string(row, "task")?;
        let head = string(row, "head")?;
        let split = string(row, "split")?;
        let baseline = string(row, "baseline")?;
        ensure(
            TASKS.contains(&task)
                && HEADS.contains(&head)
                && string(row, "candidate")? == candidate_name,
            "primary contrast identity mismatch",
        )?;
        let group = if split == "future"
            && baselines
                .iter()
                .any(|value| value.as_str() == Some(baseline))
        {
            0
        } else if split == "old" && baseline == "warmup_old" {
            1
        } else {
            return Err("unexpected primary contrast".into());
        };
        ensure(
            seen_primary.insert(key(row, &["task", "head", "split", "baseline"])),
            "duplicate primary contrast",
        )?;
        ensure(
            number(row, "threshold")? == [-0.001, 0.0][group],
            "primary threshold changed",
        )?;
        if row["status"] != "completed" {
            available[group] = false;
            continue;
        }
        let count = row["source_components"]
            .as_u64()
            .ok_or("missing source component count")?;
        let expected = protocol["source_counts"][task][if group == 0 {
            "future_test"
        } else {
            "old_test"
        }]
        .as_u64()
        .ok_or("frozen source census missing")?;
        ensure(
            count == expected && row["source_rows"] == expected,
            "independent source census mismatch",
        )?;
        observations[group] = observations[group].min(count);
        estimates[group] = estimates[group].max(number(row, "difference")?);
        uppers[group] = uppers[group].max(number(row, "upper_bound")?);
    }
    for row in cost {
        ensure(
            TASKS.contains(&string(row, "task")?)
                && HEADS.contains(&string(row, "head")?)
                && string(row, "candidate")? == candidate_name
                && row["baseline"] == baselines[0]
                && number(row, "threshold")? == 3.0,
            "cost comparison identity mismatch",
        )?;
        ensure(
            seen_cost.insert(key(row, &["task", "head"])),
            "duplicate cost comparison",
        )?;
        if row["status"] != "completed" {
            available[2] = false;
            continue;
        }
        let pair = array(row, "paired_seed_cpu_ratios")?;
        ensure(
            pair.len() == 3
                && pair
                    .iter()
                    .all(|x| x.as_f64().is_some_and(|v| v.is_finite() && v > 0.0)),
            "paired timing census mismatch",
        )?;
        let ratio = number(row, "cpu_ratio")?;
        crate::census::verify_ratio(&report, row)?;
        ensure(ratio > 0.0, "invalid measured CPU ratio")?;
        estimates[2] = estimates[2].max(ratio);
        uppers[2] = uppers[2].max(ratio);
    }
    let thresholds = [-0.001, 0.0, 3.0];
    let minima = [512, 512, 3];
    let floors = [-710.0, -710.0, 0.0];
    let names = ["task", "retention", "total_cost"];
    let mut gates = Vec::new();
    let mut measurements = Vec::new();
    let mut aggregate = Vec::new();
    let mut all_pass = true;
    for index in 0..3 {
        let name = names[index];
        let adapter = &gate["comparisons"][name];
        let comparison = hash(adapter, "comparison_sha256")?;
        let canonical = string(adapter, "definition_json")?;
        let definition: Value = serde_json::from_str(canonical)?;
        let expected_definition = json!({"group":name,"protocol_sha256":protocol_hash,"frozen_evaluation":protocol["evaluation"],"aggregation":"maximum over every registered constituent; no missing values","operator":if index==0 {"strict_less"} else {"less_equal"},"threshold":thresholds[index],"observation_unit":if index==2 {"paired timed seed runs per fixed ratio"} else {"minimum distinct source components among constituent contrasts"}});
        ensure(
            Digest32::of_bytes(canonical.as_bytes()) == comparison
                && definition == expected_definition,
            "comparison definition binding mismatch",
        )?;
        ensure(
            hash(adapter, "evidence_sha256")? == report_digest,
            "measurement evidence mismatch",
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
        let passed = available[index]
            && if index == 0 {
                uppers[index] < thresholds[index]
            } else {
                uppers[index] <= thresholds[index]
            };
        all_pass &= passed;
        let supplied = &adapter["measurement"];
        if available[index] {
            ensure(
                supplied["status"] == "measured"
                    && supplied["observations"] == observations[index]
                    && number(supplied, "lower_bound")? == floors[index]
                    && number(supplied, "estimate")? == estimates[index]
                    && number(supplied, "upper_bound")? == uppers[index],
                "independent adapter aggregate disagreement",
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
                "unavailable aggregate disagreement",
            )?;
            measurements.push(ScientificMeasurementStatusV1::Unavailable);
        }
        aggregate.push(json!({"gate":name,"available":available[index],"observations":observations[index],"lower_bound":floors[index],"estimate":estimates[index],"upper_bound":uppers[index],"threshold":thresholds[index],"criterion_met":passed,"lower_bound_semantics":if index==2 {"zero support floor; upper is maximum measured CPU ratio, not a CI"} else {"conservative NLL-difference support floor from float64 tiny clipping; not a bootstrap lower CI"}}));
    }
    ensure(
        report["all_registered_gates_met"] == all_pass
            && gate["all_registered_gates_met"] == all_pass,
        "recomputed final gate disposition disagrees",
    )?;
    Ok(Inputs {
        policy: ScientificCandidatePolicyV1 {
            protocol_digest,
            candidate_definition_digest: hash(&gate, "candidate_definition_sha256")?,
            task: gates[0].clone(),
            retention: gates[1].clone(),
            total_cost: gates[2].clone(),
        },
        measurements: measurements
            .try_into()
            .map_err(|_| "three measurements required")?,
        aggregate: json!(aggregate),
        report_digest,
        gate_digest: Digest32::of_bytes(&gate_bytes),
        candidate,
        predecessor,
        code_digest: hash(&gate, "training_code_sha256")?,
        runtime_digest: hash(&gate, "runtime_sha256")?,
        dataset_digest: hash(&gate, "source_dataset_sha256")?,
        all_numeric_gates_pass: all_pass,
    })
}
