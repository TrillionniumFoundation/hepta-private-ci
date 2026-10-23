//! Recover a lost storage acknowledgement without replaying the publication.
//!
//! This is a storage operation, not signer authorization. The caller must bind
//! the supplied digest to its durably dispatched, independently verified value.

use super::*;

impl LockedFileEvidenceFrontierBackend {
    /// Recover the acknowledgement for an exact historical publication.
    ///
    /// A visible journal record is not proof that a previous `fsync` succeeded.
    /// Recovery therefore holds the journal lock, validates the complete chain,
    /// synchronizes the existing file and its pinned directory again, and only
    /// then returns the original audit identity. It never appends a record or
    /// changes the generation. `None` is not a terminal negative outcome.
    ///
    /// A handle poisoned by an earlier uncertain write must be reopened before
    /// reconciliation. This method does not clear poison or authorize a signer.
    pub fn recover_durable_acknowledgement(
        &mut self,
        store_id: &str,
        frontier_generation: u64,
        expected_frontier_sha256: &Sha256Digest,
    ) -> Result<Option<EvidenceFrontierDurableAckV1>, EvidenceFrontierBackendError> {
        self.recover_ack_with_sync(
            store_id,
            frontier_generation,
            expected_frontier_sha256,
            |file, directory| {
                file.sync_all()?;
                directory.sync_all()
            },
        )
    }

    fn recover_ack_with_sync(
        &mut self,
        store_id: &str,
        frontier_generation: u64,
        expected_frontier_sha256: &Sha256Digest,
        synchronize: impl FnOnce(&File, &File) -> io::Result<()>,
    ) -> Result<Option<EvidenceFrontierDurableAckV1>, EvidenceFrontierBackendError> {
        self.ensure_available()?;
        if frontier_generation == 0 {
            return Err(EvidenceFrontierBackendError::Invalid(
                "acknowledgement recovery requires a positive generation".to_string(),
            ));
        }
        self.verify_backend_identity()?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;

            let path = self.journal_path(store_id)?;
            // Never create an empty journal to make an absent publication look
            // reconciled. Nonblocking open also rejects special-file attacks
            // without blocking on a FIFO before metadata can be inspected.
            let mut file = match OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK)
                .open(&path)
            {
                Ok(file) => file,
                Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
                Err(error) => return Err(unavailable(error)),
            };
            validate_journal_metadata(&file, self.owner_uid)?;
            // Do not block a daemon worker indefinitely behind a publisher.
            file.try_lock().map_err(|error| {
                EvidenceFrontierBackendError::Unavailable(format!(
                    "publication acknowledgement recovery lock unavailable: {error}"
                ))
            })?;
            let directory = open_pinned_directory(
                &self.journals,
                self.owner_uid,
                self.journals_device,
                self.journals_inode,
            )?;
            let pinned = file.metadata().map_err(unavailable)?;
            require_same_journal(&file, &path, &pinned, self.owner_uid)?;
            let records = read_records_from_locked(
                &mut file,
                store_id,
                &self.identity,
                &self.identity_sha256,
            )?;
            let Some(record) = records
                .iter()
                .find(|record| record.frontier.frontier_generation == frontier_generation)
            else {
                return Ok(None);
            };
            if &record.frontier_sha256 != expected_frontier_sha256 {
                return Err(EvidenceFrontierBackendError::Invalid(
                    "historical publication digest differs from the durable dispatch pin"
                        .to_string(),
                ));
            }
            let acknowledgement = EvidenceFrontierDurableAckV1 {
                backend_id: self.identity.backend_id.clone(),
                backend_identity_sha256: self.identity_sha256.clone(),
                store_id: store_id.to_string(),
                frontier_generation,
                frontier_sha256: record.frontier_sha256.clone(),
                audit_sequence: record.audit_sequence,
            };
            if let Err(error) = synchronize(&file, &directory) {
                self.poisoned = true;
                return Err(EvidenceFrontierBackendError::Indeterminate(
                    error.to_string(),
                ));
            }
            if let Err(error) = require_same_journal(&file, &path, &pinned, self.owner_uid)
                .and_then(|()| self.verify_backend_identity().map(|_| ()))
            {
                self.poisoned = true;
                return Err(EvidenceFrontierBackendError::Indeterminate(
                    error.to_string(),
                ));
            }
            Ok(Some(acknowledgement))
        }
        #[cfg(not(unix))]
        {
            let _ = (store_id, expected_frontier_sha256, synchronize);
            Err(EvidenceFrontierBackendError::Unsupported)
        }
    }
}

#[cfg(unix)]
fn require_same_journal(
    file: &File,
    path: &Path,
    pinned: &std::fs::Metadata,
    owner_uid: u32,
) -> Result<(), EvidenceFrontierBackendError> {
    use std::os::unix::fs::MetadataExt;

    validate_journal_metadata(file, owner_uid)?;
    let opened = file.metadata().map_err(unavailable)?;
    let named = std::fs::symlink_metadata(path).map_err(unavailable)?;
    if opened.len() != pinned.len()
        || opened.mtime() != pinned.mtime()
        || opened.mtime_nsec() != pinned.mtime_nsec()
        || opened.ctime() != pinned.ctime()
        || opened.ctime_nsec() != pinned.ctime_nsec()
        || !named.is_file()
        || named.dev() != opened.dev()
        || named.ino() != opened.ino()
        || named.nlink() != 1
        || named.uid() != opened.uid()
        || named.mode() != opened.mode()
        || named.len() != opened.len()
    {
        return Err(EvidenceFrontierBackendError::Invalid(
            "publication journal was replaced during acknowledgement recovery".to_string(),
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "recovery_tests.rs"]
mod tests;
