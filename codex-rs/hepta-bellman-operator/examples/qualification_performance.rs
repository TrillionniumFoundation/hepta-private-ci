use std::fmt::Write as _;
use std::fs;
use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_bellman_operator::SensorCoreDesignV1;
use codex_hepta_bellman_operator::SensorPointV1;
use codex_hepta_bellman_operator::TabularOperatorPlanV1;
use codex_hepta_bellman_operator::TabularOperatorSampleV1;
use codex_hepta_bellman_operator::WorkControlV1;
use codex_hepta_bellman_operator::build_sensor_core_controlled_v2;
use codex_hepta_bellman_operator::fit_tabular_operator_strict_controlled_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const SENSOR_CASES: &[(usize, usize)] = &[
    (1_024, 64),
    (4_096, 128),
    (8_192, 192),
    (16_384, 256),
];
const TABULAR_CASES: &[(usize, usize)] = &[(100_000, 5), (500_000, 3), (1_000_000, 2)];
const MAX_RSS_KIB: u64 = 6 * 1024 * 1024;

fn id(value: impl AsRef<str>) -> StableId {
    StableId::new(value.as_ref()).expect("qualification identity")
}

fn digest(label: impl AsRef<[u8]>) -> Digest32 {
    Digest32::of_bytes(label.as_ref())
}

fn coordinate(index: usize, count: usize) -> FixedQ32 {
    let numerator = i128::try_from(index + 1).expect("index");
    let denominator = i128::try_from(count + 1).expect("count");
    let raw = numerator * i128::from(FixedQ32::ONE.raw()) / denominator;
    FixedQ32::from_raw(i64::try_from(raw).expect("coordinate"))
}

fn sensor_design(candidate_count: usize, requested_count: usize) -> SensorCoreDesignV1 {
    let candidates = (0..candidate_count)
        .map(|index| SensorPointV1 {
            point_id: id(format!("sensor-candidate-{index:05}")),
            coordinates: vec![
                coordinate(index, candidate_count),
                coordinate((index * 7_919) % candidate_count, candidate_count),
            ],
        })
        .collect();
    SensorCoreDesignV1 {
        sensor_core_id: id(format!("qualification-core-{candidate_count}")),
        state_axis_digest: digest(b"qualification-state-axis"),
        candidate_design_digest: digest(candidate_count.to_be_bytes()),
        seed_digest: digest(b"qualification-deterministic-seed"),
        requested_count,
        candidates,
    }
}

fn run_sensor(candidate_count: usize, requested_count: usize) -> Duration {
    let design = sensor_design(candidate_count, requested_count);
    let candidates = u64::try_from(candidate_count).expect("candidate count");
    let requested = u64::try_from(requested_count).expect("requested count");
    // Validation + initial distances + winner and update scans for each selected
    // point + the selected-point separation matrix, with explicit headroom.
    let max_operations = candidates
        .saturating_mul(requested.saturating_mul(3).saturating_add(16))
        .saturating_add(requested.saturating_mul(requested));
    let (control, _) = WorkControlV1::new(120_000, max_operations.max(10_000)).unwrap();
    let started = Instant::now();
    let manifest = build_sensor_core_controlled_v2(design, &control)
        .expect("sensor-core qualification");
    assert_eq!(manifest.selected_points.len(), requested_count);
    started.elapsed()
}

fn run_tabular(sample_count: usize, iteration: usize) -> Duration {
    let started = Instant::now();
    let sensor = id("qualification-sensor");
    let action = id("qualification-action");
    let iteration_u64 = u64::try_from(iteration).expect("iteration");
    let sample_count_u64 = u64::try_from(sample_count).expect("sample count");
    let samples = (0..sample_count)
        .map(|index| {
            let index_u64 = u64::try_from(index).expect("sample index");
            let mut evidence = [0_u8; 24];
            evidence[..8].copy_from_slice(&iteration_u64.to_be_bytes());
            evidence[8..16].copy_from_slice(&index_u64.to_be_bytes());
            evidence[16..].copy_from_slice(&sample_count_u64.to_be_bytes());
            TabularOperatorSampleV1 {
                sample_id: id(format!("qualification-sample-{iteration:02}-{index:07}")),
                sensor_id: sensor.clone(),
                action_id: action.clone(),
                target: FixedQ32::from_raw(i64::try_from(index % 17).expect("target")),
                evidence_digest: digest(evidence),
            }
        })
        .collect();
    let dataset_label = format!("qualification-dataset-{sample_count}-{iteration}");
    let plan = TabularOperatorPlanV1 {
        artifact_id: id(format!("qualification-artifact-{sample_count}-{iteration}")),
        producer_id: id("qualification-owner"),
        generation: Generation::new(1).expect("generation"),
        objective_digest: digest(b"qualification-objective"),
        dataset_digest: digest(dataset_label.as_bytes()),
        sensor_core_digest: digest(b"qualification-sensor-core"),
        training_profile_digest: digest(b"qualification-training-profile"),
        minimum_samples_per_cell: 1,
        sensor_ids: vec![sensor],
        action_ids: vec![action],
        samples,
    };
    let max_operations = sample_count_u64.saturating_add(4_096);
    let (control, _) = WorkControlV1::new(300_000, max_operations).unwrap();
    let artifact = fit_tabular_operator_strict_controlled_v3(plan, &control)
        .expect("tabular qualification");
    assert_eq!(artifact.cells.len(), 1);
    assert_eq!(
        usize::try_from(artifact.cells[0].sample_count).expect("cell count"),
        sample_count
    );
    started.elapsed()
}

fn percentile(values: &[Duration], percent: usize) -> u128 {
    let mut millis = values.iter().map(Duration::as_millis).collect::<Vec<_>>();
    millis.sort_unstable();
    let index = ((millis.len() - 1) * percent).div_ceil(100);
    millis[index]
}

fn peak_rss_kib() -> u64 {
    let Ok(status) = fs::read_to_string("/proc/self/status") else {
        return 0;
    };
    status
        .lines()
        .find_map(|line| {
            let value = line.strip_prefix("VmHWM:")?.trim();
            value.split_whitespace().next()?.parse().ok()
        })
        .unwrap_or(0)
}

fn duration_row(label: &str, size_name: &str, size: usize, values: &[Duration]) -> String {
    format!(
        "{{\"case\":\"{label}\",\"{size_name}\":{size},\"iterations\":{},\"p50Millis\":{},\"p95Millis\":{},\"p99Millis\":{}}}",
        values.len(),
        percentile(values, 50),
        percentile(values, 95),
        percentile(values, 99),
    )
}

fn main() -> ExitCode {
    let output = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("learning-operator-performance.json"));
    let mut rows = Vec::new();
    let mut passed = true;

    for &(candidate_count, requested_count) in SENSOR_CASES {
        let values = (0..3)
            .map(|_| run_sensor(candidate_count, requested_count))
            .collect::<Vec<_>>();
        let p99 = percentile(&values, 99);
        passed &= p99 <= 120_000;
        rows.push(format!(
            "{{\"case\":\"sensor-core\",\"candidateCount\":{candidate_count},\"selectedCount\":{requested_count},\"iterations\":{},\"p50Millis\":{},\"p95Millis\":{},\"p99Millis\":{},\"p99LimitMillis\":120000}}",
            values.len(),
            percentile(&values, 50),
            percentile(&values, 95),
            p99,
        ));
    }

    for &(sample_count, iterations) in TABULAR_CASES {
        let values = (0..iterations)
            .map(|iteration| run_tabular(sample_count, iteration))
            .collect::<Vec<_>>();
        let p99 = percentile(&values, 99);
        let limit = match sample_count {
            100_000 => 60_000,
            500_000 => 180_000,
            _ => 300_000,
        };
        passed &= p99 <= limit;
        let mut row = duration_row("tabular-fit-end-to-end", "sampleCount", sample_count, &values);
        row.pop();
        write!(&mut row, ",\"p99LimitMillis\":{limit}}}").expect("JSON row");
        rows.push(row);
    }

    let rss = peak_rss_kib();
    if rss != 0 {
        passed &= rss <= MAX_RSS_KIB;
    }
    let document = format!(
        "{{\n  \"schema\": \"hepta.learning-operator.performance.v1\",\n  \"measurementScope\": \"complete operation including input materialization\",\n  \"thresholdClass\": \"qualification runaway guard, not production SLO\",\n  \"peakRssKiB\": {rss},\n  \"peakRssLimitKiB\": {MAX_RSS_KIB},\n  \"cases\": [\n    {}\n  ],\n  \"passed\": {passed}\n}}\n",
        rows.join(",\n    ")
    );
    if let Some(parent) = output.parent() {
        if let Err(error) = fs::create_dir_all(parent) {
            eprintln!("cannot create performance output directory: {error}");
            return ExitCode::FAILURE;
        }
    }
    if let Err(error) = fs::write(&output, document.as_bytes()) {
        eprintln!("cannot write performance output: {error}");
        return ExitCode::FAILURE;
    }
    println!("{document}");
    if passed {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}
