//! Physical CURRENT validation through the original exclusive file description.
//! This neither acquires a second writer nor advances or repairs a journal.

use super::*;

impl LockedFileProductEvaluationExecutionStoreV1 {
    /// Validate the complete bounded history and cached state against the
    /// original file. The lock, bytes, append owner and cursor are preserved.
    /// Any mismatch or I/O uncertainty permanently poisons this live owner.
    /// Callers must bracket this read with their independent witness checks.
    pub fn read_current_anchor(&mut self) -> Result<ProductEvaluationExecutionAnchorV1, FileError> {
        if self.poisoned {
            return Err(FileError::Indeterminate);
        }
        let cursor = match self.file.stream_position() {
            Ok(cursor) => cursor,
            Err(error) => {
                self.poisoned = true;
                return Err(io_error(error));
            }
        };
        let current = (|| {
            let length = self.file.metadata().map_err(io_error)?.len();
            if length > MAX_FILE_BYTES {
                return Err(FileError::Capacity);
            }
            if length != self.length {
                return Err(FileError::Corrupt);
            }
            let bytes = physical::read_stable_image(&mut self.file)?;
            let replayed = self.replay_current_image(&bytes)?;
            if bytes.len() as u64 != self.length
                || replayed.anchor != self.anchor
                || replayed.records != self.records
                || Digest32::of_bytes(&bytes) != self.image_digest
            {
                return Err(FileError::Rollback);
            }
            let stable = physical::read_stable_image(&mut self.file)?;
            if stable != bytes || Digest32::of_bytes(&stable) != self.image_digest {
                return Err(FileError::Rollback);
            }
            Ok((replayed.anchor, bytes, replayed))
        })();
        let restored = self.file.seek(SeekFrom::Start(cursor)).map_err(io_error);
        let result = match (current, restored) {
            (Err(error), _) | (_, Err(error)) => Err(error),
            (Ok((current, bytes, replayed)), Ok(position)) if position == cursor => {
                // Publish only after every physical check and cursor restoration.
                self.remember_verified_replay(&bytes, replayed);
                Ok(current)
            }
            (Ok(_), Ok(_)) => Err(FileError::Indeterminate),
        };
        if result.is_err() {
            self.poisoned = true;
        }
        result
    }
}
