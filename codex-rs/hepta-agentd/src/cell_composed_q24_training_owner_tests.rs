//! Actual bounded optimizer, file locks, independent witness and cold reopen.
//! Source-role metadata is fixture data, not production custody or adoption.

use std::fs::OpenOptions;

use crate::CellQ24TrainingMetricsV1;
use crate::CellQ24TrainingOwnerErrorV1 as OwnerError;
use crate::CellQ24TrainingOwnerV1;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionErrorV1;
use pretty_assertions::assert_eq;

use super::*;

#[path = "cell_composed_q24_training_observation_tests.rs"]
mod observation;

fn opened(root: &Path, name: &str) -> anyhow::Result<File> {
    Ok(OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(root.join(name))?)
}

fn witness(root: &Path) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        opened(root, "witness")?,
        JournalScope {
            scope_digest: d("original-q24-trainer"),
            objective_digest: d("objective"),
        },
        Generation::new(1)?,
        /*max_records*/ 16,
    )?)
}

fn original_plan(
    baseline: Arc<LoadedCellQ24ModelV1>,
    prefix: &LearningIterationSnapshotV1,
    batch: &CellQ24TrainingBatchV1,
    rule: CellQ24SgdRuleV1,
) -> anyhow::Result<CellQ24SingleHeadTrainingPlanV1> {
    let head = CellQ24PrivateHeadV1::Drive { index: 0 };
    let optimizer = rule.digest(batch)?;
    let scope = FrozenLearningScopeV2::freeze(
        &prefix.request,
        &prefix.owners,
        LearningUpdateScopeV2::Cell,
        cell_q24_single_head_update_rule_v1(&prefix.request.selected_bundle, head, optimizer)?,
    )?;
    Ok(CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
        prefix.clone(),
        scope,
        baseline,
        head,
        optimizer,
    )?)
}

fn result_identity(
    outcome: &CellQ24TrainingOutcomeV1,
) -> anyhow::Result<(Digest32, Vec<u8>, CellQ24TrainingMetricsV1)> {
    Ok(match outcome {
        CellQ24TrainingOutcomeV1::Candidate(candidate) => (
            candidate.bundle.digest()?,
            candidate.heads.clone(),
            candidate.metrics.clone(),
        ),
        CellQ24TrainingOutcomeV1::NoUpdate {
            retained_bundle,
            metrics,
        } => (*retained_bundle, Vec::new(), metrics.clone()),
    })
}

#[test]
fn q24_training_owner_cold_readback_preserves_candidate_and_no_update() -> anyhow::Result<()> {
    for target in [2 * Q, Q] {
        let root = tempfile::tempdir()?;
        let baseline = Arc::new(load(root.path(), /*factor*/ 1)?);
        let selected = bundle(&baseline, /*prior*/ None)?;
        let original_heads = fs::read(root.path().join("heads"))?;
        let rule = CellQ24SgdRuleV1 {
            epochs: 2,
            learning_rate_q24: Q / 2,
        };
        let data = batch(target)?;
        let (plan, prefix) = plan(
            Arc::clone(&baseline),
            &selected,
            &data,
            CellQ24PrivateHeadV1::Drive { index: 0 },
            rule,
            "none",
        )?;
        let mut owner = CellQ24TrainingOwnerV1::create(
            opened(root.path(), "job")?,
            witness(root.path())?,
            plan,
            data.clone(),
            rule,
        )?;
        let original = owner.fit_or_readback(&AtomicBool::new(false))?;
        assert_eq!(
            matches!(original, CellQ24TrainingOutcomeV1::NoUpdate { .. }),
            target == Q
        );
        let expected = result_identity(&original)?;
        let saved = fs::read(root.path().join("job"))?;
        assert_eq!(
            result_identity(&owner.fit_or_readback(&AtomicBool::new(true))?)?,
            expected
        );
        // A separately opened witness cannot become a second writer.
        assert!(witness(root.path()).is_err());
        drop(owner);
        let baseline = Arc::new(private_head::reopen(root.path())?);
        let plan = original_plan(Arc::clone(&baseline), &prefix, &data, rule)?;
        let mut owner = CellQ24TrainingOwnerV1::recover(
            opened(root.path(), "job")?,
            witness(root.path())?,
            plan,
            data,
            rule,
        )?;
        let recovered = owner.fit_or_readback(&AtomicBool::new(true))?;
        assert_eq!(result_identity(&recovered)?, expected);
        if let CellQ24TrainingOutcomeV1::Candidate(candidate) = recovered {
            let model = Arc::new(candidate.model);
            let after = predict(&model, &candidate.bundle, [Q / 4, Q / 8], "cold-candidate")?;
            let before = predict(&baseline, &selected, [Q / 4, Q / 8], "cold-baseline")?;
            assert_eq!((&after[1..], after[0]), (&before[1..], 7 * Q / 8));
        }
        assert_eq!(fs::read(root.path().join("job"))?, saved);
        assert_eq!(fs::read(root.path().join("heads"))?, original_heads);
    }
    Ok(())
}

#[test]
fn q24_training_owner_cancelled_admission_never_retrains_after_reopen() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let baseline = Arc::new(load(root.path(), /*factor*/ 1)?);
    let selected = bundle(&baseline, /*prior*/ None)?;
    let data = batch(2 * Q)?;
    let rule = CellQ24SgdRuleV1 {
        epochs: 2,
        learning_rate_q24: Q / 2,
    };
    let (plan, prefix) = plan(
        Arc::clone(&baseline),
        &selected,
        &data,
        CellQ24PrivateHeadV1::Drive { index: 0 },
        rule,
        "none",
    )?;
    let mut owner = CellQ24TrainingOwnerV1::create(
        opened(root.path(), "job")?,
        witness(root.path())?,
        plan,
        data.clone(),
        rule,
    )?;
    assert!(matches!(
        owner.fit_or_readback(&AtomicBool::new(true)),
        Err(OwnerError::Training(CellQ24TrainingErrorV1::Cancelled))
    ));
    let admitted = fs::read(root.path().join("job"))?;
    drop(owner);
    let plan = original_plan(baseline, &prefix, &data, rule)?;
    let mut recovered = CellQ24TrainingOwnerV1::recover(
        opened(root.path(), "job")?,
        witness(root.path())?,
        plan,
        data,
        rule,
    )?;
    assert!(matches!(
        recovered.fit_or_readback(&AtomicBool::new(false)),
        Err(OwnerError::Pending)
    ));
    assert!(matches!(recovered.readback(), Err(OwnerError::Pending)));
    assert!(matches!(
        recovered.read_learning_observation(&prefix),
        Err(OwnerError::Pending)
    ));
    assert_eq!(fs::read(root.path().join("job"))?, admitted);
    Ok(())
}

enum LostAck {
    BeforeWrite,
    AfterWrite,
}

struct FaultWitness {
    inner: FileAnchorWitnessStore,
    sequence: u64,
    fault: LostAck,
}

impl AnchorWitnessStore for FaultWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if next.sequence == self.sequence {
            if matches!(self.fault, LostAck::AfterWrite) {
                self.inner.compare_and_swap(expected, next)?;
            }
            return Err(WitnessStoreError::Indeterminate);
        }
        self.inner.compare_and_swap(expected, next)
    }
}

#[test]
fn q24_training_owner_recovers_lost_admission_and_completion_witness_acks() -> anyhow::Result<()> {
    for sequence in [2, 3] {
        for fault in [LostAck::BeforeWrite, LostAck::AfterWrite] {
            let root = tempfile::tempdir()?;
            let baseline = Arc::new(load(root.path(), /*factor*/ 1)?);
            let selected = bundle(&baseline, /*prior*/ None)?;
            let data = batch(2 * Q)?;
            let rule = CellQ24SgdRuleV1 {
                epochs: 2,
                learning_rate_q24: Q / 2,
            };
            let (plan, prefix) = plan(
                Arc::clone(&baseline),
                &selected,
                &data,
                CellQ24PrivateHeadV1::Drive { index: 0 },
                rule,
                "none",
            )?;
            let mut owner = CellQ24TrainingOwnerV1::create(
                opened(root.path(), "job")?,
                FaultWitness {
                    inner: witness(root.path())?,
                    sequence,
                    fault,
                },
                plan,
                data.clone(),
                rule,
            )?;
            assert!(matches!(
                owner.fit_or_readback(&AtomicBool::new(false)),
                Err(OwnerError::CommitUncertain)
            ));
            assert!(matches!(owner.readback(), Err(OwnerError::CommitUncertain)));
            assert!(matches!(
                owner.read_learning_observation(&prefix),
                Err(OwnerError::CommitUncertain)
            ));
            let saved = fs::read(root.path().join("job"))?;
            drop(owner);
            let plan = original_plan(baseline, &prefix, &data, rule)?;
            let mut owner = CellQ24TrainingOwnerV1::recover(
                opened(root.path(), "job")?,
                witness(root.path())?,
                plan,
                data,
                rule,
            )?;
            let recovered = owner.fit_or_readback(&AtomicBool::new(true));
            if sequence == 2 {
                assert!(matches!(recovered, Err(OwnerError::Pending)));
            } else {
                let recovered = recovered?;
                assert!(matches!(recovered, CellQ24TrainingOutcomeV1::Candidate(_)));
                assert_eq!(result_identity(&recovered)?.2.optimizer_steps, 2);
                assert_eq!(
                    result_identity(&owner.readback()?)?,
                    result_identity(&recovered)?
                );
            }
            assert_eq!(fs::read(root.path().join("job"))?, saved);
        }
    }
    Ok(())
}

#[test]
fn q24_training_owner_rejects_changed_binding_rollback_and_torn_completion() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let baseline = Arc::new(load(root.path(), /*factor*/ 1)?);
    let selected = bundle(&baseline, /*prior*/ None)?;
    let data = batch(2 * Q)?;
    let rule = CellQ24SgdRuleV1 {
        epochs: 2,
        learning_rate_q24: Q / 2,
    };
    let (plan, prefix) = plan(
        Arc::clone(&baseline),
        &selected,
        &data,
        CellQ24PrivateHeadV1::Drive { index: 0 },
        rule,
        "none",
    )?;
    let mut owner = CellQ24TrainingOwnerV1::create(
        opened(root.path(), "job")?,
        witness(root.path())?,
        plan,
        data.clone(),
        rule,
    )?;
    let genesis = fs::read(root.path().join("job"))?;
    owner.fit_or_readback(&AtomicBool::new(false))?;
    let completed = fs::read(root.path().join("job"))?;
    drop(owner);
    // Different data under the same operation and source-dataset label still
    // changes its frozen rule and complete job binding; it is not a new claim.
    let altered = batch(Q)?;
    let plan = original_plan(Arc::clone(&baseline), &prefix, &altered, rule)?;
    assert!(matches!(
        CellQ24TrainingOwnerV1::recover(
            opened(root.path(), "job")?,
            witness(root.path())?,
            plan,
            altered,
            rule,
        ),
        Err(OwnerError::File(
            LockedFileProductEvaluationExecutionErrorV1::Corrupt
        ))
    ));
    assert_eq!(fs::read(root.path().join("job"))?, completed);
    fs::write(root.path().join("job"), &genesis)?;
    let plan = original_plan(Arc::clone(&baseline), &prefix, &data, rule)?;
    assert!(matches!(
        CellQ24TrainingOwnerV1::recover(
            opened(root.path(), "job")?,
            witness(root.path())?,
            plan,
            data.clone(),
            rule,
        ),
        Err(OwnerError::File(
            LockedFileProductEvaluationExecutionErrorV1::Rollback
        ))
    ));
    fs::write(root.path().join("job"), &completed[..completed.len() - 1])?;
    let plan = original_plan(baseline, &prefix, &data, rule)?;
    assert!(
        CellQ24TrainingOwnerV1::recover(
            opened(root.path(), "job")?,
            witness(root.path())?,
            plan,
            data,
            rule,
        )
        .is_err()
    );
    Ok(())
}
