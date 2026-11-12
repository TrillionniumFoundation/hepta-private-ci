//! Read-only recovery of one fully witnessed execution journal.
//!
//! The authorized descriptor and exact terminal anchor come from the original
//! owner. This is data readback, not evaluator authentication or a writer lease.
//! All writers must honor the file lock; path identity, current witness custody
//! and signed completion admission remain with the caller. Never retain a
//! duplicate open description whose lock/cursor can be changed independently.

use super::*;

/// Opens existing HEPTEX01 bytes without creating, repairing, acknowledging or
/// fsyncing anything. A valid but unwitnessed suffix is refused. Shared locks are
/// held only while reading, so this reader does not retain an old writer lease.
pub struct ReadOnlyProductEvaluationExecutionStoreV1 {
    file: File,
    records: BTreeMap<StableId, (Digest32, State)>,
    anchor: ProductEvaluationExecutionAnchorV1,
    bytes_digest: Digest32,
    poisoned: bool,
}

impl ReadOnlyProductEvaluationExecutionStoreV1 {
    pub fn open(
        mut file: File,
        binding: Digest32,
        exact: ProductEvaluationExecutionAnchorV1,
    ) -> Result<Self, FileError> {
        if binding.is_zero() {
            return Err(FileError::Binding);
        }
        let bytes = snapshot(&mut file)?;
        if bytes.len() < HEADER {
            return Err(FileError::MissingHeader);
        }
        if &bytes[..8] != MAGIC
            || &bytes[8..40] != binding.as_array()
            || &bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()
        {
            return Err(FileError::Corrupt);
        }
        let mut anchor = ProductEvaluationExecutionAnchorV1 {
            sequence: 0,
            history_digest: Digest32::of_bytes(&bytes[..HEADER]),
        };
        let mut records = BTreeMap::new();
        let mut remaining = &bytes[HEADER..];
        while !remaining.is_empty() {
            let raw: [u8; 4] = take(&mut remaining, 4)?
                .try_into()
                .map_err(|_| FileError::Corrupt)?;
            let count = u32::from_be_bytes(raw) as usize;
            if !(36..=MAX_FRAME).contains(&count) {
                return Err(FileError::Capacity);
            }
            let payload = take(&mut remaining, count)?;
            let checksum = take(&mut remaining, 32)?;
            let next = next_anchor(anchor, payload)?;
            if checksum != next.history_digest.as_array() {
                return Err(FileError::Corrupt);
            }
            replay(&mut records, payload)?;
            anchor = next;
        }
        if anchor != exact {
            return Err(FileError::Rollback);
        }
        Ok(Self {
            file,
            records,
            anchor,
            bytes_digest: Digest32::of_bytes(&bytes),
            poisoned: false,
        })
    }

    /// Identifies the immutable cut admitted at open; it is not a live witness.
    #[must_use]
    pub fn anchor(&self) -> ProductEvaluationExecutionAnchorV1 {
        self.anchor
    }

    /// Rechecks all physical bytes before returning even a cached Pending or
    /// Completed state. Any observed unreadability or change permanently fences
    /// this handle; restoring old bytes cannot clear that observation.
    pub fn readback(&mut self, key: &ProductEvaluationExecutionKeyV1) -> Result<State, StoreError> {
        if self.poisoned {
            return Err(StoreError::Indeterminate);
        }
        if !matches!(
            snapshot(&mut self.file),
            Ok(bytes) if Digest32::of_bytes(&bytes) == self.bytes_digest
        ) {
            self.poisoned = true;
            return Err(StoreError::Indeterminate);
        }
        let (binding, state) = self.records.get(&key.plan_id).ok_or(StoreError::Missing)?;
        if *binding != key.binding_digest {
            return Err(StoreError::Conflict);
        }
        Ok(state.clone())
    }
}

fn snapshot(file: &mut File) -> Result<Vec<u8>, FileError> {
    file.try_lock_shared().map_err(|error| match error {
        TryLockError::WouldBlock => FileError::Busy,
        TryLockError::Error(error) => io_error(error),
    })?;
    let result = (|| {
        let metadata = file.metadata().map_err(io_error)?;
        if !metadata.is_file() {
            return Err(FileError::NotRegular);
        }
        let length = metadata.len();
        if length > MAX_FILE_BYTES {
            return Err(FileError::Capacity);
        }
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        let mut bytes = Vec::new();
        (&mut *file)
            .take(MAX_FILE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(io_error)?;
        if bytes.len() as u64 != length || file.metadata().map_err(io_error)?.len() != length {
            return Err(FileError::Corrupt);
        }
        Ok(bytes)
    })();
    let unlocked = file.unlock().map_err(io_error);
    let bytes = result?;
    unlocked?;
    Ok(bytes)
}
