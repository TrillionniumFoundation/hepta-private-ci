//! Data-only physical read of an original guarded Cell journal and witness.
//! Both writer locks must be released. This decoder is not a CURRENT guard,
//! historical recipient grant, or durable refusal owner.

use std::fs::OpenOptions;
use std::os::fd::AsRawFd;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;

use super::*;
use crate::JournalScope;
use crate::observe_original_file_anchor_v1;
use codex_hepta_types::Generation;

pub struct CellOriginalJournalFilesV1 {
    pub journal: File,
    pub witness: File,
    pub witness_scope: JournalScope,
    pub witness_generation: Generation,
    pub witness_records: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellOriginalJournalObservationV1 {
    pub anchor: JournalAnchor,
    pub snapshot: CellOwnerSnapshotV1,
    pub decision: CellDecisionReceiptV1,
}

/// Decode only the complete, independently witnessed original physical cut.
/// The caller must compare this data to its independently retained Root cut;
/// this stateless observer cannot remember a failure across separate calls.
pub fn observe_original_guarded_cell_v1(
    files: CellOriginalJournalFilesV1,
    partition: CellJournalPartitionV1,
    max_records: usize,
    binding: &CellGenerationOwnerBindingV1,
    operation_id: &StableId,
    semantic_request_digest: Digest32,
) -> Result<CellOriginalJournalObservationV1, CellExecutionError> {
    let scope = binding.scope();
    if !(1..=65_536).contains(&max_records)
        || semantic_request_digest.is_zero()
        || partition.scope.agent_id.as_str() != scope.agent_id
        || partition.scope.cell_id.as_str() != scope.cell_id
        || partition.scope.run_id.as_str() != scope.run_id
        || partition.scope.principal_digest.into_array() != scope.principal_digest
        || partition.source_frontier.into_array() != binding.source_frontier()
        || partition.writer_epoch != binding.writer_epoch()
    {
        return Err(CellExecutionError::ScopeMismatch);
    }
    let specs = [partition];
    let ordinary_header = header(&specs)?;
    let digest = Digest32::of_parts(&[
        b"hepta.cell.published-feature-journal.v1\0",
        &ordinary_header,
        &binding
            .digest()
            .map_err(|_| CellExecutionError::ScopeMismatch)?,
        &(max_records as u64).to_be_bytes(),
    ]);
    let mut header = b"HPTACJ04".to_vec();
    header.extend_from_slice(digest.as_array());
    let (journal, journal_identity) = original_readonly(&files.journal)?;
    let (witness, witness_identity) = original_readonly(&files.witness)?;
    if (journal_identity.device, journal_identity.inode)
        == (witness_identity.device, witness_identity.inode)
    {
        return Err(CellExecutionError::ScopeMismatch);
    }
    let read_witness = || {
        observe_original_file_anchor_v1(
            &witness,
            files.witness_scope,
            files.witness_generation,
            files.witness_records,
        )
        .map_err(|_| CellExecutionError::AcknowledgedHistoryMissing)
    };
    let expected = read_witness()?;
    let bytes = original_image(&journal)?;
    if read_witness()? != expected
        || original_image(&journal)? != bytes
        || read_witness()? != expected
        || original_image(&journal)? != bytes
        || FileIdentity::read(&journal)? != journal_identity
        || FileIdentity::read(&witness)? != witness_identity
    {
        return Err(CellExecutionError::CommitUncertain);
    }
    let parsed = image::parse_original_cell_image(&bytes, &header, &specs, max_records, expected)?;
    if !parsed.witnessed
        || parsed.head.is_none()
        || parsed.head != expected
        || parsed.offset != bytes.len()
    {
        return Err(CellExecutionError::AcknowledgedHistoryMissing);
    }
    let scope = &specs[0].scope;
    if parsed.owner.pending_inference(scope)?.is_some() {
        return Err(CellExecutionError::InferencePending);
    }
    let decision = parsed
        .owner
        .lookup(scope, operation_id, semantic_request_digest)?
        .ok_or(CellExecutionError::AcknowledgedHistoryMissing)?;
    let snapshot = parsed.owner.snapshot(scope)?;
    if FileIdentity::read(&journal)? != journal_identity
        || FileIdentity::read(&witness)? != witness_identity
        || read_witness()? != expected
        || original_image(&journal)? != bytes
    {
        return Err(CellExecutionError::CommitUncertain);
    }
    Ok(CellOriginalJournalObservationV1 {
        anchor: parsed
            .head
            .ok_or(CellExecutionError::AcknowledgedHistoryMissing)?,
        snapshot,
        decision,
    })
}

#[derive(Clone, Eq, PartialEq)]
struct FileIdentity {
    device: u64,
    inode: u64,
    length: u64,
    links: u64,
    uid: u32,
    gid: u32,
    mode: u32,
    modified: (i64, i64),
    changed: (i64, i64),
}

impl FileIdentity {
    fn read(file: &File) -> Result<Self, CellExecutionError> {
        let m = file
            .metadata()
            .map_err(|_| CellExecutionError::OwnerUnavailable)?;
        if !m.is_file() || m.nlink() != 1 {
            return Err(CellExecutionError::OwnerUnavailable);
        }
        Ok(Self {
            device: m.dev(),
            inode: m.ino(),
            length: m.len(),
            links: m.nlink(),
            uid: m.uid(),
            gid: m.gid(),
            mode: m.mode(),
            modified: (m.mtime(), m.mtime_nsec()),
            changed: (m.ctime(), m.ctime_nsec()),
        })
    }
}

fn original_readonly(file: &File) -> Result<(LockedFile, FileIdentity), CellExecutionError> {
    let original = FileIdentity::read(file)?;
    let descriptor = file.as_raw_fd();
    let readonly = OpenOptions::new()
        .read(true)
        .open(format!("/proc/self/fd/{descriptor}"))
        .map_err(|_| CellExecutionError::OwnerUnavailable)?;
    if FileIdentity::read(&readonly)? != original {
        return Err(CellExecutionError::OwnerUnavailable);
    }
    let locked = LockedFile::acquire(readonly).map_err(|_| CellExecutionError::OwnerUnavailable)?;
    if FileIdentity::read(&locked)? != original {
        return Err(CellExecutionError::OwnerUnavailable);
    }
    Ok((locked, original))
}

fn original_image(file: &File) -> Result<Vec<u8>, CellExecutionError> {
    let length = file
        .metadata()
        .map_err(|_| CellExecutionError::OwnerUnavailable)?
        .len();
    if !(HEADER_BYTES as u64..=MAX_JOURNAL_BYTES).contains(&length) {
        return Err(CellExecutionError::JournalCorrupt);
    }
    let mut bytes = vec![0; length as usize];
    file.read_exact_at(&mut bytes, 0)
        .map_err(|_| CellExecutionError::OwnerUnavailable)?;
    Ok(bytes)
}
