//! Crash-durable segmented acknowledgement witness for the V2 Neuron owner.
//!
//! The witness is stored outside `HPTNGS02`. Complete records are monotonic
//! compare-and-swap transitions. A torn final record is truncated on reopen;
//! a complete checksum or predecessor mismatch fails closed.

use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;
use std::path::Path;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::AnchorWitnessStore;
use crate::JournalAnchor;
use crate::JournalScope;
use crate::WitnessStoreError;

const ROOT_MAGIC: &[u8; 8] = b"HPTNWV02";
const SUCCESSOR_MAGIC: &[u8; 8] = b"HPTNWV03";
const SCHEMA_VERSION: u32 = 2;
const HEADER_BYTES: usize = 173;
const RECORD_BYTES: usize = 112;
const MAX_RECORDS: usize = 65_536;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronWitnessContextV2 {
    pub generation: Generation,
    pub scope: JournalScope,
    pub key_epoch: u64,
    pub deletion_epoch: u64,
    pub max_records: usize,
}

impl NeuronWitnessContextV2 {
    fn validate(&self) -> Result<(), WitnessStoreError> {
        if self.scope.scope_digest.is_zero()
            || self.scope.objective_digest.is_zero()
            || self.key_epoch == 0
            || self.deletion_epoch == 0
        {
            return Err(WitnessStoreError::ContextMismatch);
        }
        if !(1..=MAX_RECORDS).contains(&self.max_records) {
            return Err(WitnessStoreError::InvalidLimit);
        }
        Ok(())
    }
}

struct WitnessV2LockedFile(File);

impl WitnessV2LockedFile {
    fn acquire(file: File) -> Result<Self, WitnessStoreError> {
        if !file.metadata()?.is_file() {
            return Err(WitnessStoreError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(WitnessStoreError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}

impl Deref for WitnessV2LockedFile {
    type Target = File;

    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl DerefMut for WitnessV2LockedFile {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}

impl Drop for WitnessV2LockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

pub struct FileNeuronWitnessStoreV2 {
    file: WitnessV2LockedFile,
    context: NeuronWitnessContextV2,
    seed: Option<JournalAnchor>,
    records: usize,
    current: Option<JournalAnchor>,
    poisoned: bool,
}

impl FileNeuronWitnessStoreV2 {
    pub fn create(
        path: &Path,
        context: NeuronWitnessContextV2,
    ) -> Result<Self, WitnessStoreError> {
        Self::create_segment(path, context, None)
    }

    pub fn create_successor(
        path: &Path,
        context: NeuronWitnessContextV2,
        seed: JournalAnchor,
    ) -> Result<Self, WitnessStoreError> {
        Self::create_segment(path, context, Some(seed))
    }

    pub fn open_existing(
        path: &Path,
        context: NeuronWitnessContextV2,
    ) -> Result<Self, WitnessStoreError> {
        Self::open_segment_path(path, context, None)
    }

    pub fn open_successor(
        path: &Path,
        context: NeuronWitnessContextV2,
        seed: JournalAnchor,
    ) -> Result<Self, WitnessStoreError> {
        Self::open_segment_path(path, context, Some(seed))
    }

    pub fn start_successor(
        &self,
        path: &Path,
        context: NeuronWitnessContextV2,
    ) -> Result<Self, WitnessStoreError> {
        self.ensure_healthy()?;
        let seed = self.current.ok_or(WitnessStoreError::InvalidAnchor)?;
        if context.generation != self.context.generation
            || context.scope != self.context.scope
            || context.key_epoch < self.context.key_epoch
            || context.deletion_epoch < self.context.deletion_epoch
        {
            return Err(WitnessStoreError::ContextMismatch);
        }
        context.validate()?;
        Self::create_successor(path, context, seed)
    }

    #[must_use]
    pub fn segment_seed(&self) -> Option<JournalAnchor> {
        self.seed
    }

    #[must_use]
    pub fn key_epoch(&self) -> u64 {
        self.context.key_epoch
    }

    #[must_use]
    pub fn deletion_epoch(&self) -> u64 {
        self.context.deletion_epoch
    }

    pub fn remaining_capacity(&self) -> Result<usize, WitnessStoreError> {
        self.ensure_healthy()?;
        Ok(self.context.max_records.saturating_sub(self.records))
    }

    fn create_segment(
        path: &Path,
        context: NeuronWitnessContextV2,
        seed: Option<JournalAnchor>,
    ) -> Result<Self, WitnessStoreError> {
        context.validate()?;
        validate_seed(seed)?;
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(path)?;
        let mut file = WitnessV2LockedFile::acquire(file)?;
        let header = encode_header(&context, seed);
        file.write_all(&header)
            .map_err(|_| WitnessStoreError::Indeterminate)?;
        file.sync_all()
            .map_err(|_| WitnessStoreError::Indeterminate)?;
        sync_parent_directory(path)?;
        Ok(Self {
            file,
            context,
            seed,
            records: 0,
            current: seed,
            poisoned: false,
        })
    }

    fn open_segment_path(
        path: &Path,
        context: NeuronWitnessContextV2,
        seed: Option<JournalAnchor>,
    ) -> Result<Self, WitnessStoreError> {
        context.validate()?;
        validate_seed(seed)?;
        let file = OpenOptions::new().read(true).write(true).open(path)?;
        let mut file = WitnessV2LockedFile::acquire(file)?;
        let expected_header = encode_header(&context, seed);
        let length = file.metadata()?.len();
        if length < HEADER_BYTES as u64 {
            return Err(WitnessStoreError::Corrupt);
        }
        file.seek(SeekFrom::Start(0))?;
        let mut actual_header = [0_u8; HEADER_BYTES];
        file.read_exact(&mut actual_header)?;
        if actual_header != expected_header {
            return Err(WitnessStoreError::ContextMismatch);
        }

        let available = length - HEADER_BYTES as u64;
        let complete = usize::try_from(available / RECORD_BYTES as u64)
            .map_err(|_| WitnessStoreError::Capacity)?;
        if complete > context.max_records {
            return Err(WitnessStoreError::Capacity);
        }
        let stable_length = HEADER_BYTES as u64
            + u64::try_from(complete)
                .map_err(|_| WitnessStoreError::Capacity)?
                .checked_mul(RECORD_BYTES as u64)
                .ok_or(WitnessStoreError::Capacity)?;
        let mut current = seed;
        let mut record = [0_u8; RECORD_BYTES];
        for _ in 0..complete {
            file.read_exact(&mut record)?;
            let (expected, next) = decode_record(&record)?;
            if expected != current || !is_successor(expected, next) {
                return Err(WitnessStoreError::Corrupt);
            }
            current = Some(next);
        }
        if stable_length != length {
            file.set_len(stable_length)
                .map_err(|_| WitnessStoreError::Indeterminate)?;
            file.sync_all()
                .map_err(|_| WitnessStoreError::Indeterminate)?;
        }
        file.sync_data()
            .map_err(|_| WitnessStoreError::Indeterminate)?;
        Ok(Self {
            file,
            context,
            seed,
            records: complete,
            current,
            poisoned: false,
        })
    }

    fn ensure_healthy(&self) -> Result<(), WitnessStoreError> {
        if self.poisoned {
            Err(WitnessStoreError::Poisoned)
        } else {
            Ok(())
        }
    }
}

impl AnchorWitnessStore for FileNeuronWitnessStoreV2 {
    fn admit_new_anchor(&self, expected: Option<JournalAnchor>) -> Result<(), WitnessStoreError> {
        self.ensure_healthy()?;
        if self.current != expected {
            return Err(WitnessStoreError::Conflict);
        }
        if self.records >= self.context.max_records {
            return Err(WitnessStoreError::Capacity);
        }
        Ok(())
    }

    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.ensure_healthy()?;
        Ok(self.current)
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.admit_new_anchor(expected)?;
        if !is_successor(expected, next) {
            return Err(WitnessStoreError::InvalidAnchor);
        }
        exit_process_cut("before_witness_append");
        let record = encode_record(expected, next);
        let expected_length = HEADER_BYTES as u64
            + u64::try_from(self.records)
                .map_err(|_| WitnessStoreError::Capacity)?
                .checked_mul(RECORD_BYTES as u64)
                .ok_or(WitnessStoreError::Capacity)?;
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != expected_length {
            return Err(WitnessStoreError::Corrupt);
        }
        if process_cut_is("during_witness_append") {
            self.file
                .write_all(&record[..RECORD_BYTES / 2])
                .map_err(|_| WitnessStoreError::Indeterminate)?;
            self.file
                .sync_data()
                .map_err(|_| WitnessStoreError::Indeterminate)?;
            std::process::exit(73);
        }
        self.file
            .write_all(&record)
            .map_err(|_| WitnessStoreError::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| WitnessStoreError::Indeterminate)?;
        exit_process_cut("after_witness_sync_before_response");
        self.records += 1;
        self.current = Some(next);
        self.poisoned = false;
        Ok(())
    }
}

fn encode_header(
    context: &NeuronWitnessContextV2,
    seed: Option<JournalAnchor>,
) -> [u8; HEADER_BYTES] {
    let mut bytes = Vec::with_capacity(HEADER_BYTES);
    bytes.extend_from_slice(if seed.is_some() {
        SUCCESSOR_MAGIC
    } else {
        ROOT_MAGIC
    });
    bytes.extend_from_slice(&SCHEMA_VERSION.to_be_bytes());
    bytes.extend_from_slice(&context.generation.get().to_be_bytes());
    bytes.extend_from_slice(context.scope.scope_digest.as_array());
    bytes.extend_from_slice(context.scope.objective_digest.as_array());
    bytes.extend_from_slice(&context.key_epoch.to_be_bytes());
    bytes.extend_from_slice(&context.deletion_epoch.to_be_bytes());
    match seed {
        Some(anchor) => {
            bytes.push(1);
            bytes.extend_from_slice(&anchor.sequence.to_be_bytes());
            bytes.extend_from_slice(anchor.checkpoint_digest.as_array());
        }
        None => {
            bytes.push(0);
            bytes.extend_from_slice(&0_u64.to_be_bytes());
            bytes.extend_from_slice(Digest32::ZERO.as_array());
        }
    }
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    let mut output = [0_u8; HEADER_BYTES];
    output.copy_from_slice(&bytes);
    output
}

fn encode_record(expected: Option<JournalAnchor>, next: JournalAnchor) -> [u8; RECORD_BYTES] {
    let expected = expected.unwrap_or(JournalAnchor {
        sequence: 0,
        checkpoint_digest: Digest32::ZERO,
    });
    let mut bytes = Vec::with_capacity(RECORD_BYTES);
    bytes.extend_from_slice(&expected.sequence.to_be_bytes());
    bytes.extend_from_slice(expected.checkpoint_digest.as_array());
    bytes.extend_from_slice(&next.sequence.to_be_bytes());
    bytes.extend_from_slice(next.checkpoint_digest.as_array());
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    let mut output = [0_u8; RECORD_BYTES];
    output.copy_from_slice(&bytes);
    output
}

fn decode_record(
    bytes: &[u8; RECORD_BYTES],
) -> Result<(Option<JournalAnchor>, JournalAnchor), WitnessStoreError> {
    if Digest32::of_bytes(&bytes[..RECORD_BYTES - 32]).as_array()
        != &bytes[RECORD_BYTES - 32..]
    {
        return Err(WitnessStoreError::Corrupt);
    }
    let expected_sequence = u64::from_be_bytes(
        bytes[..8]
            .try_into()
            .map_err(|_| WitnessStoreError::Corrupt)?,
    );
    let expected_digest = Digest32::from_array(
        bytes[8..40]
            .try_into()
            .map_err(|_| WitnessStoreError::Corrupt)?,
    );
    let next_sequence = u64::from_be_bytes(
        bytes[40..48]
            .try_into()
            .map_err(|_| WitnessStoreError::Corrupt)?,
    );
    let next_digest = Digest32::from_array(
        bytes[48..80]
            .try_into()
            .map_err(|_| WitnessStoreError::Corrupt)?,
    );
    let expected = match (expected_sequence, expected_digest.is_zero()) {
        (0, true) => None,
        (0, false) | (_, true) => return Err(WitnessStoreError::Corrupt),
        (sequence, false) => Some(JournalAnchor {
            sequence,
            checkpoint_digest: expected_digest,
        }),
    };
    let next = JournalAnchor {
        sequence: next_sequence,
        checkpoint_digest: next_digest,
    };
    if !is_successor(expected, next) {
        return Err(WitnessStoreError::Corrupt);
    }
    Ok((expected, next))
}

fn validate_seed(seed: Option<JournalAnchor>) -> Result<(), WitnessStoreError> {
    if seed.is_some_and(|anchor| anchor.sequence == 0 || anchor.checkpoint_digest.is_zero()) {
        Err(WitnessStoreError::InvalidAnchor)
    } else {
        Ok(())
    }
}

fn is_successor(expected: Option<JournalAnchor>, next: JournalAnchor) -> bool {
    if next.sequence == 0 || next.checkpoint_digest.is_zero() {
        return false;
    }
    expected.map_or(next.sequence == 1, |anchor| {
        anchor.sequence.checked_add(1) == Some(next.sequence)
    })
}

#[cfg(test)]
fn process_cut_is(point: &str) -> bool {
    std::env::var("HEPTA_NEURON_V2_CRASH_CUT").is_ok_and(|value| value == point)
}

#[cfg(not(test))]
fn process_cut_is(_point: &str) -> bool {
    false
}

#[cfg(test)]
fn exit_process_cut(point: &str) {
    if process_cut_is(point) {
        std::process::exit(73);
    }
}

#[cfg(not(test))]
fn exit_process_cut(_point: &str) {}

#[cfg(unix)]
fn sync_parent_directory(path: &Path) -> Result<(), WitnessStoreError> {
    let parent = path
        .parent()
        .ok_or(WitnessStoreError::Io(io::ErrorKind::InvalidInput))?;
    File::open(parent)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_parent_directory(_path: &Path) -> Result<(), WitnessStoreError> {
    Ok(())
}

#[cfg(test)]
#[path = "witness_v2_tests.rs"]
mod tests;
