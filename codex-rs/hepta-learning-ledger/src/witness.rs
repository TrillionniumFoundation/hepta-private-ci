//! Independently persisted acknowledgement witness for the causal learning ledger.
//!
//! The witness is deliberately a separate host-authorized file capability. It
//! records only monotonic ledger anchors and never derives its state from the
//! ledger file it protects. The host still owns path separation, directory
//! durability, backup isolation, encryption and the administrative boundary
//! that makes this file independent in deployment.

use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;

use crate::DurableLedgerError;
use crate::LedgerAnchor;
use crate::durable_lock::LockedFile;

const MAGIC: &[u8; 8] = b"HEPTLW01";
const HEADER: u64 = 72;
const FRAME: u64 = 112;
const MAX_WITNESS_RECORDS: u64 = 1_000_000;
const FRAME_DOMAIN: &[u8] = b"hepta.learning-ledger.anchor-witness.v1";

/// Append-only, independently retained minimum acknowledgement frontier.
///
/// A successful `advance` returns only after the witness bytes have been
/// synchronized. I/O uncertainty poisons the handle so callers cannot issue a
/// later acknowledgement until reopening and reconciling the witness.
pub struct LedgerWitnessStore {
    file: LockedFile,
    binding: Digest32,
    current: LedgerAnchor,
    record_count: u64,
    poisoned: bool,
}

impl LedgerWitnessStore {
    /// Initialize a new, empty witness file. Never use this to replace a lost
    /// witness for an existing acknowledged ledger.
    pub fn create(file: File, binding: Digest32) -> Result<Self, DurableLedgerError> {
        validate_binding(binding)?;
        let mut file = LockedFile::acquire(file)?;
        if file.metadata()?.len() != 0 {
            return Err(DurableLedgerError::AlreadyInitialized);
        }
        let header = encode_header(binding);
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            current: empty_anchor(),
            record_count: 0,
            poisoned: false,
        })
    }

    /// Recover the complete witness lineage. Only an incomplete final frame may
    /// be removed; a complete corrupt or non-monotonic frame fails closed.
    pub fn recover(file: File, binding: Digest32) -> Result<Self, DurableLedgerError> {
        validate_binding(binding)?;
        let mut file = LockedFile::acquire(file)?;
        let length = file.metadata()?.len();
        if length < HEADER {
            return Err(DurableLedgerError::MissingHeader);
        }
        file.seek(SeekFrom::Start(0))?;
        let mut header = [0_u8; HEADER as usize];
        file.read_exact(&mut header)?;
        verify_header(&header, binding)?;

        let mut current = empty_anchor();
        let mut cursor = HEADER;
        let mut record_count = 0_u64;
        while length - cursor >= FRAME {
            if record_count >= MAX_WITNESS_RECORDS {
                return Err(DurableLedgerError::Capacity);
            }
            let mut frame = [0_u8; FRAME as usize];
            file.read_exact(&mut frame)?;
            let (previous, next) = decode_frame(binding, &frame)?;
            if previous != current || !valid_successor(previous, next) {
                return Err(DurableLedgerError::Corrupt);
            }
            current = next;
            cursor += FRAME;
            record_count += 1;
        }

        if cursor != length {
            file.set_len(cursor)
                .map_err(|_| DurableLedgerError::Indeterminate)?;
            file.sync_all()
                .map_err(|_| DurableLedgerError::Indeterminate)?;
        }
        file.seek(SeekFrom::Start(cursor))?;
        Ok(Self {
            file,
            binding,
            current,
            record_count,
            poisoned: false,
        })
    }

    #[must_use]
    pub const fn current_anchor(&self) -> LedgerAnchor {
        self.current
    }

    /// Durably move the minimum acknowledged frontier forward. Replaying the
    /// exact current anchor is idempotent; moving backward or reusing a sequence
    /// with another digest fails closed.
    pub fn advance(
        &mut self,
        expected_previous: LedgerAnchor,
        next: LedgerAnchor,
    ) -> Result<LedgerAnchor, DurableLedgerError> {
        if self.poisoned {
            return Err(DurableLedgerError::Poisoned);
        }
        if expected_previous != self.current {
            return Err(DurableLedgerError::Conflict);
        }
        if next == self.current {
            return Ok(self.current);
        }
        if !valid_successor(self.current, next) {
            return Err(DurableLedgerError::InvalidAnchor);
        }
        if self.record_count >= MAX_WITNESS_RECORDS {
            return Err(DurableLedgerError::Capacity);
        }
        let expected_length = HEADER
            .checked_add(
                self.record_count
                    .checked_mul(FRAME)
                    .ok_or(DurableLedgerError::Capacity)?,
            )
            .ok_or(DurableLedgerError::Capacity)?;
        if self.file.seek(SeekFrom::End(0))? != expected_length {
            return Err(DurableLedgerError::Corrupt);
        }
        let frame = encode_frame(self.binding, self.current, next);
        self.poisoned = true;
        self.file
            .write_all(&frame)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        self.current = next;
        self.record_count += 1;
        self.poisoned = false;
        Ok(self.current)
    }
}

fn validate_binding(binding: Digest32) -> Result<(), DurableLedgerError> {
    if binding.is_zero() {
        Err(DurableLedgerError::InvalidBinding)
    } else {
        Ok(())
    }
}

fn empty_anchor() -> LedgerAnchor {
    LedgerAnchor {
        sequence: 0,
        chain_digest: Digest32::ZERO,
    }
}

fn valid_successor(previous: LedgerAnchor, next: LedgerAnchor) -> bool {
    next.sequence > previous.sequence && !next.chain_digest.is_zero()
}

fn encode_header(binding: Digest32) -> [u8; HEADER as usize] {
    let mut header = [0_u8; HEADER as usize];
    header[..8].copy_from_slice(MAGIC);
    header[8..40].copy_from_slice(binding.as_array());
    let digest = Digest32::of_bytes(&header[..40]);
    header[40..72].copy_from_slice(digest.as_array());
    header
}

fn verify_header(header: &[u8; HEADER as usize], binding: Digest32) -> Result<(), DurableLedgerError> {
    if &header[..8] != MAGIC || Digest32::of_bytes(&header[..40]).as_array() != &header[40..72] {
        return Err(DurableLedgerError::Corrupt);
    }
    if &header[8..40] != binding.as_array() {
        return Err(DurableLedgerError::BindingMismatch);
    }
    Ok(())
}

fn encode_frame(
    binding: Digest32,
    previous: LedgerAnchor,
    next: LedgerAnchor,
) -> [u8; FRAME as usize] {
    let mut frame = [0_u8; FRAME as usize];
    frame[..8].copy_from_slice(&previous.sequence.to_be_bytes());
    frame[8..40].copy_from_slice(previous.chain_digest.as_array());
    frame[40..48].copy_from_slice(&next.sequence.to_be_bytes());
    frame[48..80].copy_from_slice(next.chain_digest.as_array());

    let mut preimage = Vec::with_capacity(FRAME_DOMAIN.len() + 32 + 80);
    preimage.extend_from_slice(FRAME_DOMAIN);
    preimage.extend_from_slice(binding.as_array());
    preimage.extend_from_slice(&frame[..80]);
    let checksum = Digest32::of_bytes(&preimage);
    frame[80..112].copy_from_slice(checksum.as_array());
    frame
}

fn decode_frame(
    binding: Digest32,
    frame: &[u8; FRAME as usize],
) -> Result<(LedgerAnchor, LedgerAnchor), DurableLedgerError> {
    let mut preimage = Vec::with_capacity(FRAME_DOMAIN.len() + 32 + 80);
    preimage.extend_from_slice(FRAME_DOMAIN);
    preimage.extend_from_slice(binding.as_array());
    preimage.extend_from_slice(&frame[..80]);
    if Digest32::of_bytes(&preimage).as_array() != &frame[80..112] {
        return Err(DurableLedgerError::Corrupt);
    }

    let previous = LedgerAnchor {
        sequence: read_u64(&frame[..8])?,
        chain_digest: read_digest(&frame[8..40])?,
    };
    let next = LedgerAnchor {
        sequence: read_u64(&frame[40..48])?,
        chain_digest: read_digest(&frame[48..80])?,
    };
    Ok((previous, next))
}

fn read_u64(bytes: &[u8]) -> Result<u64, DurableLedgerError> {
    let raw: [u8; 8] = bytes
        .try_into()
        .map_err(|_| DurableLedgerError::Corrupt)?;
    Ok(u64::from_be_bytes(raw))
}

fn read_digest(bytes: &[u8]) -> Result<Digest32, DurableLedgerError> {
    let raw: [u8; 32] = bytes
        .try_into()
        .map_err(|_| DurableLedgerError::Corrupt)?;
    Ok(Digest32::from_array(raw))
}

#[cfg(test)]
mod tests {
    use std::fs::OpenOptions;
    use std::path::PathBuf;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn anchor(sequence: u64, value: &str) -> LedgerAnchor {
        LedgerAnchor {
            sequence,
            chain_digest: digest(value),
        }
    }

    fn temp_file(label: &str) -> (PathBuf, File) {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock after epoch")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "hepta-learning-ledger-{label}-{}-{nanos}.bin",
            std::process::id()
        ));
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&path)
            .expect("create witness fixture");
        (path, file)
    }

    fn reopen(path: &PathBuf) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .expect("reopen witness fixture")
    }

    #[test]
    fn witness_round_trip_is_monotonic_and_durable() {
        let binding = digest("witness-binding");
        let (path, file) = temp_file("round-trip");
        let mut witness = LedgerWitnessStore::create(file, binding).expect("create witness");
        let first = anchor(1, "chain-1");
        let second = anchor(4, "chain-4");
        assert_eq!(
            witness.advance(witness.current_anchor(), first),
            Ok(first)
        );
        assert_eq!(witness.advance(first, second), Ok(second));
        drop(witness);

        let recovered = LedgerWitnessStore::recover(reopen(&path), binding).expect("recover witness");
        assert_eq!(recovered.current_anchor(), second);
        drop(recovered);
        std::fs::remove_file(path).expect("remove witness fixture");
    }

    #[test]
    fn witness_rejects_stale_predecessor_and_backward_motion() {
        let binding = digest("witness-binding");
        let (path, file) = temp_file("conflict");
        let mut witness = LedgerWitnessStore::create(file, binding).expect("create witness");
        let first = anchor(2, "chain-2");
        witness
            .advance(witness.current_anchor(), first)
            .expect("advance witness");
        assert_eq!(
            witness.advance(empty_anchor(), anchor(3, "chain-3")),
            Err(DurableLedgerError::Conflict)
        );
        assert_eq!(
            witness.advance(first, anchor(1, "chain-1")),
            Err(DurableLedgerError::InvalidAnchor)
        );
        drop(witness);
        std::fs::remove_file(path).expect("remove witness fixture");
    }

    #[test]
    fn witness_recovery_repairs_only_an_incomplete_final_frame() {
        let binding = digest("witness-binding");
        let (path, file) = temp_file("partial-tail");
        let mut witness = LedgerWitnessStore::create(file, binding).expect("create witness");
        let first = anchor(1, "chain-1");
        witness
            .advance(witness.current_anchor(), first)
            .expect("advance witness");
        drop(witness);

        let mut damaged = OpenOptions::new()
            .append(true)
            .open(&path)
            .expect("open witness tail");
        damaged.write_all(&[1, 2, 3, 4, 5]).expect("write partial tail");
        damaged.sync_all().expect("sync partial tail");
        drop(damaged);

        let recovered = LedgerWitnessStore::recover(reopen(&path), binding).expect("repair tail");
        assert_eq!(recovered.current_anchor(), first);
        assert_eq!(recovered.file.metadata().expect("metadata").len(), HEADER + FRAME);
        drop(recovered);
        std::fs::remove_file(path).expect("remove witness fixture");
    }
}
