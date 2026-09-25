//! A checkpoint is a complete retained-identity set, not an arbitrary valid
//! prefix. Counts and an end marker detect whole-record truncation; they are
//! structural integrity checks, not a signature or backup rollback authority.
use super::Error;

pub(super) const HEADER: &str = "checkpoint-set-v1|";
pub(super) const END: &str = "checkpoint-set-end-v1";

#[derive(Default)]
pub(super) struct CheckpointFrame {
    seen_record: bool,
    remaining: Option<usize>,
}

impl CheckpointFrame {
    /// Return true for framing records already consumed by this validator.
    pub(super) fn observe(&mut self, line: &str, capacity: usize) -> Result<bool, Error> {
        if let Some(count) = line.strip_prefix(HEADER) {
            if self.seen_record {
                return Err(Error::CorruptJournal("checkpoint is not first"));
            }
            let count: usize = count
                .parse()
                .map_err(|_| Error::CorruptJournal("checkpoint count"))?;
            if count > capacity {
                return Err(Error::CapacityExceeded);
            }
            self.remaining = Some(count);
            self.seen_record = true;
            return Ok(true);
        }
        self.seen_record = true;
        if line == END {
            if self.remaining != Some(0) {
                return Err(Error::CorruptJournal("checkpoint incomplete set"));
            }
            self.remaining = None;
            return Ok(true);
        }
        let checkpoint = line.starts_with(super::LEGACY_CHECKPOINT_PREFIX)
            || line.starts_with(super::native::CHECKPOINT_PREFIX);
        if checkpoint {
            let remaining = self
                .remaining
                .as_mut()
                .ok_or(Error::CorruptJournal("checkpoint outside set"))?;
            *remaining = remaining
                .checked_sub(1)
                .ok_or(Error::CorruptJournal("checkpoint extra identity"))?;
        } else if self.remaining.is_some() {
            return Err(Error::CorruptJournal("checkpoint missing end marker"));
        }
        Ok(false)
    }

    pub(super) fn finish(self) -> Result<(), Error> {
        if self.remaining.is_some() {
            return Err(Error::CorruptJournal("checkpoint truncated set"));
        }
        Ok(())
    }
}
