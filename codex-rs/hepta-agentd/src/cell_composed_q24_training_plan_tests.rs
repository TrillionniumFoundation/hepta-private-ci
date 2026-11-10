//! Actual loaded material and structurally valid synthetic stage histories.
//! No optimizer, stage attestation, Root registration or evaluation is executed.

use pretty_assertions::assert_eq;

use super::*;
use crate::CellQ24PrivateHeadV1;
use crate::CellQ24SingleHeadTrainingPlanV1;
use crate::cell_q24_single_head_update_rule_v1;

const HEADS: [i64; 8] = [Q, 0, 0, Q, -Q, 0, 0, -Q];

fn dataset_cut(
    model: &LoadedCellQ24ModelV1,
    selected: &CellCompatibilityBundleV1,
) -> anyhow::Result<LearningIterationSnapshotV1> {
    let publication = Fixture::new(configured(model, selected)?)?;
    let decision = learning_test_decision(&publication, selected.clone(), "none")?;
    let mut coordinator = LearningIterationCoordinatorV1::new(
        decision.snapshot().request.clone(),
        decision.snapshot().owners.clone(),
    )?;
    for receipt in decision.snapshot().receipts.iter().take(2) {
        coordinator.record(receipt.clone(), 20)?;
    }
    Ok(coordinator.snapshot().clone())
}

fn frozen(
    prefix: &LearningIterationSnapshotV1,
    head: CellQ24PrivateHeadV1,
    optimizer: Digest32,
) -> anyhow::Result<FrozenLearningScopeV2> {
    Ok(FrozenLearningScopeV2::freeze(
        &prefix.request,
        &prefix.owners,
        LearningUpdateScopeV2::Cell,
        cell_q24_single_head_update_rule_v1(&prefix.request.selected_bundle, head, optimizer)?,
    )?)
}

fn trained_material(
    path: &Path,
    values: &[i64; 8],
    prefix: &LearningIterationSnapshotV1,
    rule: Digest32,
) -> anyhow::Result<(
    LoadedCellQ24ModelV1,
    CellCompatibilityBundleV1,
    LearningIterationSnapshotV1,
)> {
    drop(load(path, /*factor*/ 1)?);
    fs::write(path.join("heads"), matrix(/*rows*/ 4, /*cols*/ 2, values))?;
    let file = |name| File::open(path.join(name));
    let model = LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {
        base: file("base")?,
        encoder: file("encoder")?,
        heads: file("heads")?,
        organ_adapter: Some(file("organ")?),
        cell_adapter: Some(file("cell")?),
    })?;
    let mut candidate = bundle(&model, Some(&prefix.request.selected_bundle))?;
    let original_dataset = prefix.receipts.last()
        .ok_or_else(|| anyhow::anyhow!("fixture requires the Dataset receipt"))?;
    let dataset = match &original_dataset.observation {
        LearningIterationObservationV1::Dataset { snapshot_digest, .. } => *snapshot_digest,
        _ => anyhow::bail!("fixture Dataset prefix"),
    };
    let lineage = candidate.training_lineage.as_mut()
        .ok_or_else(|| anyhow::anyhow!("fixture requires candidate lineage"))?;
    lineage.dataset = dataset;
    lineage.update_rule = rule;
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(prefix.clone())?;
    coordinator.record(
        learning_test_receipt(
            &coordinator,
            LearningIterationObservationV1::Training {
                candidate: Box::new(candidate.clone()),
                steps: 1,
                milliseconds: 1,
                artifact_bytes: 64,
            },
        ),
        20,
    )?;
    Ok((model, candidate, coordinator.snapshot().clone()))
}

#[test]
fn q24_frozen_plan_returns_exact_candidate_for_actual_worker_execution() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let baseline = Arc::new(load(root.path(), /*factor*/ 1)?);
    let selected = bundle(&baseline, /*prior*/ None)?;
    let prefix = dataset_cut(&baseline, &selected)?;
    for (head, coefficient, value, expected) in [
        (
            CellQ24PrivateHeadV1::Drive { index: 1 },
            2,
            Q / 2,
            [Q, 2 * Q, -Q, -3 * Q / 2],
        ),
        (
            CellQ24PrivateHeadV1::Prediction { index: 0 },
            4,
            -Q / 2,
            [Q, 3 * Q / 2, -Q / 2, -3 * Q / 2],
        ),
    ] {
        let optimizer = d("original optimizer contract");
        let rule = cell_q24_single_head_update_rule_v1(&selected, head, optimizer)?;
        let plan = CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
            prefix.clone(), frozen(&prefix, head, optimizer)?, Arc::clone(&baseline), head, optimizer,
        )?;
        let mut values = HEADS;
        values[coefficient] = value;
        let (candidate, candidate_bundle, result) =
            trained_material(root.path(), &values, &prefix, rule)?;
        let candidate = plan.validate_training_candidate(&result, candidate)?;
        let config = configured(&candidate, &candidate_bundle)?;
        let worker = candidate.into_worker(
            &candidate_bundle, config.manifest.clone(), Arc::new(|| 11),
        )?;
        // Path replacement cannot change either resident checked allocation.
        fs::write(root.path().join("heads"), b"replaced-after-validation")?;
        let request = CellGenerationRequestV2 {
            operation_id: "frozen-row-material".into(),
            task_digest: config.task_digest,
            source_frontier: config.source_frontier,
            predecessor: config.initial,
            input: input(),
            admitted_at_micros: 10,
            deadline_micros: 100,
        };
        let output = worker.execute(&config.manifest, &request, &AtomicBool::new(false))?;
        let mut bytes = b"HQ24O001".to_vec();
        bytes.extend_from_slice(&2_u16.to_le_bytes());
        for value in expected { bytes.extend_from_slice(&value.to_le_bytes()); }
        assert_eq!(
            (output.disposition, output.output_delta, output.successor_state),
            (CellGenerationDispositionV2::Stopped, bytes, Vec::new()),
        );
        assert_eq!(result.receipts.len(), prefix.receipts.len() + 1);
    }
    Ok(())
}

#[test]
fn q24_plan_binds_full_baseline_row_optimizer_and_original_scope() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let baseline = Arc::new(load(root.path(), /*factor*/ 1)?);
    let selected = bundle(&baseline, /*prior*/ None)?;
    let prefix = dataset_cut(&baseline, &selected)?;
    let head = CellQ24PrivateHeadV1::Drive { index: 1 };
    let optimizer = d("original optimizer contract");
    let scope = frozen(&prefix, head, optimizer)?;
    for (other_head, other_optimizer) in [
        (CellQ24PrivateHeadV1::Drive { index: 0 }, optimizer),
        (CellQ24PrivateHeadV1::Prediction { index: 1 }, optimizer),
        (CellQ24PrivateHeadV1::Drive { index: 2 }, optimizer),
        (head, d("different optimizer")),
        (head, Digest32::ZERO),
    ] {
        assert!(CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
            prefix.clone(), scope.clone(), Arc::clone(&baseline), other_head, other_optimizer,
        ).is_err());
    }
    let changed = Arc::new(load(root.path(), /*factor*/ 2)?);
    assert!(CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
        prefix.clone(), scope.clone(), changed, head, optimizer,
    ).is_err());
    let mut other_selected = selected;
    other_selected.artifact_id = StableId::new("different-original-bundle")?;
    let other_prefix = dataset_cut(&baseline, &other_selected)?;
    assert!(CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
        other_prefix, scope.clone(), Arc::clone(&baseline), head, optimizer,
    ).is_err());
    let organ_scope = FrozenLearningScopeV2::freeze(
        &prefix.request, &prefix.owners, LearningUpdateScopeV2::Organ,
        cell_q24_single_head_update_rule_v1(&prefix.request.selected_bundle, head, optimizer)?,
    )?;
    assert!(CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
        prefix, organ_scope, baseline, head, optimizer,
    ).is_err());
    Ok(())
}

#[test]
fn q24_plan_refuses_other_valid_training_histories_or_material() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let baseline = Arc::new(load(root.path(), /*factor*/ 1)?);
    let selected = bundle(&baseline, /*prior*/ None)?;
    let prefix = dataset_cut(&baseline, &selected)?;
    let head = CellQ24PrivateHeadV1::Drive { index: 1 };
    let optimizer = d("original optimizer contract");
    let rule = cell_q24_single_head_update_rule_v1(&selected, head, optimizer)?;
    let scope = frozen(&prefix, head, optimizer)?;
    let plan = CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
        prefix.clone(), scope.clone(), Arc::clone(&baseline), head, optimizer,
    )?;
    for scenario in 0..5 {
        let mut other_prefix = prefix.clone();
        if scenario == 0 {
            let mut replay = LearningIterationCoordinatorV1::new(
                prefix.request.clone(), prefix.owners.clone(),
            )?;
            for (index, original) in prefix.receipts.iter().enumerate() {
                let mut receipt = original.clone();
                receipt.predecessor = replay.snapshot().head_digest;
                if index == 1 { receipt.evidence_digest = d("different Dataset evidence"); }
                replay.record(receipt, 20)?;
            }
            other_prefix = replay.snapshot().clone();
        }
        let mut values = HEADS;
        values[2] = Q / 2;
        if scenario == 4 { values[7] = -Q / 2; }
        let result_rule = if scenario == 3 { d("uncommitted rule") } else { rule };
        let (candidate, candidate_bundle, mut result) =
            trained_material(root.path(), &values, &other_prefix, result_rule)?;
        let candidate = if scenario == 1 {
            values[2] = Q / 4;
            trained_material(root.path(), &values, &prefix, rule)?.0
        } else { candidate };
        if scenario == 2 {
            let mut extended = LearningIterationCoordinatorV1::from_snapshot(result)?;
            extended.record(
                learning_test_receipt(
                    &extended,
                    LearningIterationObservationV1::Evaluation {
                        candidate_bundle: candidate_bundle.digest()?,
                        evaluation_profile: prefix.request.evaluation_profile,
                        disposition: LearningEvaluationDispositionV1::NoUpdate,
                    },
                ), 20,
            )?;
            result = extended.snapshot().clone();
        }
        // Every rejected result is a valid complete coordinator history.
        LearningIterationCoordinatorV1::from_snapshot(result.clone())?;
        assert!(plan.validate_training_candidate(&result, candidate).is_err());
    }
    let mut values = HEADS;
    values[2] = Q / 2;
    let (_, _, after_training) = trained_material(root.path(), &values, &prefix, rule)?;
    assert!(CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
        after_training, scope, baseline, head, optimizer,
    ).is_err());
    Ok(())
}
