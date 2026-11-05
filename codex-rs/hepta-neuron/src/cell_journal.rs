//! One host-owned journal for many independently scoped Cell state partitions.
//! The host supplies an exclusive regular file and an independent durable
//! AnchorWitnessStore. Frames bind policy receipts and sparse ticks; recovery
//! recomputes checkpoints without executing a model. No effect rights.

use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AnchorWitnessStore;
use crate::JournalAnchor;
use crate::cell_journal_codec::MAX_FRAME_BYTES;
use crate::cell_journal_codec::apply_record;
use crate::cell_journal_codec::encode_commit;
use crate::cell_journal_codec::encode_admission;
use crate::cell_journal_codec::encode_reset;
use crate::cell_owner::CellPartitionOwnerV1;
use crate::cell_types::*;
use crate::journal_lock::LockedFile;

const MAGIC: &[u8; 8] = b"HPTACJ02";
const HEADER_BYTES: usize = 40;
const MAX_JOURNAL_BYTES: u64 = 64 * 1024 * 1024;

/// Frozen admission table: recovery requires the same definitions, source
/// frontiers and initial writer epochs. Changing this table requires host-owned
/// lifecycle transfer and journal replacement; this type does not migrate it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellJournalPartitionV1 {
    pub scope: CellScopeV1,
    pub definition: CellDefinitionV1,
    pub source_frontier: Digest32,
    pub writer_epoch: u64,
}

pub struct CellOwnerJournalV1<W: AnchorWitnessStore> {
    file: LockedFile,
    witness: W,
    specs: Vec<CellJournalPartitionV1>,
    owner: CellPartitionOwnerV1,
    header: Vec<u8>,
    head: Option<JournalAnchor>,
    max_records: usize,
    length: u64,
    healthy: bool,
}

impl<W: AnchorWitnessStore> CellOwnerJournalV1<W> {
    pub fn open(
        file: File,
        witness: W,
        specs: Vec<CellJournalPartitionV1>,
        max_records: usize,
    ) -> Result<Self, CellExecutionError> {
        if specs.is_empty() || specs.len() > 1024 || !(1..=65_536).contains(&max_records) {
            return Err(CellExecutionError::CapacityExceeded);
        }
        let owner = initial_owner(&specs)?;
        let header = header(&specs)?;
        let mut file = LockedFile::acquire(file).map_err(|_| CellExecutionError::OwnerUnavailable)?;
        if file.metadata().map_err(|_| CellExecutionError::OwnerUnavailable)?.len() == 0 {
            if witness.current().map_err(|_| CellExecutionError::OwnerUnavailable)?.is_some() {
                return Err(CellExecutionError::AcknowledgedHistoryMissing);
            }
            file.seek(SeekFrom::Start(0)).map_err(|_| CellExecutionError::OwnerUnavailable)?;
            file.write_all(&header).map_err(|_| CellExecutionError::CommitUncertain)?;
            file.sync_all().map_err(|_| CellExecutionError::CommitUncertain)?;
        }
        let mut journal = Self {
            file, witness, specs, owner, header, head: None,
            max_records, length: 0, healthy: false,
        };
        journal.recover()?;
        Ok(journal)
    }

    /// Read back the original log after an uncertain write. Only an incomplete
    /// tail is trimmed, after proving all witnessed history still exists. A
    /// complete lost-ack frame is retained and witnessed before lookup returns
    /// its exact receipt. No encoding or inference is repeated.
    pub fn recover(&mut self) -> Result<(), CellExecutionError> {
        self.healthy = false;
        let expected = self.witness.current().map_err(|_| CellExecutionError::OwnerUnavailable)?;
        let length = self.file.metadata().map_err(|_| CellExecutionError::OwnerUnavailable)?.len();
        if length < HEADER_BYTES as u64 || length > MAX_JOURNAL_BYTES {
            return Err(CellExecutionError::JournalCorrupt);
        }
        self.file.seek(SeekFrom::Start(0)).map_err(|_| CellExecutionError::OwnerUnavailable)?;
        let mut bytes = vec![0; length as usize];
        self.file.read_exact(&mut bytes).map_err(|_| CellExecutionError::OwnerUnavailable)?;
        if bytes[..HEADER_BYTES] != self.header {
            return Err(CellExecutionError::JournalCorrupt);
        }
        let mut owner = initial_owner(&self.specs)?;
        let mut offset = HEADER_BYTES;
        let mut head = None;
        let mut count = 0;
        let mut witnessed = expected.is_none();
        while offset < bytes.len() {
            if bytes.len() - offset < 4 {
                break;
            }
            let size = u32::from_be_bytes(bytes[offset..offset + 4].try_into()
                .map_err(|_| CellExecutionError::JournalCorrupt)?) as usize;
            if size == 0 || size > MAX_FRAME_BYTES {
                return Err(CellExecutionError::JournalCorrupt);
            }
            let end = offset.checked_add(4 + size + 32).ok_or(CellExecutionError::JournalCorrupt)?;
            if end > bytes.len() {
                break;
            }
            count += 1;
            if count > self.max_records {
                return Err(CellExecutionError::CapacityExceeded);
            }
            let payload = &bytes[offset + 4..end - 32];
            let anchor = next_anchor(&self.header, head, payload)?;
            if anchor.checkpoint_digest.as_array() != &bytes[end - 32..end] {
                return Err(CellExecutionError::JournalCorrupt);
            }
            apply_record(payload, &self.specs, &mut owner)?;
            if expected == Some(anchor) {
                witnessed = true;
            }
            head = Some(anchor);
            offset = end;
        }
        if !witnessed {
            return Err(CellExecutionError::AcknowledgedHistoryMissing);
        }
        // Validate the independent anchor before any file repair.
        if offset < bytes.len() {
            self.file.set_len(offset as u64).map_err(|_| CellExecutionError::CommitUncertain)?;
        }
        self.file.sync_all().map_err(|_| CellExecutionError::CommitUncertain)?;
        if let Some(next) = head
            && expected != Some(next)
        {
            self.witness.compare_and_swap(expected, next)
                .map_err(|_| CellExecutionError::CommitUncertain)?;
        }
        self.owner = owner;
        self.head = head;
        self.length = offset as u64;
        self.healthy = true;
        Ok(())
    }

    /// Persist source invalidation and a new writer fence in the shared journal.
    /// Temporal state resets explicitly; already prepared commits fail CAS.
    pub fn reset_at_frontier(
        &mut self,
        scope: &CellScopeV1,
        source_frontier: Digest32,
        writer_epoch: u64,
    ) -> Result<(), CellExecutionError> {
        self.require_healthy()?;
        let index = self.partition_index(scope)?;
        self.owner.check_reset(scope, source_frontier, writer_epoch)?;
        let payload = encode_reset(index, source_frontier, writer_epoch);
        self.check_reserved_capacity(payload.len(), self.owner.pending_count())?;
        self.persist(payload)?;
        if let Err(error) = self.owner.reset_at_frontier(scope, source_frontier, writer_epoch) {
            self.healthy = false;
            return Err(error);
        }
        Ok(())
    }

    fn partition_index(&self, scope: &CellScopeV1) -> Result<usize, CellExecutionError> {
        self.specs.iter().position(|s| &s.scope == scope).ok_or(CellExecutionError::ScopeMismatch)
    }

    fn require_healthy(&self) -> Result<(), CellExecutionError> {
        if self.healthy { Ok(()) } else { Err(CellExecutionError::CommitUncertain) }
    }

    fn check_reserved_capacity(&self, payload_bytes: usize, remaining_pending: usize) -> Result<(), CellExecutionError> {
        let reserved_records = remaining_pending as u64;
        let sequence = self.head.map_or(0, |a| a.sequence);
        let reserved_bytes = reserved_records * (MAX_FRAME_BYTES as u64 + 36);
        if sequence + 1 + reserved_records > self.max_records as u64
            || self.length + payload_bytes as u64 + 36 + reserved_bytes > MAX_JOURNAL_BYTES
        {
            return Err(CellExecutionError::CapacityExceeded);
        }
        Ok(())
    }

    fn persist(&mut self, payload: Vec<u8>) -> Result<(), CellExecutionError> {
        self.require_healthy()?;
        let next = next_anchor(&self.header, self.head, &payload)?;
        if next.sequence > self.max_records as u64
            || payload.len() > MAX_FRAME_BYTES
            || self.length + payload.len() as u64 + 36 > MAX_JOURNAL_BYTES
        {
            return Err(CellExecutionError::CapacityExceeded);
        }
        let mut frame = Vec::with_capacity(payload.len() + 36);
        frame.extend_from_slice(&(payload.len() as u32).to_be_bytes());
        frame.extend_from_slice(&payload);
        frame.extend_from_slice(next.checkpoint_digest.as_array());
        self.healthy = false;
        if self.file.metadata().map_err(|_| CellExecutionError::CommitUncertain)?.len() != self.length {
            return Err(CellExecutionError::CommitUncertain);
        }
        self.file.seek(SeekFrom::Start(self.length)).map_err(|_| CellExecutionError::CommitUncertain)?;
        self.file.write_all(&frame).map_err(|_| CellExecutionError::CommitUncertain)?;
        self.file.sync_all().map_err(|_| CellExecutionError::CommitUncertain)?;
        self.witness.compare_and_swap(self.head, next).map_err(|_| CellExecutionError::CommitUncertain)?;
        self.head = Some(next);
        self.length += frame.len() as u64;
        self.healthy = true;
        Ok(())
    }
}

impl<W: AnchorWitnessStore> CellStateOwnerV1 for CellOwnerJournalV1<W> {
    fn admit_inference(&mut self, admission: CellInferenceAdmissionV1) -> Result<(), CellExecutionError> {
        self.require_healthy()?;
        let index = self.partition_index(&admission.snapshot.scope)?;
        self.owner.check_admission(&admission)?;
        let payload = encode_admission(index, &admission);
        self.check_reserved_capacity(payload.len(), self.owner.pending_count() + 1)?;
        self.persist(payload)?;
        if let Err(error) = self.owner.admit_inference(admission) {
            self.healthy = false;
            return Err(error);
        }
        Ok(())
    }

    fn pending_inference(&self, scope: &CellScopeV1) -> Result<Option<CellInferenceAdmissionV1>, CellExecutionError> {
        self.require_healthy()?;
        self.owner.pending_inference(scope)
    }

    fn snapshot(&self, scope: &CellScopeV1) -> Result<CellOwnerSnapshotV1, CellExecutionError> {
        self.require_healthy()?;
        self.owner.snapshot(scope)
    }

    fn lookup(
        &self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        semantic_request_digest: Digest32,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError> {
        self.require_healthy()?;
        self.owner.lookup(scope, operation_id, semantic_request_digest)
    }

    fn reconcile(
        &self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        operation_digest: Digest32,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError> {
        self.require_healthy()?;
        self.owner.reconcile(scope, operation_id, operation_digest)
    }

    fn commit(
        &mut self,
        proposal: CellStateProposalV1,
        now_micros: u64,
    ) -> Result<CellDecisionReceiptV1, CellExecutionError> {
        self.require_healthy()?;
        let index = self.partition_index(&proposal.snapshot.scope)?;
        if let Some(receipt) = self.owner.check_commit(&proposal, now_micros)? {
            return Ok(receipt);
        }
        let proposal = proposal.settle_at(now_micros)?;
        let payload = encode_commit(index, &proposal);
        self.persist(payload)?;
        // Exclusive mutable ownership preserves the validated CAS while file
        // and witness are written; only the target partition is then updated.
        match self.owner.commit(proposal, now_micros) {
            Ok(receipt) => Ok(receipt),
            Err(error) => {
                self.healthy = false;
                Err(error)
            }
        }
    }
}

fn initial_owner(specs: &[CellJournalPartitionV1]) -> Result<CellPartitionOwnerV1, CellExecutionError> {
    let mut owner = CellPartitionOwnerV1::new(specs.len(), /*max_receipts_per_partition*/4096)?;
    for spec in specs {
        owner.admit(spec.scope.clone(), &spec.definition, spec.source_frontier, spec.writer_epoch)?;
    }
    Ok(owner)
}

fn header(specs: &[CellJournalPartitionV1]) -> Result<Vec<u8>, CellExecutionError> {
    let mut table = b"hepta.cell.journal.admission.v1".to_vec();
    table.extend_from_slice(&(specs.len() as u64).to_be_bytes());
    for spec in specs {
        for digest in [spec.scope.digest(), spec.definition.semantic_digest()?, spec.source_frontier] {
            table.extend_from_slice(digest.as_array());
        }
        table.extend_from_slice(&spec.writer_epoch.to_be_bytes());
    }
    let mut bytes = MAGIC.to_vec();
    bytes.extend_from_slice(Digest32::of_bytes(&table).as_array());
    Ok(bytes)
}

fn next_anchor(
    header: &[u8],
    previous: Option<JournalAnchor>,
    payload: &[u8],
) -> Result<JournalAnchor, CellExecutionError> {
    let sequence = previous.map_or(0, |a| a.sequence).checked_add(1)
        .ok_or(CellExecutionError::CapacityExceeded)?;
    let mut bytes = b"hepta.cell.journal.frame.v1".to_vec();
    bytes.extend_from_slice(previous.map_or_else(
        || Digest32::of_bytes(header), |a| a.checkpoint_digest,
    ).as_array());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(&(payload.len() as u64).to_be_bytes());
    bytes.extend_from_slice(payload);
    Ok(JournalAnchor { sequence, checkpoint_digest: Digest32::of_bytes(&bytes) })
}

#[cfg(test)]
#[path = "cell_journal_tests.rs"]
mod tests;
