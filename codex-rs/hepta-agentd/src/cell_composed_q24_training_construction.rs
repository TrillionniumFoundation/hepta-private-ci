//! Durable trainer creation and recovery use the original sealed source path.
//! The public path re-reads its own owner; aggregate assembly may borrow the
//! same actual Prepared operation. Neither path accepts affirmative data.

use super::*;

impl<W: AnchorWitnessStore> CellQ24TrainingOwnerV1<W> {
    pub(crate) fn create_with_source(
        file: File,
        mut witness: W,
        plan: CellQ24SingleHeadTrainingPlanV1,
        batch: CellQ24TrainingBatchV1,
        rule: CellQ24SgdRuleV1,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<Self, Error> {
        let key = job_key(&plan, &batch, rule, source)?;
        if witness.current()?.is_some() {
            return Err(Error::Binding("training witness already initialized"));
        }
        let journal =
            LockedFileProductEvaluationExecutionStoreV1::create(file, key.binding_digest)?;
        witness
            .compare_and_swap(None, anchor(journal.anchor()))
            .map_err(|_| Error::CommitUncertain)?;
        Ok(Self {
            journal,
            witness,
            plan,
            batch,
            rule,
            key,
            fenced: false,
        })
    }
    pub(crate) fn recover_with_source(
        file: File,
        mut witness: W,
        plan: CellQ24SingleHeadTrainingPlanV1,
        batch: CellQ24TrainingBatchV1,
        rule: CellQ24SgdRuleV1,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<Self, Error> {
        let key = job_key(&plan, &batch, rule, source)?;
        let minimum = witness
            .current()?
            .ok_or(Error::Binding("original training witness"))?;
        let sequence = minimum
            .sequence
            .checked_sub(1)
            .ok_or(Error::Binding("training witness sequence"))?;
        let journal = LockedFileProductEvaluationExecutionStoreV1::recover(
            file,
            key.binding_digest,
            ProductEvaluationExecutionAnchorV1 {
                sequence,
                history_digest: minimum.checkpoint_digest,
            },
        )?;
        let current = anchor(journal.anchor());
        if current != minimum {
            witness
                .compare_and_swap(Some(minimum), current)
                .map_err(|_| Error::CommitUncertain)?;
        }
        Ok(Self {
            journal,
            witness,
            plan,
            batch,
            rule,
            key,
            fenced: false,
        })
    }
}

fn job_key(
    plan: &CellQ24SingleHeadTrainingPlanV1,
    batch: &CellQ24TrainingBatchV1,
    rule: CellQ24SgdRuleV1,
    source: &impl OriginalQ24DatasetReadV1,
) -> Result<ProductEvaluationExecutionKeyV1, Error> {
    let optimizer = plan.validate_fit_input_with_source(batch, rule, source)?;
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: plan.prefix.request.operation_id.clone(),
        binding_digest: Digest32::of_parts(&[
            b"hepta.cell.q24.original-training-job.v1\0",
            plan.prefix.head_digest.as_array(),
            plan.scope.binding().as_array(),
            plan.baseline.effective_weights_digest().as_array(),
            batch.digest().as_array(),
            optimizer.as_array(),
        ]),
    })
}
