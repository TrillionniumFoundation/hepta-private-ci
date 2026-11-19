//! Read-only publication metadata from the active, exclusively owned journal.

use super::DurableRunStartJournal;
use super::RunStartAnchor;
use super::RunStartRecovery;
use super::RunStartStoreError;
use super::validate_recovery;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartPublication {
    pub sequence: u64,
    pub record_digest: Digest32,
    pub chain_digest: Digest32,
}

impl DurableRunStartJournal {
    /// Read already-published metadata without append, recovery or file I/O.
    /// Absence is not proof that a request was never durably admitted.
    pub fn publication(
        &self,
        run_id: &StableId,
    ) -> Result<Option<RunStartPublication>, RunStartStoreError> {
        if self.poisoned {
            return Err(RunStartStoreError::Poisoned);
        }
        Ok(self.by_run.get(run_id).map(|index| {
            let stored = &self.records[*index];
            RunStartPublication {
                sequence: stored.sequence,
                record_digest: stored.record_digest,
                chain_digest: stored.chain_digest,
            }
        }))
    }

    /// Verify a caller-retained acknowledgement against the current in-memory
    /// prefix. This never repairs a file or grants access to its contents.
    pub fn verify_anchor(&self, anchor: RunStartAnchor) -> Result<(), RunStartStoreError> {
        if self.poisoned {
            return Err(RunStartStoreError::Poisoned);
        }
        validate_recovery(RunStartRecovery::Acknowledged(anchor), self.max_records)?;
        let stored = self
            .records
            .get((anchor.sequence - 1) as usize)
            .ok_or(RunStartStoreError::AcknowledgedHistoryMissing)?;
        if stored.chain_digest != anchor.chain_digest {
            return Err(RunStartStoreError::AnchorMismatch);
        }
        Ok(())
    }
}
