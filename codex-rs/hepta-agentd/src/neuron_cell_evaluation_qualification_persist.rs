//! Private one-dispatch adapter for the original runner's publication boundary.
//! It owns no signature capability and is never returned to a caller.
use codex_hepta_intelligence_eval::ProductEvaluationExecutionClaimV1;
use codex_hepta_intelligence_eval::ProductEvidenceSinkErrorV1;
use codex_hepta_intelligence_eval::ProductQualificationEvidenceSinkV1;
use codex_hepta_intelligence_eval::SignedEvaluationDecisionV1;
use codex_hepta_types::Digest32;

use super::*;

pub(super) struct PersistPort<'a, W: AnchorWitnessStore> {
    pub(super) journal: &'a mut OriginalCellEvaluationExecutionStoreV1<W>,
    pub(super) config: &'a OriginalCellEvaluationQualificationConfigV1,
    pub(super) key: &'a ProductEvaluationExecutionKeyV1,
    pub(super) prepared: &'a Prepared,
    pub(super) started_at: u64,
    pub(super) used: bool,
    pub(super) error: Option<Error>,
}

impl<W: AnchorWitnessStore> PersistPort<'_, W> {
    fn persist_original(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, Error> {
        if self.used {
            return Err(Error::CommitUncertain);
        }
        self.used = true;
        if execution_digest != self.prepared.evaluation.temporal().execution_digest {
            return Err(Error::Binding("original Qualification execution digest"));
        }
        let current = binding::now()?;
        binding::new_work_time(self.config, self.started_at, current)?;
        binding::authenticate(self.config, self.prepared, current)?;
        let bytes = binding::decision_bytes(self.key, execution_digest, decision)?;
        match ProductEvaluationExecutionStoreV1::claim(self.journal, self.key)? {
            ProductEvaluationExecutionClaimV1::Claimed => {}
            ProductEvaluationExecutionClaimV1::Existing(State::Pending) => {
                return Err(Error::Pending);
            }
            ProductEvaluationExecutionClaimV1::Existing(State::Completed(_)) => {
                return Err(StoreError::Conflict.into());
            }
        }
        let current = binding::now()?;
        binding::new_work_time(self.config, self.started_at, current)?;
        binding::authenticate(self.config, self.prepared, current)?;
        ProductEvaluationExecutionStoreV1::complete(self.journal, self.key, &bytes)?;
        match ProductEvaluationExecutionStoreV1::readback(self.journal, self.key)? {
            State::Completed(original) if original == bytes => {}
            State::Pending => return Err(Error::Pending),
            State::Completed(_) => return Err(Error::CommitUncertain),
        }
        Ok(binding::publication_digest(self.key, &bytes))
    }
}

impl<W: AnchorWitnessStore> ProductQualificationEvidenceSinkV1 for PersistPort<'_, W> {
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        match self.persist_original(execution_digest, decision) {
            Ok(digest) => Ok(digest),
            Err(error) => {
                self.error = Some(error);
                Err(ProductEvidenceSinkErrorV1::Indeterminate)
            }
        }
    }
}
