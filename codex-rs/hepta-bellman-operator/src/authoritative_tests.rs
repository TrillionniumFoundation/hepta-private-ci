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
use crate::TabularPayloadPinV2;
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

fn percentile(values: &mut [u128], numerator: usize, denominator: usize) -> u128 {
    values.sort_unstable();
    let rank = values
        .len()
        .checked_mul(numerator)
        .and_then(|value| value.checked_add(denominator - 1))
        .unwrap()
        / denominator;
    values[rank.saturating_sub(1).min(values.len() - 1)]
}

fn summary(mut values: Vec<u128>) -> (u128, u128, u128) {
    let p50 = percentile(&mut values.clone(), 50, 100);
    let p95 = percentile(&mut values.clone(), 95, 100);
    let p99 = percentile(&mut values, 99, 100);
    (p50, p95, p99)
}

fn process_resident_bytes() -> u128 {
    let status = std::fs::read_to_string("/proc/self/status")
        .expect("authoritative Linux qualification must expose /proc/self/status");
    let kibibytes = status
        .lines()
        .find_map(|line| {
            line.strip_prefix("VmRSS:")?
                .split_whitespace()
                .next()?
                .parse::<u128>()
                .ok()
        })
        .expect("VmRSS must be present in /proc/self/status");
    kibibytes
        .checked_mul(1024)
        .expect("resident byte conversion overflow")
}

fn resident_measurement(before: u128, checkpoints: &[u128]) -> (u128, u128) {
    let peak = checkpoints.iter().copied().max().unwrap_or(before);
    (peak, peak.saturating_sub(before))
}

/// Dedicated authoritative CI runs this ignored matrix in release mode. The
/// thresholds are qualification ceilings, not marketing latency claims. The
/// RSS values are process checkpoints around input materialization and fitting;
/// the model-estimated bytes come from the bounded work receipt.
#[test]
#[ignore = "authoritative performance qualification"]
fn authoritative_performance_matrix_v1() {
    for candidate_count in [1_000_usize, 4_000, 8_000, 16_000] {
        let mut durations = Vec::new();
        let mut absolute_resident = Vec::new();
        let mut resident_deltas = Vec::new();
        let mut estimated_bytes = Vec::new();
        for _ in 0..3 {
            let before = process_resident_bytes();
            let design = sensor_design(candidate_count);
            let after_input = process_resident_bytes();
            let started = Instant::now();
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
            durations.push(started.elapsed().as_micros());
            let (absolute, delta) = resident_measurement(before, &[after_input, after_fit]);
            absolute_resident.push(absolute);
            resident_deltas.push(delta);
            estimated_bytes.push(u128::from(receipt.work.estimated_bytes));
        }
        let (p50, p95, p99) = summary(durations);
        let (rss_p50, rss_p95, rss_p99) = summary(absolute_resident);
        let (rss_delta_p50, rss_delta_p95, rss_delta_p99) = summary(resident_deltas);
        let (estimated_p50, estimated_p95, estimated_p99) = summary(estimated_bytes);
        println!(
            "{{\"kind\":\"sensor-core\",\"candidates\":{candidate_count},\"p50Micros\":{p50},\"p95Micros\":{p95},\"p99Micros\":{p99},\"p50ResidentBytes\":{rss_p50},\"p95ResidentBytes\":{rss_p95},\"p99ResidentBytes\":{rss_p99},\"p50ResidentDeltaBytes\":{rss_delta_p50},\"p95ResidentDeltaBytes\":{rss_delta_p95},\"p99ResidentDeltaBytes\":{rss_delta_p99},\"p50EstimatedBytes\":{estimated_p50},\"p95EstimatedBytes\":{estimated_p95},\"p99EstimatedBytes\":{estimated_p99}}}"
        );
        assert!(p99 < Duration::from_secs(120).as_micros());
        assert!(rss_delta_p99 < 512 * MEBIBYTE);
        assert!(estimated_p99 <= u128::from(generous_budget().max_estimated_bytes));
    }

    for sample_count in [100_000_usize, 500_000, 1_000_000] {
        let mut durations = Vec::new();
        let mut absolute_resident = Vec::new();
        let mut resident_deltas = Vec::new();
        let mut estimated_bytes = Vec::new();
        for _ in 0..3 {
            let before = process_resident_bytes();
            let plan = tabular_plan(sample_count);
            let after_input = process_resident_bytes();
            let started = Instant::now();
            let fit = fit_tabular_operator_bounded_v2(plan, generous_budget()).unwrap();
            let after_fit = process_resident_bytes();
            assert_eq!(fit.artifact.cells.len(), 1_000);
            durations.push(started.elapsed().as_micros());
            let (absolute, delta) = resident_measurement(before, &[after_input, after_fit]);
            absolute_resident.push(absolute);
            resident_deltas.push(delta);
            estimated_bytes.push(u128::from(fit.work.estimated_bytes));
        }
        let (p50, p95, p99) = summary(durations);
        let (rss_p50, rss_p95, rss_p99) = summary(absolute_resident);
        let (rss_delta_p50, rss_delta_p95, rss_delta_p99) = summary(resident_deltas);
        let (estimated_p50, estimated_p95, estimated_p99) = summary(estimated_bytes);
        println!(
            "{{\"kind\":\"tabular-fit\",\"samples\":{sample_count},\"p50Micros\":{p50},\"p95Micros\":{p95},\"p99Micros\":{p99},\"p50ResidentBytes\":{rss_p50},\"p95ResidentBytes\":{rss_p95},\"p99ResidentBytes\":{rss_p99},\"p50ResidentDeltaBytes\":{rss_delta_p50},\"p95ResidentDeltaBytes\":{rss_delta_p95},\"p99ResidentDeltaBytes\":{rss_delta_p99},\"p50EstimatedBytes\":{estimated_p50},\"p95EstimatedBytes\":{estimated_p95},\"p99EstimatedBytes\":{estimated_p99}}}"
        );
        let ceiling = match sample_count {
            100_000 => Duration::from_secs(90),
            500_000 => Duration::from_secs(240),
            _ => Duration::from_secs(480),
        };
        assert!(p99 < ceiling.as_micros());
        assert!(rss_delta_p99 < 3 * 1024 * MEBIBYTE);
        assert!(estimated_p99 <= u128::from(generous_budget().max_estimated_bytes));
    }
}
