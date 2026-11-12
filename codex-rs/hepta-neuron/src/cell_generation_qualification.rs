//! Opt-in physical bytes from the sole journal and its original witness.

use super::CellGenerationJournalV2;
use crate::AnchorWitnessStore;
use crate::CellGenerationErrorV2;
use crate::WitnessStoreError;
use crate::qualification_file::FileBytesError;
use crate::qualification_file::file_bytes;

impl<W: AnchorWitnessStore> CellGenerationJournalV2<W> {
    /// Return complete journal and witness bytes while retaining both locks.
    /// The bound applies to each file; unsupported witnesses remain unavailable.
    pub fn qualification_file_bytes(
        &mut self,
        maximum_bytes: u64,
    ) -> Result<[Vec<u8>; 2], CellGenerationErrorV2> {
        self.require_healthy()?;
        let result = (|| {
            let journal = file_bytes(&mut self.file, maximum_bytes).map_err(|error| match error {
                FileBytesError::Capacity => CellGenerationErrorV2::Capacity,
                FileBytesError::Io(_) => CellGenerationErrorV2::CommitUncertain,
            })?;
            let witness = self
                .witness
                .qualification_file_bytes(maximum_bytes)
                .map_err(|error| match error {
                    WitnessStoreError::Capacity => CellGenerationErrorV2::Capacity,
                    WitnessStoreError::Unavailable => CellGenerationErrorV2::Unavailable,
                    _ => CellGenerationErrorV2::CommitUncertain,
                })?;
            self.require_healthy()?;
            Ok([journal, witness])
        })();
        if matches!(result, Err(CellGenerationErrorV2::CommitUncertain)) {
            self.healthy = false;
        }
        result
    }
}
