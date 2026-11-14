//! Construct the exact native training material inside the original Prepared
//! read. Facts never replace the actual Dataset capability carried by batch.

use super::*;

impl CellQ24PreparedLearningV1 {
    pub(crate) fn training_material_in_operation(
        &self,
        dataset: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        read: &OriginalPreparedReadV1<'_>,
    ) -> Result<CellQ24PreparedTrainingMaterialV1, Error> {
        OriginalPreparedReadV1::require_prepared(read, self)?;
        let facts = OriginalPreparedReadV1::read_validated_facts(read)?;
        if scope != self.scope
            || dataset.request != self.initial.request
            || dataset.owners != self.initial.owners
            || dataset.receipts.len() != 2
            || dataset.receipts[0].observation != facts.experience
            || dataset.receipts[1].observation != facts.dataset
            || dataset.receipts[0].evidence_digest != facts.experience_evidence
            || dataset.receipts[1].evidence_digest != facts.dataset_evidence
        {
            return Err(Error::Binding(
                "original Experience and Dataset observations",
            ));
        }
        let plan = CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
            dataset,
            scope,
            Arc::clone(&self.config.baseline),
            self.config.head,
            self.config.rule.digest(&self.batch)?,
        )?;
        OriginalPreparedReadV1::require_prepared(read, self)?;
        Ok(CellQ24PreparedTrainingMaterialV1 {
            plan,
            batch: self.batch.clone(),
            rule: self.config.rule,
        })
    }
}
