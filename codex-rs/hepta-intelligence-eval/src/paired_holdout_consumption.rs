//! Read the original CAS through its held descriptor, never through a second
//! writer. The descriptor retains the original physical lock until it closes.
use super::*;
use crate::CrossFoldPlanReceiptV1;
use crate::FinalHoldoutJournalReceiptV1;
use crate::HoldoutUseDispositionV1;
use codex_hepta_learning_ledger::open_root_review_input;
use codex_hepta_types::AuthorityPosture;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

pub(crate) struct HeldPairedConsumptionV1 {
    file: File,
    binding: Digest32,
    minimum: Option<FinalHoldoutCasAnchorV1>,
}

impl LockedFileFinalHoldoutCasStoreV1 {
    pub(crate) fn paired_consumption_reader(
        &self,
        original_path: &Path,
        expected_binding: Digest32,
        minimum: FinalHoldoutCasAnchorV1,
    ) -> Result<HeldPairedConsumptionV1, LockedFileCasErrorV1> {
        if self.poisoned || self.binding != expected_binding {
            return Err(LockedFileCasErrorV1::Indeterminate);
        }
        let protected =
            open_root_review_input(original_path).map_err(|_| LockedFileCasErrorV1::Binding)?;
        let supplied = protected.metadata().map_err(io_error)?;
        let held = self.file.metadata().map_err(io_error)?;
        if supplied.dev() != held.dev()
            || supplied.ino() != held.ino()
            || held.uid() != 0
            || held.mode() & 0o077 != 0
        {
            return Err(LockedFileCasErrorV1::Binding);
        }
        let reader = HeldPairedConsumptionV1 {
            file: self.file.try_clone().map_err(io_error)?,
            binding: self.binding,
            minimum: Some(minimum),
        };
        reader.read_state()?;
        Ok(reader)
    }
}

impl HeldPairedConsumptionV1 {
    pub(crate) fn verify(
        &self,
        plan: &CrossFoldPlanReceiptV1,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<(), LockedFileCasErrorV1> {
        if receipt.disposition != HoldoutUseDispositionV1::Recorded
            || receipt.authority != AuthorityPosture::DENY_ALL
        {
            return Err(LockedFileCasErrorV1::Binding);
        }
        let state = self.read_state()?;
        let record = state
            .journal
            .records
            .last()
            .ok_or(LockedFileCasErrorV1::Binding)?;
        if record.plan != *plan
            || record.sequence != receipt.sequence
            || record.record_digest != receipt.record_digest
            || record.use_receipt != receipt.use_receipt
            || state.journal.head_digest != receipt.head_digest
        {
            return Err(LockedFileCasErrorV1::Binding);
        }
        Ok(())
    }

    fn read_state(&self) -> Result<FinalHoldoutCasRecordV1, LockedFileCasErrorV1> {
        let before = self.file.metadata().map_err(io_error)?;
        if !before.is_file() || before.nlink() != 1 || before.len() > MAX_BYTES {
            return Err(LockedFileCasErrorV1::Corrupt);
        }
        // Positional reads do not move the original writer's shared cursor.
        let mut bytes = vec![0; before.len() as usize];
        self.file.read_exact_at(&mut bytes, 0).map_err(io_error)?;
        let after = self.file.metadata().map_err(io_error)?;
        if before.len() != after.len()
            || before.mtime() != after.mtime()
            || before.mtime_nsec() != after.mtime_nsec()
            || after.nlink() != 1
        {
            return Err(LockedFileCasErrorV1::Indeterminate);
        }
        let (state, _) = decode_locked_state(&bytes, self.binding, self.minimum)?;
        state.ok_or(LockedFileCasErrorV1::Corrupt)
    }
}

#[cfg(test)]
#[path = "paired_holdout_consumption_tests.rs"]
mod tests;
