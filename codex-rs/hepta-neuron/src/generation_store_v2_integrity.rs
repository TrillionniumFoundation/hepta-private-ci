//! Verify retained generation history before returning cached authority facts.
//! MeasuredFileV2 is intentionally not Sync, so these synchronous descriptor
//! reads cannot race another safe shared owner call on the same seek cursor.

use super::*;

impl FileNeuronGenerationStoreV2 {
    pub(super) fn ensure_healthy(&self) -> Result<(), GenerationStoreError> {
        if self.poisoned.get() {
            return Err(GenerationStoreError::Poisoned);
        }
        let result = self.verify_retained_history();
        if result.is_err() {
            self.poisoned.set(true);
        }
        result
    }

    fn verify_retained_history(&self) -> Result<(), GenerationStoreError> {
        self.file.verify_identity()?;
        let mut file = &**self.file;
        if file.metadata()?.len() != self.end_offset {
            return Err(GenerationStoreError::Corrupt);
        }
        file.seek(SeekFrom::Start(0))?;
        let mut header = [0; HEADER_BYTES];
        file.read_exact(&mut header)?;
        if header != encode_header(&self.context)? {
            return Err(GenerationStoreError::ContextMismatch);
        }
        let mut offset = HEADER_BYTES as u64;
        let mut frontier = Digest32::ZERO;
        let mut events = 0_usize;
        let maximum_events = self
            .records
            .len()
            .checked_mul(2)
            .ok_or(GenerationStoreError::Capacity)?;
        while offset < self.end_offset {
            if events >= maximum_events || self.end_offset - offset < 4 + CHECKSUM_BYTES as u64 {
                return Err(GenerationStoreError::Corrupt);
            }
            let mut length_bytes = [0; 4];
            file.read_exact(&mut length_bytes)?;
            let length = u32::from_be_bytes(length_bytes) as usize;
            if length == 0 || length > MAX_FRAME_BYTES {
                return Err(GenerationStoreError::Corrupt);
            }
            let frame_bytes = framed_bytes(length)?;
            if frame_bytes > self.end_offset - offset {
                return Err(GenerationStoreError::Corrupt);
            }
            let mut payload = vec![0; length];
            file.read_exact(&mut payload)?;
            let mut checksum = [0; CHECKSUM_BYTES];
            file.read_exact(&mut checksum)?;
            if Digest32::of_parts(&[&length_bytes, &payload]).as_array() != &checksum {
                return Err(GenerationStoreError::Corrupt);
            }
            // decode_event checks the complete encoded event body digest; the
            // chain is anchored to the exact frontier retained after our writes.
            let (previous, next) = match decode_event(&payload)? {
                DecodedEventV2::Commit {
                    previous_event_digest,
                    event_digest,
                    ..
                }
                | DecodedEventV2::WitnessAck {
                    previous_event_digest,
                    event_digest,
                    ..
                } => (previous_event_digest, event_digest),
            };
            if previous != frontier {
                return Err(GenerationStoreError::Corrupt);
            }
            frontier = next;
            events += 1;
            offset += frame_bytes;
        }
        if frontier != self.event_frontier || file.metadata()?.len() != self.end_offset {
            return Err(GenerationStoreError::Corrupt);
        }
        self.file.verify_identity()?;
        Ok(())
    }
}
