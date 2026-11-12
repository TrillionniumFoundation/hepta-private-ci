//! Captured job identity is separate from the immutable Root-frozen rule.
//! These factories consume the sealed live capture; neither accepts a batch,
//! provenance digest, callback or an existing legacy owner to relabel.

use crate::OriginalCellQ24TrainingSourceV1;

use super::*;

#[path = "cell_q24_training_source_owner_read.rs"]
mod readonly;

impl<W: AnchorWitnessStore> CellQ24TrainingOwnerV1<W> {
    /// Bind a new original native job to actual source custody. Construction is
    /// synchronous owner I/O; the host must use a bounded blocking lane. The
    /// resulting owner must enter SourceBoundCellQ24TrainingStageV1 before it
    /// serves ordinary Training commands. Success only binds the journal to
    /// the capture identity; Stage admission performs a new actual CURRENT. No role key or enrollment is created.
    pub fn create_from_original_source(
        file: File,
        mut witness: W,
        source: OriginalCellQ24TrainingSourceV1,
    ) -> Result<Self, Error> {
        let (plan, batch, rule) = source.native_inputs()?;
        let key = captured_job_key(&plan, &batch, rule, &source)?;
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
            source: Some(source),
            fenced: false,
        })
    }

    /// Reconcile only this same captured-profile journal and witness. Complete
    /// Material signature bytes participate in its key, so a renewed signature,
    /// legacy batch or changed original freeze cannot cold-rebind the job.
    /// This opens no Source, Ledger, evidence socket, key or replacement scope.
    pub fn recover_from_original_source(
        file: File,
        mut witness: W,
        source: OriginalCellQ24TrainingSourceV1,
    ) -> Result<Self, Error> {
        let (plan, batch, rule) = source.native_inputs()?;
        let key = captured_job_key(&plan, &batch, rule, &source)?;
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
            source: Some(source),
            fenced: false,
        })
    }

    /// Only the already occupied original blocking lane calls these reads.
    /// Any failed check fences the live owner. Recovery must retain the same
    /// captured identity; unavailability is never an optimizer NoUpdate.
    pub(crate) fn require_original_source_capture(&mut self) -> Result<(), Error> {
        if self.fenced {
            return Err(Error::CommitUncertain);
        }
        let result = self
            .source
            .as_ref()
            .ok_or(Error::Binding(
                "ordinary Training requires original source capture",
            ))
            .and_then(|source| {
                OriginalCellQ24TrainingSourceV1::require_current_in_lane(source)
                    .map_err(Error::from)
            });
        if result.is_err() {
            self.fenced = true;
        }
        result
    }

    pub(crate) fn require_captured_work_deadline(&self) -> Result<(), Error> {
        if self.source.is_some() {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_err(|_| Error::Binding("captured work clock before Unix epoch"))?
                .as_secs();
            if now >= self.plan.prefix.request.envelope.expiry_unix_seconds {
                return Err(CellQ24TrainingErrorV1::DeadlineExceeded.into());
            }
        }
        Ok(())
    }

    /// True identifies an actual private capture after this fresh read. It is
    /// not a cached authorization and cannot be supplied by a command caller.
    pub(crate) fn require_live_source_if_captured(&mut self) -> Result<bool, Error> {
        if self.source.is_some() {
            self.require_original_source_capture()?;
            Ok(true)
        } else {
            Ok(false)
        }
    }
}

fn captured_job_key(
    plan: &CellQ24SingleHeadTrainingPlanV1,
    batch: &CellQ24TrainingBatchV1,
    rule: CellQ24SgdRuleV1,
    source: &OriginalCellQ24TrainingSourceV1,
) -> Result<ProductEvaluationExecutionKeyV1, Error> {
    let original = job_key(plan, batch, rule)?;
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: original.plan_id,
        binding_digest: Digest32::of_parts(&[
            b"hepta.cell.q24.original-source-training-job.v1\0",
            original.binding_digest.as_array(),
            source.source_capture_binding().as_array(),
        ]),
    })
}
