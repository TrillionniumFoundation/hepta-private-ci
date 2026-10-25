//! Synchronous private-file transaction mechanics, following the existing
//! Objective checkpoint's retained-lock and atomic-replace protocol.
use super::*;
use sha2::Digest;
#[cfg(unix)]
use std::io::Read;
#[cfg(unix)]
use std::io::Write;

const MAX_BYTES: u64 = 8 * 1024 * 1024;

fn unavailable<T>(_: T) -> AgentRunError {
    AgentRunError::PersistenceUnavailable
}

fn checksum(sequence: u64, snapshot: &Snapshot) -> Result<String, AgentRunError> {
    let bytes = serde_json::to_vec(&(1_u32, sequence, snapshot)).map_err(unavailable)?;
    Ok(format!("{:x}", sha2::Sha256::digest(bytes)))
}

impl LifecycleJournal {
    #[cfg(unix)]
    pub(super) fn open(
        path: &Path,
        mode: JournalOpenMode,
    ) -> Result<(Self, Option<Snapshot>), AgentRunError> {
        use std::os::unix::fs::OpenOptionsExt;
        let parent = path.parent().ok_or(AgentRunError::PersistenceUnavailable)?;
        if !path.is_absolute() || parent.canonicalize().map_err(unavailable)? != parent {
            return Err(AgentRunError::PersistenceUnavailable);
        }
        private_parent(parent)?;
        let lock_path = path.with_extension("lifecycle-lock");
        if lock_path == path {
            return Err(AgentRunError::PersistenceUnavailable);
        }
        let lock = std::fs::OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
            .open(&lock_path)
            .map_err(unavailable)?;
        private_file(&lock, &lock_path, parent)?;
        lock.try_lock().map_err(unavailable)?;
        let stored = match (mode, std::fs::symlink_metadata(path)) {
            (JournalOpenMode::Create, Err(error))
                if error.kind() == std::io::ErrorKind::NotFound =>
            {
                None
            }
            (JournalOpenMode::Reopen, Ok(_)) => Some(read_document(path)?),
            _ => return Err(AgentRunError::PersistenceUnavailable),
        };
        Ok((
            Self {
                path: path.to_path_buf(),
                _lock: lock,
                sequence: stored.as_ref().map_or(0, |document| document.sequence),
                committed: stored.as_ref().map(|document| document.snapshot.clone()),
                poisoned: false,
                #[cfg(test)]
                fail_before_publish: false,
                #[cfg(test)]
                fail_after_publish: false,
            },
            stored.map(|document| document.snapshot),
        ))
    }

    #[cfg(not(unix))]
    pub(super) fn open(
        _path: &Path,
        _mode: JournalOpenMode,
    ) -> Result<(Self, Option<Snapshot>), AgentRunError> {
        Err(AgentRunError::PersistenceUnavailable)
    }

    pub(super) fn commit(&mut self, snapshot: Snapshot) -> Result<(), AgentRunError> {
        if self.poisoned {
            return Err(AgentRunError::PersistenceUnavailable);
        }
        let sequence = self
            .sequence
            .checked_add(1)
            .ok_or(AgentRunError::PersistenceUnavailable)?;
        let checksum = checksum(sequence, &snapshot)?;
        let document = Document {
            schema: 1,
            sequence,
            snapshot,
            checksum,
        };
        let bytes = serde_json::to_vec(&document).map_err(unavailable)?;
        if bytes.len() as u64 > MAX_BYTES {
            return Err(AgentRunError::PersistenceUnavailable);
        }
        if let Err(error) = self.publish(&bytes) {
            self.poisoned = true;
            return Err(error);
        }
        self.sequence = sequence;
        self.committed = Some(document.snapshot);
        Ok(())
    }

    #[cfg(unix)]
    fn publish(&self, bytes: &[u8]) -> Result<(), AgentRunError> {
        use std::os::unix::fs::OpenOptionsExt;
        let parent = self
            .path
            .parent()
            .ok_or(AgentRunError::PersistenceUnavailable)?;
        private_parent(parent)?;
        private_file(
            &self._lock,
            &self.path.with_extension("lifecycle-lock"),
            parent,
        )?;
        if self.sequence != 0 {
            let current = read_document(&self.path)?;
            if current.sequence != self.sequence
                || self.committed.as_ref() != Some(&current.snapshot)
            {
                return Err(AgentRunError::PersistenceUnavailable);
            }
        }
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(unavailable)?
            .as_nanos();
        // This nonce only avoids temporary-name collisions; it is not identity
        // or an authority/rollback fence.
        let temp = parent.join(format!(".lifecycle-{}-{nonce}.tmp", std::process::id()));
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
            .open(&temp)
            .map_err(unavailable)?;
        let outcome = (|| {
            file.write_all(bytes).map_err(unavailable)?;
            file.sync_all().map_err(unavailable)?;
            #[cfg(test)]
            if self.fail_before_publish {
                return Err(AgentRunError::PersistenceUnavailable);
            }
            if self.sequence == 0 {
                // Atomic no-replace publication: never overwrite a file that
                // appeared after Create checked for absence.
                std::fs::hard_link(&temp, &self.path).map_err(unavailable)?;
                std::fs::remove_file(&temp).map_err(unavailable)?;
            } else {
                std::fs::rename(&temp, &self.path).map_err(unavailable)?;
            }
            #[cfg(test)]
            if self.fail_after_publish {
                return Err(AgentRunError::PersistenceUnavailable);
            }
            File::open(parent)
                .and_then(|directory| directory.sync_all())
                .map_err(unavailable)?;
            let observed = read_bytes(&self.path)?;
            if observed != bytes {
                return Err(AgentRunError::PersistenceUnavailable);
            }
            Ok(())
        })();
        if outcome.is_err() {
            let _ = std::fs::remove_file(&temp);
        }
        outcome
    }

    #[cfg(not(unix))]
    fn publish(&self, _bytes: &[u8]) -> Result<(), AgentRunError> {
        Err(AgentRunError::PersistenceUnavailable)
    }
}

#[cfg(unix)]
fn private_parent(path: &Path) -> Result<(), AgentRunError> {
    use std::os::unix::fs::MetadataExt;
    let metadata = std::fs::symlink_metadata(path).map_err(unavailable)?;
    if !metadata.is_dir() || metadata.mode() & 0o077 != 0 {
        return Err(AgentRunError::PersistenceUnavailable);
    }
    Ok(())
}

#[cfg(unix)]
fn private_file(file: &File, path: &Path, parent: &Path) -> Result<(), AgentRunError> {
    use std::os::unix::fs::MetadataExt;
    let opened = file.metadata().map_err(unavailable)?;
    let linked = std::fs::symlink_metadata(path).map_err(unavailable)?;
    let owner = std::fs::metadata(parent).map_err(unavailable)?;
    if !opened.is_file()
        || !linked.is_file()
        || linked.nlink() != 1
        || linked.mode() & 0o077 != 0
        || linked.uid() != owner.uid()
        || opened.dev() != linked.dev()
        || opened.ino() != linked.ino()
    {
        return Err(AgentRunError::PersistenceUnavailable);
    }
    Ok(())
}

#[cfg(unix)]
fn read_bytes(path: &Path) -> Result<Vec<u8>, AgentRunError> {
    use std::os::unix::fs::OpenOptionsExt;
    let parent = path.parent().ok_or(AgentRunError::PersistenceUnavailable)?;
    let linked = std::fs::symlink_metadata(path).map_err(unavailable)?;
    if !linked.is_file() {
        return Err(AgentRunError::PersistenceUnavailable);
    }
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)
        .map_err(unavailable)?;
    private_file(&file, path, parent)?;
    if file.metadata().map_err(unavailable)?.len() > MAX_BYTES {
        return Err(AgentRunError::PersistenceUnavailable);
    }
    let mut bytes = Vec::new();
    file.take(MAX_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(unavailable)?;
    if bytes.len() as u64 > MAX_BYTES {
        return Err(AgentRunError::PersistenceUnavailable);
    }
    Ok(bytes)
}

#[cfg(unix)]
fn read_document(path: &Path) -> Result<Document, AgentRunError> {
    let bytes = read_bytes(path)?;
    let document: Document = serde_json::from_slice(&bytes).map_err(unavailable)?;
    if serde_json::to_vec(&document).map_err(unavailable)? != bytes
        || document.schema != 1
        || document.sequence == 0
        || checksum(document.sequence, &document.snapshot)? != document.checksum
    {
        return Err(AgentRunError::PersistenceUnavailable);
    }
    Ok(document)
}
