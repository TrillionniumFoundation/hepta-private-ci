//! Opt-in journal for the existing causal ledger; no ambient path or effect access.

use std::error::Error;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;

use crate::AppendDisposition;
use crate::AppendReceipt;
use crate::LearningLedger;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::LedgerSnapshot;
use crate::durable_codec::FRAME_OVERHEAD;
use crate::durable_codec::MAX_EVENT;
use crate::durable_codec::decode_event;
use crate::durable_codec::encode_frame;
use crate::durable_lock::LockedFile;

const MAGIC: &[u8; 8] = b"HEPTLR01";
const HEADER: usize = 72;
const MAX_RECORDS: usize = 8192;
const MAX_BYTES: u64 = 8 * 1024 * 1024;

/// A separately retained, authenticated minimum acknowledged history witness.
/// The host binds it to this store, scope and purpose; never derive it from the
/// suspect journal itself or discard it to retry unanchored recovery.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LedgerAnchor {
    pub sequence: u64,
    pub chain_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LedgerRecovery {
    Unacknowledged,
    Acknowledged(LedgerAnchor),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DurableLedgerError {
    InvalidBinding,
    InvalidLimit,
    InvalidAnchor,
    Busy,
    NotRegular,
    AlreadyInitialized,
    MissingHeader,
    BindingMismatch,
    AcknowledgedHistoryMissing,
    AnchorMismatch,
    IncompleteTail,
    UnwitnessedTail,
    Corrupt,
    Conflict,
    Capacity,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
    Semantic(LedgerError),
}

impl fmt::Display for DurableLedgerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl Error for DurableLedgerError {}
impl From<io::Error> for DurableLedgerError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

/// One exclusively owned local file. The host authorizes the file and binding,
/// authenticates record identities and observations, and enforces revocation.
/// Locks fence cooperating independent handles, not hostile or privileged writers.
/// Passing cloned/inherited handles already locked elsewhere is unsupported.
/// No mutable core escapes; memory advances only after the same event is synced.
pub struct DurableLedger {
    file: LockedFile,
    core: LearningLedger,
    max_records: usize,
    durable_length: u64,
    poisoned: bool,
}

impl DurableLedger {
    /// Create an empty store explicitly. Never use this to replace lost history.
    /// File creation and containing-directory durability are owned by the host.
    pub fn create(
        file: File,
        binding: Digest32,
        max_records: usize,
    ) -> Result<Self, DurableLedgerError> {
        validate_domain(binding, max_records)?;
        let mut file = LockedFile::acquire(file)?;
        if file.metadata()?.len() != 0 {
            return Err(DurableLedgerError::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        let digest = Digest32::of_bytes(&header);
        header.extend_from_slice(digest.as_array());
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        Ok(Self {
            file,
            core: LearningLedger::new(),
            max_records,
            durable_length: HEADER as u64,
            poisoned: false,
        })
    }

    /// Replay complete canonical frames. Validate any external acknowledgement
    /// before repairing an incomplete final frame. Full corruption never repairs.
    /// All recovered data is synced before it becomes an exposed committed result.
    pub fn recover(
        file: File,
        binding: Digest32,
        max_records: usize,
        recovery: LedgerRecovery,
    ) -> Result<Self, DurableLedgerError> {
        validate_domain(binding, max_records)?;
        validate_recovery(recovery, max_records)?;
        let mut file = LockedFile::acquire(file)?;
        let (core, cursor, length) = replay_frames(&mut file, binding, max_records, recovery)?;
        if cursor != length {
            file.set_len(cursor)
                .map_err(|_| DurableLedgerError::Indeterminate)?;
        }
        file.sync_all()
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        Ok(Self {
            file,
            core,
            max_records,
            durable_length: cursor,
            poisoned: false,
        })
    }

    /// Validate without changing memory, compare the exact predecessor, append
    /// and sync, then publish the core event. Equal canonical retries never append.
    /// An I/O uncertainty poisons this handle: recover and reconcile before retry.
    pub fn append(
        &mut self,
        expected_predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        if self.poisoned {
            return Err(DurableLedgerError::Poisoned);
        }
        let prepared = self
            .core
            .prepare(event)
            .map_err(DurableLedgerError::Semantic)?;
        if prepared.record.predecessor_chain_digest != expected_predecessor {
            return Err(DurableLedgerError::Conflict);
        }
        if prepared.disposition == AppendDisposition::IdempotentReplay {
            return self
                .core
                .apply(prepared)
                .map_err(DurableLedgerError::Semantic);
        }
        if self.core.records().len() >= self.max_records {
            return Err(DurableLedgerError::Capacity);
        }
        let frame = encode_frame(&prepared.record)?;
        let next_length = self.durable_length + frame.len() as u64;
        if next_length > MAX_BYTES {
            return Err(DurableLedgerError::Capacity);
        }
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.durable_length {
            return Err(DurableLedgerError::Corrupt);
        }
        self.file
            .write_all(&frame)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        let receipt = self
            .core
            .apply(prepared)
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        self.durable_length = next_length;
        self.poisoned = false;
        Ok(receipt)
    }

    pub fn records(&self) -> Result<&[LedgerRecord], DurableLedgerError> {
        if self.poisoned {
            Err(DurableLedgerError::Poisoned)
        } else {
            Ok(self.core.records())
        }
    }

    /// Causal exclusion only: revoked bytes still exist in the audit journal.
    /// This is not proof of physical erasure or removal from derived artifacts.
    pub fn active_records(&self) -> Result<Vec<&LedgerRecord>, DurableLedgerError> {
        if self.poisoned {
            Err(DurableLedgerError::Poisoned)
        } else {
            Ok(self.core.active_records())
        }
    }

    pub fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError> {
        if self.poisoned {
            Err(DurableLedgerError::Poisoned)
        } else {
            Ok(self.core.snapshot())
        }
    }
}

/// Inspect a closed, fully witnessed segment through a host-authorized read-only
/// file. Uses the writer's parser but never writes, syncs, repairs or initializes.
/// The host must authenticate the binding and obtain the CURRENT external anchor.
/// Unlike writer recovery, inspection requires that anchor to match the entire
/// complete log. A later complete suffix requires a new witness, never a silent
/// old-prefix view. An incomplete suffix requires owner recovery, never reader repair.
/// The returned snapshot is historical, not ongoing revocation or use authority.
/// Independently open the file; already locked aliases are unsupported.
pub fn inspect_ledger(
    file: File,
    binding: Digest32,
    max_records: usize,
    anchor: LedgerAnchor,
) -> Result<LedgerSnapshot, DurableLedgerError> {
    validate_domain(binding, max_records)?;
    let recovery = LedgerRecovery::Acknowledged(anchor);
    validate_recovery(recovery, max_records)?;
    if !file.metadata()?.is_file() {
        return Err(DurableLedgerError::NotRegular);
    }
    match file.try_lock_shared() {
        Ok(()) => (),
        Err(TryLockError::WouldBlock) => return Err(DurableLedgerError::Busy),
        Err(TryLockError::Error(error)) => return Err(error.into()),
    }
    // Construct only AFTER acquisition, so a failed lock never unlocks an owner.
    let mut guard = InspectionLock(file);
    let (core, cursor, length) = replay_frames(&mut guard.0, binding, max_records, recovery)?;
    if cursor != length {
        return Err(DurableLedgerError::IncompleteTail);
    }
    if core.records().len() as u64 != anchor.sequence {
        return Err(DurableLedgerError::UnwitnessedTail);
    }
    Ok(core.snapshot())
}

struct InspectionLock(File);

impl Drop for InspectionLock {
    fn drop(&mut self) {
        // Do not let a transient inherited open description retain our shared
        // lock after success or rejection. File closure remains the fallback.
        let _ = self.0.unlock();
    }
}

fn replay_frames(
    file: &mut File,
    binding: Digest32,
    max_records: usize,
    recovery: LedgerRecovery,
) -> Result<(LearningLedger, u64, u64), DurableLedgerError> {
    let length = file.metadata()?.len();
    if length < HEADER as u64 {
        return Err(DurableLedgerError::MissingHeader);
    }
    if length > MAX_BYTES {
        return Err(DurableLedgerError::Capacity);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut header = [0; HEADER];
    file.read_exact(&mut header)?;
    if &header[..8] != MAGIC || Digest32::of_bytes(&header[..40]).as_array() != &header[40..] {
        return Err(DurableLedgerError::Corrupt);
    }
    if &header[8..40] != binding.as_array() {
        return Err(DurableLedgerError::BindingMismatch);
    }
    let mut core = LearningLedger::new();
    let mut cursor = HEADER as u64;
    while cursor < length {
        if length - cursor < 8 {
            break;
        }
        let mut prefix = [0; 8];
        file.read_exact(&mut prefix)?;
        let size = u32::from_be_bytes(
            prefix[..4]
                .try_into()
                .map_err(|_| DurableLedgerError::Corrupt)?,
        );
        let complement = u32::from_be_bytes(
            prefix[4..]
                .try_into()
                .map_err(|_| DurableLedgerError::Corrupt)?,
        );
        if size != !complement || size == 0 || size as usize > MAX_EVENT {
            return Err(DurableLedgerError::Corrupt);
        }
        let total = size as usize + FRAME_OVERHEAD;
        if length - cursor < total as u64 {
            break;
        }
        if core.records().len() >= max_records {
            return Err(DurableLedgerError::Capacity);
        }
        let mut frame = vec![0; total];
        frame[..8].copy_from_slice(&prefix);
        file.read_exact(&mut frame[8..])?;
        if Digest32::of_bytes(&frame[..total - 32]).as_array() != &frame[total - 32..] {
            return Err(DurableLedgerError::Corrupt);
        }
        let event = decode_event(&frame[48..48 + size as usize])?;
        let prepared = core
            .prepare(event)
            .map_err(|_| DurableLedgerError::Corrupt)?;
        if prepared.disposition != AppendDisposition::Appended
            || encode_frame(&prepared.record)? != frame
        {
            return Err(DurableLedgerError::Corrupt);
        }
        core.apply(prepared)
            .map_err(|_| DurableLedgerError::Corrupt)?;
        cursor += total as u64;
    }
    if let LedgerRecovery::Acknowledged(anchor) = recovery {
        let record = core
            .records()
            .get((anchor.sequence - 1) as usize)
            .ok_or(DurableLedgerError::AcknowledgedHistoryMissing)?;
        if record.chain_digest != anchor.chain_digest {
            return Err(DurableLedgerError::AnchorMismatch);
        }
    }
    Ok((core, cursor, length))
}

fn validate_recovery(
    recovery: LedgerRecovery,
    max_records: usize,
) -> Result<(), DurableLedgerError> {
    if let LedgerRecovery::Acknowledged(anchor) = recovery
        && (anchor.sequence == 0
            || anchor.sequence > max_records as u64
            || anchor.chain_digest.is_zero())
    {
        return Err(DurableLedgerError::InvalidAnchor);
    }
    Ok(())
}

fn validate_domain(binding: Digest32, max_records: usize) -> Result<(), DurableLedgerError> {
    if binding.is_zero() {
        return Err(DurableLedgerError::InvalidBinding);
    }
    if !(1..=MAX_RECORDS).contains(&max_records) {
        return Err(DurableLedgerError::InvalidLimit);
    }
    Ok(())
}

#[cfg(test)]
#[path = "durable_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "inspection_tests.rs"]
mod inspection_tests;
