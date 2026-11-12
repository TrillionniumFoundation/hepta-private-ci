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
        let replayed = physical::replay_image(&bytes, binding, exact)?;
        if replayed.anchor != exact {
            return Err(FileError::Rollback);
        }
        Ok(Self {
            file,
            records: replayed.records,
            anchor: replayed.anchor,
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
    let result = physical::read_stable_image(file);
    let unlocked = file.unlock().map_err(io_error);
    let bytes = result?;
    unlocked?;
    Ok(bytes)
}
