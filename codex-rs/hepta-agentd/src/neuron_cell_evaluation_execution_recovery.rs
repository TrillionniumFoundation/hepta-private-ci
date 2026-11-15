//! Cold recovery cannot initialize, advance or repair an original witness.

use super::*;

impl<W: AnchorWitnessStore> OriginalCellEvaluationExecutionStoreV1<W> {
    /// Reopen only the original exactly witnessed history. Even a valid raw
    /// suffix beyond the retained witness is refused; this never catches the
    /// witness up, creates a claim, completes a Pending record or signs.
    pub fn recover(file: File, witness: W, binding: Digest32) -> Result<Self, Error> {
        let expected = witness
            .current()?
            .ok_or(Error::Binding("original execution witness missing"))?;
        let sequence = expected
            .sequence
            .checked_sub(1)
            .ok_or(Error::Binding("original execution witness sequence"))?;
        if expected.checkpoint_digest.is_zero() {
            return Err(Error::Binding("original execution witness digest"));
        }
        let journal = LockedFileProductEvaluationExecutionStoreV1::recover(
            file,
            binding,
            ProductEvaluationExecutionAnchorV1 {
                sequence,
                history_digest: expected.checkpoint_digest,
            },
        )?;
        let mut owner = Self {
            journal,
            witness,
            fenced: false,
        };
        if owner.require_current()? != expected {
            return Err(Error::CommitUncertain);
        }
        Ok(owner)
    }
}
