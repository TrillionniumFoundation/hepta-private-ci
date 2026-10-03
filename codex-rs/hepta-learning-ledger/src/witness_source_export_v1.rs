//! Same independently acquired witness FD, original bytes and original parser.
use super::*;
use std::io::Cursor;
use std::os::unix::fs::FileExt;

impl LedgerWitnessStore {
    /// Export the complete original HEPTLW01 source within the host's explicit
    /// byte budget. Never infer an acknowledgement from the ledger being
    /// protected, open another file, alter the FD offset, advance or repair.
    /// Root must independently authenticate this witness owner's custody and
    /// source pin. The closed original inspector remains the consumer codec.
    pub fn export_canonical_source_v1(
        &self,
        maximum_bytes: usize,
    ) -> Result<Vec<u8>, DurableLedgerError> {
        if maximum_bytes == 0 {
            return Err(DurableLedgerError::InvalidLimit);
        }
        let frontier = self.frontier()?;
        let before = self.file.metadata()?;
        if before.len() != self.length {
            return Err(DurableLedgerError::Conflict);
        }
        let size = usize::try_from(before.len()).map_err(|_| DurableLedgerError::Capacity)?;
        if size > maximum_bytes {
            return Err(DurableLedgerError::Capacity);
        }
        let mut bytes = Vec::new();
        bytes
            .try_reserve_exact(size)
            .map_err(|_| DurableLedgerError::Capacity)?;
        bytes.resize(size, 0);
        self.file.read_exact_at(&mut bytes, /*offset*/ 0)?;
        let (decoded, cursor) =
            read_frontiers_reader(&mut Cursor::new(&bytes), self.binding, bytes.len() as u64)?;
        let after = self.file.metadata()?;
        if decoded != frontier
            || self.frontier()? != frontier
            || cursor != self.length
            || before.len() != after.len()
            || before.modified()? != after.modified()?
        {
            return Err(DurableLedgerError::Conflict);
        }
        Ok(bytes)
    }
}
