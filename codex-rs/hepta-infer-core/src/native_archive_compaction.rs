//! Journal replacement keeps both old and new file identities writer-locked.

use std::fs;
use std::fs::File;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::time::Duration;
use std::time::Instant;

use super::DurableInferenceControl;
use super::Error;
use super::MAX_JOURNAL_BYTES;
use super::MAX_JOURNAL_LINE_BYTES;
use super::archive_store;
use super::native::Event;
use super::native::JOURNAL_PREFIX;

impl DurableInferenceControl {
    pub(super) fn compact_native_history(
        &mut self,
        started: Instant,
        budget: Duration,
    ) -> Result<bool, Error> {
        if !self.native.compaction_pending || started.elapsed() >= budget {
            return Ok(false);
        }
        let temporary = self
            .path
            .with_extension(format!("{:032x}.compact", rand::random::<u128>()));
        let result = (|| {
            let mut replacement = archive_store::private_options()
                .create_new(true)
                .append(true)
                .read(true)
                .open(&temporary)?;
            replacement
                .try_lock()
                .map_err(|_| Error::WriterUnavailable)?;
            let mut bytes = 0_u64;
            if let Some(maximum_in_flight) = self.native.maximum_in_flight {
                let pin = serde_json::to_string(&Event::CapacityPinned { maximum_in_flight })
                    .map_err(|_| Error::CorruptJournal("native capacity encode"))?;
                let encoded = format!("{JOURNAL_PREFIX}{pin}\n");
                replacement.write_all(encoded.as_bytes())?;
                bytes += encoded.len() as u64;
            }
            let mut reader = BufReader::new(File::open(&self.path)?);
            let mut consumed = 0_u64;
            loop {
                if started.elapsed() >= budget {
                    return Ok(false);
                }
                let mut line = Vec::new();
                let count = (&mut reader)
                    .take(MAX_JOURNAL_LINE_BYTES as u64 + 1)
                    .read_until(b'\n', &mut line)?;
                if count == 0 {
                    break;
                }
                consumed += count as u64;
                if count > MAX_JOURNAL_LINE_BYTES || consumed > MAX_JOURNAL_BYTES {
                    return Err(Error::CapacityExceeded);
                }
                if line.last() != Some(&b'\n') {
                    return Err(Error::CorruptJournal("incomplete compacted native journal"));
                }
                let value = std::str::from_utf8(&line)
                    .map_err(|_| Error::CorruptJournal("native compaction utf8"))?;
                let keep = if let Some(json) = value.strip_prefix(JOURNAL_PREFIX) {
                    let event: Event = serde_json::from_str(json)
                        .map_err(|_| Error::CorruptJournal("native compaction decode"))?;
                    event
                        .request_id()
                        .is_some_and(|id| self.native.records.contains_key(id))
                } else {
                    true // Generic control-owner events are preserved exactly.
                };
                if keep {
                    replacement.write_all(&line)?;
                    bytes += count as u64;
                }
            }
            if bytes > MAX_JOURNAL_BYTES {
                return Err(Error::CapacityExceeded);
            }
            replacement.sync_all()?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::MetadataExt;
                let opened = self.file.metadata()?;
                let current = fs::metadata(&self.path)?;
                if opened.dev() != current.dev() || opened.ino() != current.ino() {
                    return Err(Error::WriterUnavailable);
                }
            }
            fs::rename(&temporary, &self.path)?;
            // New readers now see the locked replacement. Keep that descriptor
            // even when parent fsync fails: writes must never resume on old inode.
            self.file = replacement;
            self.journal_bytes = bytes;
            let parent = self
                .path
                .parent()
                .filter(|path| !path.as_os_str().is_empty())
                .unwrap_or_else(|| std::path::Path::new("."));
            if let Err(error) = File::open(parent).and_then(|file| file.sync_all()) {
                self.poisoned = true;
                return Err(error.into());
            }
            self.native.compaction_pending = false;
            Ok(true)
        })();
        if temporary.exists() {
            let _ = fs::remove_file(&temporary);
        }
        result
    }
}
