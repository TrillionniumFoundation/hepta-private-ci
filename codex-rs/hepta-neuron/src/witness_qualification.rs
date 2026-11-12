//! Opt-in byte observation without changing the witness lock or write rights.

use std::sync::atomic::Ordering;

use super::FileAnchorWitnessStore;
use crate::WitnessStoreError;
use crate::qualification_file::FileBytesError;
use crate::qualification_file::file_bytes as read_file_bytes;

pub(super) fn file_bytes(
    witness: &mut FileAnchorWitnessStore,
    maximum_bytes: u64,
) -> Result<Vec<u8>, WitnessStoreError> {
    if witness.poisoned.load(Ordering::Acquire) {
        return Err(WitnessStoreError::Poisoned);
    }
    let result = match witness.file.get_mut() {
        Ok(file) => read_file_bytes(file, maximum_bytes).map_err(|error| match error {
            FileBytesError::Capacity => WitnessStoreError::Capacity,
            FileBytesError::Io(error) => WitnessStoreError::Io(error.kind()),
        }),
        Err(_) => Err(WitnessStoreError::Indeterminate),
    };
    if result
        .as_ref()
        .is_err_and(|error| !matches!(error, WitnessStoreError::Capacity))
    {
        witness.poisoned.store(true, Ordering::Release);
    }
    result
}
