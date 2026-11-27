//! Actual file-loaded Q24 computation and kernel CPU/wall observations. The
//! explicit clock fixture exercises expiry; it is not Root authority or B/OPE.

#![cfg(test)]

use super::*;
use crate::CellQ24PrivateHeadV1;
use crate::cell_composed_q24::OriginalQ24BenchmarkMeterV1;
use pretty_assertions::assert_eq;

fn benchmark_request(config: &CellGenerationConfigV2) -> CellGenerationRequestV2 {
    CellGenerationRequestV2 {
        operation_id: "original-b-native-component".into(),
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        predecessor: config.initial.clone(),
        input: input(),
        admitted_at_micros: 10,
        deadline_micros: 100,
    }
}

fn meter(config: &CellGenerationConfigV2) -> anyhow::Result<OriginalQ24BenchmarkMeterV1> {
    Ok(OriginalQ24BenchmarkMeterV1::new(CellTaskCostIdentityV2 {
        task_digest: config.task_digest,
        source_digest: config.manifest.source_digest,
    })?)
}

#[test]
fn original_b_measured_native_outputs_match_the_existing_q24_worker() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let model = Arc::new(load(root.path(), /*factor*/ 1)?);
    let baseline = bundle(&model, /*prior*/ None)?;
    let config = configured(&model, &baseline)?;
    let worker = model.shared_worker(&baseline, config.manifest.clone(), Arc::new(|| 11))?;
    let request = benchmark_request(&config);
    let mut meter = meter(&config)?;
    let actual = worker.execute_original_root_benchmark(&request, &mut meter)?;
    let mut ordinary = worker.execute(&config.manifest, &request, &AtomicBool::new(/*v*/ false))?;
    // The independent observations differ; every non-cost output must match.
    ordinary.cost = actual.cost.clone();
    assert_eq!(actual, ordinary);
    assert_eq!(actual.cost, *meter.observations());
    assert_eq!(
        actual
            .cost
            .entries()
            .iter()
            .map(|entry| entry.stage)
            .collect::<Vec<_>>(),
        [
            CellCostStageV2::Codec,
            CellCostStageV2::Encoder,
            CellCostStageV2::Inference,
            CellCostStageV2::Codec
        ]
    );
    assert!(actual.cost.entries().iter().all(|entry| {
        entry.metrics.wall_micros.is_some()
            && entry.metrics.cpu_micros.is_some()
            && entry.metrics.energy_microjoules.is_none()
            && entry.accounting == CellCostAccountingV2::Exclusive
            && entry.outcome == CellCostOutcomeV2::Succeeded
    }));
    Ok(())
}

#[test]
fn original_b_native_expiry_stops_before_inference_without_extending_the_clock()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let model = load(root.path(), /*factor*/ 1)?;
    let baseline = bundle(&model, /*prior*/ None)?;
    let config = configured(&model, &baseline)?;
    let calls = Arc::new(AtomicU64::new(/*v*/ 0));
    let actual_calls = Arc::clone(&calls);
    let worker = model.into_worker(
        &baseline,
        config.manifest.clone(),
        Arc::new(move || {
            if actual_calls.fetch_add(1, Ordering::AcqRel) == 0 {
                11
            } else {
                100
            }
        }),
    )?;
    let mut meter = meter(&config)?;
    assert_eq!(
        worker
            .execute_original_root_benchmark(&benchmark_request(&config), &mut meter)
            .err(),
        Some(CellGenerationErrorV2::Deadline)
    );
    assert_eq!(calls.load(Ordering::Acquire), 2);
    assert_eq!(
        meter
            .observations()
            .entries()
            .iter()
            .map(|entry| entry.stage)
            .collect::<Vec<_>>(),
        [CellCostStageV2::Codec, CellCostStageV2::Encoder]
    );
    Ok(())
}

#[test]
fn original_b_native_bad_input_retains_a_measured_failure_without_output() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let model = load(root.path(), /*factor*/ 1)?;
    let baseline = bundle(&model, /*prior*/ None)?;
    let config = configured(&model, &baseline)?;
    let worker = model.into_worker(&baseline, config.manifest.clone(), Arc::new(|| 11))?;
    let mut request = benchmark_request(&config);
    request.input.push(0);
    let mut meter = meter(&config)?;
    assert!(
        worker
            .execute_original_root_benchmark(&request, &mut meter)
            .is_err()
    );
    let [entry] = meter.observations().entries() else {
        anyhow::bail!("one actual failed decode required")
    };
    assert_eq!(
        (entry.stage, entry.outcome),
        (CellCostStageV2::Codec, CellCostOutcomeV2::Failed)
    );
    assert!(entry.metrics.cpu_micros.is_some() && entry.metrics.wall_micros.is_some());
    assert!(entry.metrics.energy_microjoules.is_none());
    Ok(())
}

#[test]
fn original_b_late_head_data_preserves_the_actual_frozen_graph_and_rejects_extra_change()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let model = load(root.path(), /*factor*/ 1)?;
    let baseline = bundle(&model, /*prior*/ None)?;
    let head = CellQ24PrivateHeadV1::Drive { index: 0 };
    let mut values = [Q / 2, 0, 0, Q, -Q, 0, 0, -Q];
    let bytes = matrix(/*rows*/ 4, /*cols*/ 2, &values);
    let mut candidate = bundle(&model, Some(&baseline))?;
    candidate.components.heads = Digest32::of_bytes(&bytes);
    let actual = model.read_single_head_candidate_data(&baseline, &candidate, head, &bytes)?;
    assert_eq!(actual.original_head_bytes(), bytes);
    assert_eq!(actual.components(), &candidate.components);
    let config = configured(&actual, &candidate)?;
    let result = actual
        .into_worker(&candidate, config.manifest.clone(), Arc::new(|| 11))?
        .execute(
            &config.manifest,
            &benchmark_request(&config),
            &AtomicBool::new(/*v*/ false),
        )?;
    let mut expected = output(3 * Q / 2);
    expected[10..18].copy_from_slice(&(Q / 2).to_le_bytes());
    assert_eq!(result.output_delta, expected);
    values[7] = -Q / 2;
    let changed = matrix(/*rows*/ 4, /*cols*/ 2, &values);
    candidate.components.heads = Digest32::of_bytes(&changed);
    assert!(
        model
            .read_single_head_candidate_data(&baseline, &candidate, head, &changed)
            .is_err()
    );
    candidate.components.heads = Digest32::of_bytes(&bytes);
    candidate.components.encoder = d("unrelated-encoder");
    assert!(
        model
            .read_single_head_candidate_data(&baseline, &candidate, head, &bytes)
            .is_err()
    );
    Ok(())
}
