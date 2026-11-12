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
        let current = (|| -> Result<ProductEvaluationExecutionAnchorV1, FileError> {
            let length = self.file.metadata().map_err(io_error)?.len();
            if length > MAX_FILE_BYTES {
                return Err(FileError::Capacity);
            }
            if length != self.length {
                return Err(FileError::Corrupt);
            }
            self.file.seek(SeekFrom::Start(0)).map_err(io_error)?;
            let mut bytes = Vec::new();
            (&mut *self.file)
                .take(MAX_FILE_BYTES + 1)
                .read_to_end(&mut bytes)
                .map_err(io_error)?;
            if bytes.len() as u64 != length
                || self.file.metadata().map_err(io_error)?.len() != length
            {
                return Err(FileError::Corrupt);
            }
            if bytes.len() < HEADER {
                return Err(FileError::MissingHeader);
            }
            if &bytes[..8] != MAGIC
                || &bytes[8..40] != self.binding.as_array()
                || &bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()
            {
                return Err(FileError::Corrupt);
            }
            let mut current = ProductEvaluationExecutionAnchorV1 {
                sequence: 0,
                history_digest: Digest32::of_bytes(&bytes[..HEADER]),
            };
            let mut records = BTreeMap::new();
            let mut remaining = &bytes[HEADER..];
            while !remaining.is_empty() {
                let raw: [u8; 4] = take(&mut remaining, /*count*/ 4)?
                    .try_into()
                    .map_err(|_| FileError::Corrupt)?;
                let count = u32::from_be_bytes(raw) as usize;
                if !(36..=MAX_FRAME).contains(&count) {
                    return Err(FileError::Capacity);
                }
                let payload = take(&mut remaining, count)?;
                let checksum = take(&mut remaining, /*count*/ 32)?;
                let next = next_anchor(current, payload)?;
                if checksum != next.history_digest.as_array() {
                    return Err(FileError::Corrupt);
                }
                replay(&mut records, payload)?;
                current = next;
            }
            if current != self.anchor || records != self.records {
                return Err(FileError::Rollback);
            }
            Ok(current)
        })();
        let restored = self.file.seek(SeekFrom::Start(cursor)).map_err(io_error);
        let result = match (current, restored) {
            (Err(error), _) | (_, Err(error)) => Err(error),
            (Ok(current), Ok(position)) if position == cursor => Ok(current),
            (Ok(_), Ok(_)) => Err(FileError::Indeterminate),
        };
        if result.is_err() {
            self.poisoned = true;
        }
        result
    }
}
