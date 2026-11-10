//! Native optimization and serving on real Q24 bytes. Source-role metadata
//! remains an explicit fixture; these are not daemon/Root or science results.

use super::*;
use crate::CellQ24PrivateHeadV1;
use crate::CellQ24SgdRuleV1;
use crate::CellQ24SingleHeadTrainingPlanV1;
use crate::CellQ24TrainedCandidateV1;
use crate::CellQ24TrainingBatchV1;
use crate::CellQ24TrainingErrorV1;
use crate::CellQ24TrainingOutcomeV1;
use crate::CellQ24TrainingSampleV1;
use crate::cell_q24_single_head_update_rule_v1;

fn batch(target: i64) -> anyhow::Result<CellQ24TrainingBatchV1> {
    Ok(CellQ24TrainingBatchV1::new(d("dataset"), vec![CellQ24TrainingSampleV1 {
        input: vec![Q / 2, 0], target,
    }])?)
}

fn plan(
    baseline: Arc<LoadedCellQ24ModelV1>,
    selected: &CellCompatibilityBundleV1,
    batch: &CellQ24TrainingBatchV1,
    head: CellQ24PrivateHeadV1,
    rule: CellQ24SgdRuleV1,
    mutation: &str,
) -> anyhow::Result<(CellQ24SingleHeadTrainingPlanV1, LearningIterationSnapshotV1)> {
    let fixture = Fixture::new(configured(&baseline, selected)?)?;
    let history = learning_test_decision(&fixture, selected.clone(), "none")?;
    let mut request = history.snapshot().request.clone();
    request.envelope.expiry_unix_seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?.as_secs() + 60;
    request.budget.maximum_dataset_rows = batch.rows();
    request.budget.maximum_dataset_bytes = 16_384;
    request.budget.maximum_training_steps = 1_024;
    request.budget.maximum_training_milliseconds = 10_000;
    request.budget.maximum_artifact_bytes = 4_096;
    match mutation {
        "steps" => request.budget.maximum_training_steps = 1,
        "expired" => request.envelope.expiry_unix_seconds = 100,
        "none" | "bytes" => {}
        _ => anyhow::bail!("unexpected fixture mutation"),
    }
    let mut coordinator = LearningIterationCoordinatorV1::new(
        request, history.snapshot().owners.clone(),
    )?;
    let observation = history.snapshot().receipts[0].observation.clone();
    coordinator.record(learning_test_receipt(&coordinator, observation), 20)?;
    coordinator.record(learning_test_receipt(&coordinator, LearningIterationObservationV1::Dataset {
        snapshot_digest: d("dataset"), episode_digest: d("episode"),
        withdrawal_frontier: d("withdrawals"), rows: batch.rows(),
        bytes: batch.encoded().len() as u64 + u64::from(mutation == "bytes"),
    }), 20)?;
    let prefix = coordinator.snapshot().clone();
    let optimizer = rule.digest(batch)?;
    let scope = FrozenLearningScopeV2::freeze(
        &prefix.request, &prefix.owners, LearningUpdateScopeV2::Cell,
        cell_q24_single_head_update_rule_v1(selected, head, optimizer)?,
    )?;
    Ok((CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
        prefix.clone(), scope, baseline, head, optimizer,
    )?, prefix))
}

fn predict(
    model: &Arc<LoadedCellQ24ModelV1>, bundle: &CellCompatibilityBundleV1,
    values: [i64; 2], operation: &str,
) -> anyhow::Result<Vec<i64>> {
    let config = configured(model, bundle)?;
    let worker = model.shared_worker(bundle, config.manifest.clone(), Arc::new(|| 11))?;
    let mut input = b"HQ24I001".to_vec();
    input.extend_from_slice(&2_u16.to_le_bytes());
    for value in values { input.extend_from_slice(&value.to_le_bytes()); }
    let request = CellGenerationRequestV2 {
        operation_id: operation.into(), task_digest: config.task_digest,
        source_frontier: config.source_frontier, predecessor: config.initial,
        input, admitted_at_micros: 10, deadline_micros: 100,
    };
    let output = worker.execute(&config.manifest, &request, &AtomicBool::new(false))?;
    assert_eq!(output.disposition, CellGenerationDispositionV2::Stopped);
    Ok(output.output_delta[10..].chunks_exact(8)
        .map(|value| value.try_into().map(i64::from_le_bytes))
        .collect::<Result<Vec<_>, _>>()?)
}

#[test]
fn q24_native_sgd_changes_one_row_and_serves_distinct_inputs_after_reopen() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let baseline = Arc::new(load(root.path(), /*factor*/ 1)?);
    let selected = bundle(&baseline, /*prior*/ None)?;
    let original_components = baseline.components().clone();
    let rule = CellQ24SgdRuleV1 { epochs: 2, learning_rate_q24: Q / 2 };
    for (head, target, changed, expected) in [
        (CellQ24PrivateHeadV1::Drive { index: 0 }, 2 * Q, 0, 7 * Q / 8),
        (CellQ24PrivateHeadV1::Prediction { index: 0 }, 0, 2, -Q / 8),
    ] {
        let data = batch(target)?;
        let (plan, prefix) = plan(Arc::clone(&baseline), &selected, &data, head, rule, "none")?;
        let CellQ24TrainingOutcomeV1::Candidate(candidate) = plan.fit(data, rule, &AtomicBool::new(false))?
        else { anyhow::bail!("expected real changed head") };
        let CellQ24TrainedCandidateV1 { model, bundle: candidate_bundle, heads, metrics } = *candidate;
        assert_eq!((metrics.optimizer_steps, metrics.squared_error_before_q48, metrics.squared_error_after_q48),
            (2, (Q as u128).pow(2), ((Q / 4) as u128).pow(2)));
        assert_eq!(baseline.components(), &original_components);
        assert_eq!(Digest32::of_bytes(&heads), model.components().heads);
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(prefix)?;
        coordinator.record(learning_test_receipt(&coordinator, LearningIterationObservationV1::Training {
            candidate: Box::new(candidate_bundle.clone()), steps: metrics.optimizer_steps,
            milliseconds: metrics.elapsed_microseconds.div_ceil(1_000).max(1),
            artifact_bytes: heads.len() as u64,
        }), 20)?;
        let model = Arc::new(plan.validate_training_candidate(coordinator.snapshot(), model)?);
        // B differs from training A; unchanged outputs form a retention panel.
        let before = predict(&baseline, &selected, [Q / 4, Q / 8], "baseline-b")?;
        let after = predict(&model, &candidate_bundle, [Q / 4, Q / 8], "candidate-b")?;
        let mut expected_outputs = before.clone();
        expected_outputs[changed] = expected;
        assert_eq!(after, expected_outputs);
        let desired = if changed == 0 { Q } else { 0 };
        assert!((after[changed] - desired).abs() < (before[changed] - desired).abs());
        fs::write(root.path().join("heads"), &heads)?;
        let reopened = Arc::new(private_head::reopen(root.path())?);
        assert_eq!(reopened.components(), model.components());
        // C has another input and another actual worker, consuming exact bytes.
        assert_eq!(predict(&reopened, &candidate_bundle, [Q / 8, Q / 16], "fresh-c")?,
            predict(&model, &candidate_bundle, [Q / 8, Q / 16], "loaded-c")?);
        fs::write(root.path().join("heads"), b"untrusted-replacement")?;
        assert_eq!(predict(&baseline, &selected, [Q / 4, Q / 8], "retained-parent")?, before);
    }
    Ok(())
}

#[test]
fn q24_native_sgd_reports_no_update_when_actual_quantized_bytes_stay_equal() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let baseline = Arc::new(load(root.path(), /*factor*/ 1)?);
    let selected = bundle(&baseline, /*prior*/ None)?;
    let data = batch(Q)?;
    let rule = CellQ24SgdRuleV1 { epochs: 3, learning_rate_q24: Q / 2 };
    let (plan, prefix) = plan(Arc::clone(&baseline), &selected, &data,
        CellQ24PrivateHeadV1::Drive { index: 0 }, rule, "none")?;
    let CellQ24TrainingOutcomeV1::NoUpdate { retained_bundle, metrics } =
        plan.fit(data, rule, &AtomicBool::new(false))?
    else { anyhow::bail!("unchanged coefficients must not create a candidate") };
    assert_eq!((retained_bundle, metrics.optimizer_steps, metrics.squared_error_before_q48,
        metrics.squared_error_after_q48), (selected.digest()?, 3, 0, 0));
    assert_eq!(prefix.receipts.len(), 2);
    assert_eq!(predict(&baseline, &selected, [Q / 4, 0], "no-update-c")?, vec![Q / 2, 0, -Q / 2, 0]);
    Ok(())
}

#[test]
fn q24_native_sgd_refuses_changed_frozen_inputs_quota_deadline_and_cancellation() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let baseline = Arc::new(load(root.path(), /*factor*/ 1)?);
    let selected = bundle(&baseline, /*prior*/ None)?;
    let rule = CellQ24SgdRuleV1 { epochs: 2, learning_rate_q24: Q / 2 };
    let head = CellQ24PrivateHeadV1::Drive { index: 0 };
    for mutation in ["steps", "bytes", "expired", "none"] {
        let data = batch(2 * Q)?;
        let (plan, _) = plan(Arc::clone(&baseline), &selected, &data, head, rule, mutation)?;
        let result = plan.fit(data, rule, &AtomicBool::new(mutation == "none"));
        match mutation {
            "steps" | "bytes" => assert!(matches!(result, Err(CellQ24TrainingErrorV1::Binding(_)))),
            "expired" => assert!(matches!(result, Err(CellQ24TrainingErrorV1::DeadlineExceeded))),
            "none" => assert!(matches!(result, Err(CellQ24TrainingErrorV1::Cancelled))),
            _ => unreachable!(),
        }
    }
    let original = batch(2 * Q)?;
    let (plan, _) = plan(Arc::clone(&baseline), &selected, &original, head, rule, "none")?;
    assert!(matches!(plan.fit(batch(Q)?, rule, &AtomicBool::new(false)), Err(CellQ24TrainingErrorV1::Plan(_))));
    assert!(matches!(plan.fit(original, CellQ24SgdRuleV1 { epochs: 3, ..rule }, &AtomicBool::new(false)),
        Err(CellQ24TrainingErrorV1::Plan(_))));
    assert_eq!(predict(&baseline, &selected, [Q / 2, 0], "unchanged-after-refusals")?, vec![Q, 0, -Q, 0]);
    Ok(())
}
