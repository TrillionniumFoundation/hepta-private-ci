//! Bounded journal slots retain an ambiguous operation during emergency containment.

use std::fs::File;
use std::io::ErrorKind;
use std::path::Path;
use std::path::PathBuf;

use crate::DurableMutationStatusV1;
use crate::MutationJournalError;
use crate::SupervisordMutation;

const EMERGENCY_DIRECTORY: &str = "supervisor-emergency-control";

pub(crate) struct OwnedStatus {
    pub(crate) root: PathBuf,
    pub(crate) status: DurableMutationStatusV1,
}

pub(crate) fn admission_root(
    run_root: &Path,
    operation: SupervisordMutation,
) -> Result<PathBuf, MutationJournalError> {
    if operation != SupervisordMutation::Kill {
        return Ok(run_root.to_path_buf());
    }
    let root = run_root.join(EMERGENCY_DIRECTORY);
    let mut builder = std::fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    match builder.create(&root) {
        Ok(()) => File::open(run_root)?.sync_all()?,
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {}
        Err(error) => return Err(error.into()),
    }
    validate_directory(&root)?;
    Ok(root)
}

pub(crate) fn lookup(
    run_root: &Path,
    request_id: u64,
) -> Result<Option<OwnedStatus>, MutationJournalError> {
    if let Some(owned) = read_emergency(run_root)?
        && owned.status.request_id == request_id
    {
        return Ok(Some(owned));
    }
    Ok(crate::read_mutation_status(run_root)?
        .filter(|status| status.request_id == request_id)
        .map(|status| OwnedStatus {
            root: run_root.to_path_buf(),
            status,
        }))
}

pub(crate) fn read_emergency(run_root: &Path) -> Result<Option<OwnedStatus>, MutationJournalError> {
    let root = run_root.join(EMERGENCY_DIRECTORY);
    match validate_directory(&root) {
        Ok(()) => {}
        Err(MutationJournalError::Io(error)) if error.kind() == ErrorKind::NotFound => {
            return Ok(None);
        }
        Err(error) => return Err(error),
    }
    Ok(crate::read_mutation_status(&root)?.map(|status| OwnedStatus { root, status }))
}

fn validate_directory(root: &Path) -> Result<(), MutationJournalError> {
    let metadata = std::fs::symlink_metadata(root)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(MutationJournalError::Invalid(
            "emergency mutation journal is not an owner directory".to_string(),
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "mutation_journal_slots_tests.rs"]
mod tests;
