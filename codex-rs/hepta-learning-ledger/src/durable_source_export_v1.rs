//! Exact bounded original bytes from the same held owner, without a new codec.
use super::*;
use std::io::Cursor;
use std::os::unix::fs::FileExt;

pub const MAX_LEDGER_CANONICAL_SOURCE_BYTES_V1: usize = MAX_BYTES as usize;

/// Original HEPTLR01 source bytes and owner limits. This supplies no independent
/// acknowledgement: a consumer must authenticate the CURRENT external witness
/// and use the existing closed-source inspector before treating history as fact.
pub struct LedgerCanonicalSourceV1 {
    bytes: Vec<u8>,
    binding: Digest32,
    maximum_records: usize,
}

impl LedgerCanonicalSourceV1 {
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
    #[must_use]
    pub const fn binding(&self) -> Digest32 {
        self.binding
    }
    #[must_use]
    pub const fn maximum_records(&self) -> usize {
        self.maximum_records
    }
}

impl DurableLedger {
    /// Copy the complete original store while retaining its sole acquired FD.
    /// Positioned reads preserve the writer's offset and lock. The original
    /// parser revalidates the full bytes against the same in-memory history;
    /// foreign tails, corruption, poison or changing metadata fail closed.
    /// No file is opened, repaired, synchronized, appended or acknowledged.
    pub fn export_canonical_source_v1(
        &self,
    ) -> Result<LedgerCanonicalSourceV1, DurableLedgerError> {
        let snapshot = self.snapshot()?;
        let before = self.file.metadata()?;
        if before.len() != self.durable_length {
            return Err(DurableLedgerError::Conflict);
        }
        if before.len() > MAX_BYTES {
            return Err(DurableLedgerError::Capacity);
        }
        let mut bytes = vec![0; before.len() as usize];
        self.file.read_exact_at(&mut bytes, /*offset*/ 0)?;
        // Unacknowledged here means only that this private parser is checking
        // the already held owner's bytes. This does not issue an external ACK.
        let (core, cursor, length) = replay_reader(
            &mut Cursor::new(&bytes),
            bytes.len() as u64,
            self.binding,
            self.max_records,
            LedgerRecovery::Unacknowledged,
        )?;
        let after = self.file.metadata()?;
        if cursor != length
            || length != self.durable_length
            || core.snapshot() != snapshot
            || self.snapshot()? != snapshot
            || before.len() != after.len()
            || before.modified()? != after.modified()?
        {
            return Err(DurableLedgerError::Conflict);
        }
        Ok(LedgerCanonicalSourceV1 {
            bytes,
            binding: self.binding,
            maximum_records: self.max_records,
        })
    }
}
