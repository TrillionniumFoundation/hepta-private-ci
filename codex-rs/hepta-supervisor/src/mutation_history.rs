//! Terminal receipts remain queryable after the hot mutation slot is reused.
//! History has fixed sharding and a hard per-shard admission limit; pressure
//! denies a new request rather than forgetting an old replay identity.
use std::io::ErrorKind;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;

use crate::DurableMutationStatusV1;
use crate::MutationJournalError;

pub(crate) const HISTORY: &str = "supervisor-mutation-history-v1";
const MAX_SHARD_ENTRIES: usize = 1024;

fn paths(run_root: &Path, request_id: u64) -> (PathBuf, PathBuf, PathBuf) {
    let hash = Sha256Digest::for_bytes(&request_id.to_be_bytes());
    let archive = run_root.join(HISTORY);
    let shard = archive.join(&hash.as_str()[..2]);
    let receipt = shard.join(format!("{request_id:016x}"));
    (archive, shard, receipt)
}

fn validate_directory(path: &Path) -> Result<(), MutationJournalError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(MutationJournalError::Invalid(
            "mutation history directory".into(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.mode() & 0o077 != 0 {
            return Err(MutationJournalError::Invalid(
                "mutation history permissions".into(),
            ));
        }
        let parent = path
            .parent()
            .ok_or_else(|| MutationJournalError::Invalid("history parent".into()))?;
        if metadata.uid() != std::fs::metadata(parent)?.uid() {
            return Err(MutationJournalError::Invalid(
                "mutation history owner".into(),
            ));
        }
    }
    Ok(())
}

pub(crate) fn lookup(
    run_root: &Path,
    request_id: u64,
) -> Result<Option<DurableMutationStatusV1>, MutationJournalError> {
    let (archive, shard, path) = paths(run_root, request_id);
    for directory in [archive, shard, path.clone()] {
        match validate_directory(&directory) {
            Err(MutationJournalError::Io(error)) if error.kind() == ErrorKind::NotFound => {
                return Ok(None);
            }
            result => result?,
        }
    }
    let status = crate::read_mutation_status(&path)?.ok_or_else(|| {
        MutationJournalError::Invalid("terminal history receipt is missing".into())
    })?;
    if !status.phase.terminal() || status.request_id != request_id {
        return Err(MutationJournalError::IdentityConflict);
    }
    Ok(Some(status))
}

pub(crate) fn preserve(
    run_root: &Path,
    status: &DurableMutationStatusV1,
) -> Result<(), MutationJournalError> {
    if !status.phase.terminal() {
        return Err(MutationJournalError::Unresolved);
    }
    if crate::read_mutation_status(run_root)?.as_ref() != Some(status) {
        return Err(MutationJournalError::IdentityConflict);
    }
    let (archive, shard, destination) = paths(run_root, status.request_id);
    for (directory, parent) in [
        (archive.clone(), run_root.to_path_buf()),
        (shard.clone(), archive),
    ] {
        let mut builder = std::fs::DirBuilder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        match builder.create(&directory) {
            Ok(()) => {
                #[cfg(unix)]
                std::fs::File::open(parent)?.sync_all()?;
            }
            Err(error) if error.kind() == ErrorKind::AlreadyExists => {}
            Err(error) => return Err(error.into()),
        }
        validate_directory(&directory)?;
    }
    let destination_exists = match validate_directory(&destination) {
        Ok(()) => true,
        Err(MutationJournalError::Io(error)) if error.kind() == ErrorKind::NotFound => false,
        Err(error) => return Err(error),
    };
    if destination_exists {
        if let Some(prior) = crate::read_mutation_status(&destination)? {
            if prior != *status {
                return Err(MutationJournalError::IdentityConflict);
            }
            #[cfg(unix)]
            for directory in [
                &destination,
                &shard,
                &run_root.join(HISTORY),
                &run_root.to_path_buf(),
            ] {
                std::fs::File::open(directory)?.sync_all()?;
            }
            return Ok(());
        }
        // A cut after directory creation is repaired only from the still
        // authoritative hot terminal receipt, checked above. Cold lookup
        // itself never treats a missing completed receipt as absence.
    } else {
        let count = std::fs::read_dir(&shard)?
            .take(MAX_SHARD_ENTRIES + 1)
            .try_fold(0usize, |count, entry| entry.map(|_| count + 1))?;
        if count >= MAX_SHARD_ENTRIES {
            return Err(MutationJournalError::Invalid(
                "terminal mutation history shard is full".into(),
            ));
        }
    }
    let mut builder = std::fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    if !destination_exists {
        builder.create(&destination)?;
    }
    crate::mutation_journal::write_mutation_status(&destination, status)?;
    #[cfg(unix)]
    std::fs::File::open(&shard)?.sync_all()?;
    Ok(())
}

#[cfg(test)]
#[path = "mutation_history_tests.rs"]
mod tests;
