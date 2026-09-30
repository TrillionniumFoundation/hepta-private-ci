use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::LoadedTabularOperatorV2;
use crate::OperatorResourceBudgetV1;
use crate::OperatorWorkErrorV1;
use crate::SensorCoreDesignV1;
use crate::SensorCoreExecutionProfileV2;
use crate::SensorPointV1;
use crate::TABULAR_ARTIFACT_SCHEMA_V1;
use crate::TABULAR_PAYLOAD_SCHEMA_V1;
use crate::TabularOperatorPlanV1;
use crate::TabularOperatorSampleV1;
use crate::TrainingProfileV1;
use crate::WorkControlV1;
use crate::build_sensor_core_v2;
use crate::encode_tabular_payload_v1;
use crate::tabular_v2::BudgetedTabularFitErrorV2;
use crate::tabular_v2::fit_tabular_operator_bounded_v2;
use crate::with_work_control_v1;

const MEBIBYTE: u128 = 1024 * 1024;

fn id(value: impl Into<String>) -> StableId {
    StableId::new(value.into()).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation() -> Generation {
    Generation::new(1).unwrap()
}

fn generous_budget() -> OperatorResourceBudgetV1 {
    OperatorResourceBudgetV1 {
        max_operations: 500_000_000,
        max_estimated_bytes: 2 * 1024 * 1024 * 1024,
        max_elapsed_micros: 600_000_000,
    }
}

fn one_cell_plan() -> TabularOperatorPlanV1 {
    TabularOperatorPlanV1 {
        artifact_id: id("artifact"),
        producer_id: id("producer"),
        generation: generation(),
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        sensor_core_digest: digest("sensor-core"),
        training_profile_digest: digest("training-profile"),
        minimum_samples_per_cell: 1,
        sensor_ids: vec![id("sensor-0")],
        action_ids: vec![id("action-0")],
        samples: vec![TabularOperatorSampleV1 {
            sample_id: id("sample-0"),
            sensor_id: id("sensor-0"),
            action_id: id("action-0"),
            target: FixedQ32::from_raw(7),
            evidence_digest: digest("evidence-0"),
        }],
    }
}

#[test]
fn mutation_profile_digest_covers_runtime_and_error_budget() {
    let left = TrainingProfileV1::new(
        digest("objective"),
        digest("sensor"),
        7,
        4,
        FixedQ32::from_raw(10),
        OperatorResourceBudgetV1::qualification_default(),
    )
    .unwrap();
    let right = TrainingProfileV1::new(
        digest("objective"),
        digest("sensor"),
        7,
        4,
        FixedQ32::from_raw(11),
        OperatorResourceBudgetV1::qualification_default(),
    )
    .unwrap();
    let runtime_changed = TrainingProfileV1::new(
        digest("objective"),
        digest("sensor"),
        7,
        4,
        FixedQ32::from_raw(10),
        OperatorResourceBudgetV1 {
            max_operations: 49_999_999,
            ..OperatorResourceBudgetV1::qualification_default()
        },
    )
    .unwrap();
    assert_ne!(left.digest(), right.digest());
    assert_ne!(left.digest(), runtime_changed.digest());
    assert_ne!(
        left.runtime_profile_digest(),
        runtime_changed.runtime_profile_digest()
    );
}

#[test]
fn mutation_cancelled_work_is_rejected_before_fit() {
    let control = WorkControlV1::new();
    control.cancel();
    let result = with_work_control_v1(&control, || {
        fit_tabular_operator_bounded_v2(one_cell_plan(), generous_budget())
    });
    assert!(matches!(
        result,
        Err(BudgetedTabularFitErrorV2::Work(
            OperatorWorkErrorV1::Cancelled
        ))
    ));
}

#[test]
fn mutation_persisted_payload_cannot_reuse_the_selected_pin() {
    let fit = fit_tabular_operator_bounded_v2(one_cell_plan(), generous_budget()).unwrap();
    let mut bytes = encode_tabular_payload_v1(&fit.artifact).unwrap();
    let pin = TabularPayloadPinV2 {
        artifact_id: fit.artifact.artifact_id.clone(),
        producer_id: fit.artifact.producer_id.clone(),
        artifact_schema_version: TABULAR_ARTIFACT_SCHEMA_V1,
        payload_schema_version: TABULAR_PAYLOAD_SCHEMA_V1,
        payload_digest: Digest32::of_bytes(&bytes),
        artifact_digest: fit.artifact.artifact_digest,
        objective_digest: fit.artifact.objective_digest,
        dataset_digest: fit.artifact.dataset_digest,
        sensor_core_digest: fit.artifact.sensor_core_digest,
        training_profile_digest: fit.artifact.training_profile_digest,
        runtime_profile_digest: digest("runtime"),
        trust_digest: digest("trust"),
        registry_head_digest: digest("registry"),
        authority_epoch: 1,
        generation: fit.artifact.generation,
    };
    let last = bytes.len() - 1;
    bytes[last] ^= 1;
    assert!(LoadedTabularOperatorV2::from_pinned_payload_v2(&bytes, &pin).is_err());
}

fn sensor_design(candidate_count: usize) -> SensorCoreDesignV1 {
    let denominator = i64::try_from(candidate_count - 1).unwrap();
    SensorCoreDesignV1 {
        sensor_core_id: id("benchmark-core"),
        state_axis_digest: digest("benchmark-axis"),
        candidate_design_digest: digest(&format!("design-{candidate_count}")),
        seed_digest: digest("benchmark-seed"),
        requested_count: 64,
        candidates: (0..candidate_count)
            .map(|index| SensorPointV1 {
                point_id: id(format!("point-{index:05}")),
                coordinates: vec![FixedQ32::from_raw(
                    i64::try_from(index).unwrap() * FixedQ32::ONE.raw() / denominator,
                )],
            })
            .collect(),
    }
}

fn tabular_plan(sample_count: usize) -> TabularOperatorPlanV1 {
    const SENSORS: usize = 100;
    const ACTIONS: usize = 10;
    const CELLS: usize = SENSORS * ACTIONS;
    assert_eq!(sample_count % CELLS, 0);
    let sensor_ids = (0..SENSORS)
        .map(|index| id(format!("sensor-{index:03}")))
        .collect::<Vec<_>>();
    let action_ids = (0..ACTIONS)
        .map(|index| id(format!("action-{index:02}")))
        .collect::<Vec<_>>();
    let samples = (0..sample_count)
        .map(|index| {
            let cell = index % CELLS;
            let sensor = cell / ACTIONS;
            let action = cell % ACTIONS;
            TabularOperatorSampleV1 {
                sample_id: id(format!("sample-{index:07}")),
                sensor_id: sensor_ids[sensor].clone(),
                action_id: action_ids[action].clone(),
                target: FixedQ32::from_raw(i64::try_from(index % 17).unwrap() - 8),
                evidence_digest: Digest32::of_bytes(&index.to_be_bytes()),
            }
        })
        .collect();
    TabularOperatorPlanV1 {
        artifact_id: id(format!("artifact-{sample_count}")),
        producer_id: id("benchmark-producer"),
        generation: generation(),
        objective_digest: digest("benchmark-objective"),
        dataset_digest: digest(&format!("dataset-{sample_count}")),
        sensor_core_digest: digest("benchmark-sensor-core"),
        training_profile_digest: digest(&format!("profile-{sample_count}")),
        minimum_samples_per_cell: sample_count / CELLS,
        sensor_ids,
        action_ids,
        samples,
    }
}

fn percentile_sorted(values: &[u128], numerator: usize, denominator: usize) -> u128 {
    let rank = values
        .len()
        .checked_mul(numerator)
        .and_then(|value| value.checked_add(denominator - 1))
        .unwrap()
        / denominator;
    values[rank.saturating_sub(1).min(values.len() - 1)]
}

#[derive(Clone, Copy, Debug)]
struct MeasurementSummary {
    median: u128,
    p90: u128,
    maximum: u128,
    median_absolute_deviation: u128,
}

fn summary(mut values: Vec<u128>) -> MeasurementSummary {
    assert!(!values.is_empty());
    values.sort_unstable();
    let median = percentile_sorted(&values, 50, 100);
    let p90 = percentile_sorted(&values, 90, 100);
    let maximum = *values.last().unwrap();
    let mut deviations = values
        .iter()
        .map(|value| value.abs_diff(median))
        .collect::<Vec<_>>();
    deviations.sort_unstable();
    MeasurementSummary {
        median,
        p90,
        maximum,
        median_absolute_deviation: percentile_sorted(&deviations, 50, 100),
    }
}

#[derive(Clone, Copy, Debug)]
struct PerformanceRunProfile {
    name: &'static str,
    warmups: usize,
    observations: usize,
    target_host_candidate: bool,
}

impl PerformanceRunProfile {
    const fn regression() -> Self {
        Self {
            name: "github-regression-v2",
            warmups: 2,
            observations: 7,
            target_host_candidate: false,
        }
    }

    const fn target_host() -> Self {
        Self {
            name: "target-host-candidate-v1",
            warmups: 5,
            observations: 25,
            target_host_candidate: true,
        }
    }
}

fn performance_profile() -> PerformanceRunProfile {
    if std::env::var_os("HEPTA_TARGET_HOST_CAPACITY").as_deref() == Some("1".as_ref()) {
        PerformanceRunProfile::target_host()
    } else {
        PerformanceRunProfile::regression()
    }
}

#[test]
fn target_host_profile_has_statistically_meaningful_minimum_sample() {
    let profile = PerformanceRunProfile::target_host();
    assert!(profile.warmups >= 5);
    assert!(profile.observations >= 20);
}

fn proc_status_value(label: &str) -> u128 {
    let status = std::fs::read_to_string("/proc/self/status")
        .expect("authoritative Linux qualification must expose /proc/self/status");
    let kibibytes = status
        .lines()
        .find_map(|line| {
            line.strip_prefix(label)?
                .split_whitespace()
                .next()?
                .parse::<u128>()
                .ok()
        })
        .unwrap_or(0);
    kibibytes
        .checked_mul(1024)
        .expect("resident byte conversion overflow")
}

fn process_resident_bytes() -> u128 {
    proc_status_value("VmRSS:")
}

fn process_peak_resident_bytes() -> u128 {
    proc_status_value("VmHWM:")
}

fn cgroup_peak_bytes() -> Option<u128> {
    for path in [
        Path::new("/sys/fs/cgroup/memory.peak"),
        Path::new("/sys/fs/cgroup/memory/memory.max_usage_in_bytes"),
    ] {
        let Ok(value) = std::fs::read_to_string(path) else {
            continue;
        };
        if let Ok(parsed) = value.trim().parse::<u128>() {
            return Some(parsed);
        }
    }
    None
}

fn cpu_governor() -> String {
    std::fs::read_to_string("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
        .map(|value| value.trim().to_owned())
        .unwrap_or_else(|_| "unavailable".to_owned())
}

#[derive(Clone, Copy, Debug)]
struct PerformanceObservation {
    elapsed_micros: u128,
    resident_bytes: u128,
    resident_delta_bytes: u128,
    process_peak_resident_bytes: u128,
    cgroup_peak_bytes: Option<u128>,
    estimated_bytes: u128,
}

fn observe_sensor(candidate_count: usize) -> PerformanceObservation {
    let before = process_resident_bytes();
    let started = Instant::now();
    let design = sensor_design(candidate_count);
    let after_input = process_resident_bytes();
    let receipt = build_sensor_core_v2(
        design,
        SensorCoreExecutionProfileV2 {
            budget: generous_budget(),
            exact_candidate_limit: 4_096,
            maximum_working_candidates: 4_096,
        },
    )
    .unwrap();
    let after_fit = process_resident_bytes();
    assert_eq!(
        usize::try_from(receipt.input_candidate_count).unwrap(),
        candidate_count
    );
    let resident = after_input.max(after_fit);
    PerformanceObservation {
        elapsed_micros: started.elapsed().as_micros(),
        resident_bytes: resident,
        resident_delta_bytes: resident.saturating_sub(before),
        process_peak_resident_bytes: process_peak_resident_bytes(),
        cgroup_peak_bytes: cgroup_peak_bytes(),
        estimated_bytes: u128::from(receipt.work.estimated_bytes),
    }
}

fn observe_tabular(sample_count: usize) -> PerformanceObservation {
    let before = process_resident_bytes();
    let started = Instant::now();
    let plan = tabular_plan(sample_count);
    let after_input = process_resident_bytes();
    let fit = fit_tabular_operator_bounded_v2(plan, generous_budget()).unwrap();
    let after_fit = process_resident_bytes();
    assert_eq!(fit.artifact.cells.len(), 1_000);
    let resident = after_input.max(after_fit);
    PerformanceObservation {
        elapsed_micros: started.elapsed().as_micros(),
        resident_bytes: resident,
        resident_delta_bytes: resident.saturating_sub(before),
        process_peak_resident_bytes: process_peak_resident_bytes(),
        cgroup_peak_bytes: cgroup_peak_bytes(),
        estimated_bytes: u128::from(fit.work.estimated_bytes),
    }
}

fn emit_performance_summary(
    kind: &str,
    size_name: &str,
    size: usize,
    profile: PerformanceRunProfile,
    cold_micros: u128,
    observations: &[PerformanceObservation],
) -> (
    MeasurementSummary,
    MeasurementSummary,
    MeasurementSummary,
    MeasurementSummary,
) {
    let elapsed = summary(
        observations
            .iter()
            .map(|value| value.elapsed_micros)
            .collect(),
    );
    let resident = summary(
        observations
            .iter()
            .map(|value| value.resident_bytes)
            .collect(),
    );
    let resident_delta = summary(
        observations
            .iter()
            .map(|value| value.resident_delta_bytes)
            .collect(),
    );
    let estimated = summary(
        observations
            .iter()
            .map(|value| value.estimated_bytes)
            .collect(),
    );
    let process_peak = observations
        .iter()
        .map(|value| value.process_peak_resident_bytes)
        .max()
        .unwrap_or(0);
    let cgroup_peak = observations
        .iter()
        .filter_map(|value| value.cgroup_peak_bytes)
        .max()
        .map_or_else(|| "null".to_owned(), |value| value.to_string());
    println!(
        "{{\"schema\":\"hepta.learning-operator-performance.v2\",\"kind\":\"{kind}\",\"{size_name}\":{size},\"profile\":\"{}\",\"warmups\":{},\"observations\":{},\"targetHostCandidate\":{},\"shippingCapacityClaim\":false,\"hostOs\":\"{}\",\"hostArch\":\"{}\",\"cpuGovernor\":\"{}\",\"coldMicros\":{cold_micros},\"medianMicros\":{},\"p90Micros\":{},\"maxMicros\":{},\"madMicros\":{},\"medianResidentBytes\":{},\"maxResidentBytes\":{},\"medianResidentDeltaBytes\":{},\"maxResidentDeltaBytes\":{},\"processPeakResidentBytes\":{process_peak},\"cgroupPeakBytes\":{cgroup_peak},\"medianEstimatedBytes\":{},\"maxEstimatedBytes\":{}}}",
        profile.name,
        profile.warmups,
        profile.observations,
        profile.target_host_candidate,
        std::env::consts::OS,
        std::env::consts::ARCH,
        cpu_governor(),
        elapsed.median,
        elapsed.p90,
        elapsed.maximum,
        elapsed.median_absolute_deviation,
        resident.median,
        resident.maximum,
        resident_delta.median,
        resident_delta.maximum,
        estimated.median,
        estimated.maximum,
    );
    (elapsed, resident, resident_delta, estimated)
}

/// Dedicated authoritative CI runs this ignored matrix in release mode.
///
/// The default GitHub-hosted profile is regression evidence only: it performs
/// warm-up, measures seven full materialize-and-fit operations and reports
/// median/p90/max/MAD rather than pretending three samples establish p95/p99.
/// Setting `HEPTA_TARGET_HOST_CAPACITY=1` requires five warm-ups and twenty-five
/// observations, but still emits `shippingCapacityClaim=false`; independent
/// target-host acceptance is a separate external gate.
#[test]
#[ignore = "authoritative performance qualification"]
fn authoritative_performance_matrix_v1() {
    let profile = performance_profile();
    for candidate_count in [1_000_usize, 4_000, 8_000, 16_000] {
        let cold = observe_sensor(candidate_count).elapsed_micros;
        for _ in 0..profile.warmups {
            let _ = observe_sensor(candidate_count);
        }
        let observations = (0..profile.observations)
            .map(|_| observe_sensor(candidate_count))
            .collect::<Vec<_>>();
        let (elapsed, _, resident_delta, estimated) = emit_performance_summary(
            "sensor-core",
            "candidates",
            candidate_count,
            profile,
            cold,
            &observations,
        );
        assert!(elapsed.maximum < Duration::from_secs(120).as_micros());
        assert!(resident_delta.maximum < 512 * MEBIBYTE);
        assert!(estimated.maximum <= u128::from(generous_budget().max_estimated_bytes));
    }

    for sample_count in [100_000_usize, 500_000, 1_000_000] {
        let cold = observe_tabular(sample_count).elapsed_micros;
        for _ in 0..profile.warmups {
            let _ = observe_tabular(sample_count);
        }
        let observations = (0..profile.observations)
            .map(|_| observe_tabular(sample_count))
            .collect::<Vec<_>>();
        let (elapsed, _, resident_delta, estimated) = emit_performance_summary(
            "tabular-fit",
            "samples",
            sample_count,
            profile,
            cold,
            &observations,
        );
        let ceiling = match sample_count {
            100_000 => Duration::from_secs(90),
            500_000 => Duration::from_secs(240),
            _ => Duration::from_secs(480),
        };
        assert!(elapsed.maximum < ceiling.as_micros());
        assert!(resident_delta.maximum < 3 * 1024 * MEBIBYTE);
        assert!(estimated.maximum <= u128::from(generous_budget().max_estimated_bytes));
    }
}
