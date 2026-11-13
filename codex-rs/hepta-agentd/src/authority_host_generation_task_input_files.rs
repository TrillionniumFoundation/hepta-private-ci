//! Check the actual retained descriptors before the original factories open
//! them. No pathname is opened, created, reset or substituted by this module.

use std::collections::BTreeSet;
use std::fs::File;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;

use super::RootHostQ24TaskFilesV1;
use super::TaskFilePurpose;
use super::invalid;
use crate::AgentdError;

#[derive(Clone, Copy)]
enum Access { ReadOnly, ReadWrite, ReadAppend }

pub(super) fn require_descriptors(
    files: &RootHostQ24TaskFilesV1,
    purpose: TaskFilePurpose,
) -> Result<(), AgentdError> {
    let mut identities = BTreeSet::new();
    for (file, access) in [
        (&files.source_journal, Access::ReadWrite),
        (&files.source_witness, Access::ReadWrite),
        (&files.cell_journal, Access::ReadWrite),
        (&files.cell_witness, Access::ReadWrite),
        (&files.inference_control, Access::ReadAppend),
        (&files.model.base, Access::ReadOnly),
        (&files.model.encoder, Access::ReadOnly),
        (&files.model.heads, Access::ReadOnly),
    ] {
        require_one(file, access, &mut identities)?;
    }
    for file in [files.model.organ_adapter.as_ref(), files.model.cell_adapter.as_ref()]
        .into_iter().flatten()
    {
        require_one(file, Access::ReadOnly, &mut identities)?;
    }
    if purpose == TaskFilePurpose::Recover
        && (files.source_journal.metadata()?.len() == 0
            || files.cell_journal.metadata()?.len() == 0
            || files.source_witness.metadata()?.len() < 112
            || files.cell_witness.metadata()?.len() < 112)
    {
        return Err(invalid("task recovery cannot initialize an absent journal or witness history"));
    }
    // A real existing control journal may have no entries before first
    // execution. Its original replay and the same Source/Cell receipts decide
    // whether readback is possible; absence is never translated into Execute.
    Ok(())
}

fn require_one(
    file: &File,
    access: Access,
    identities: &mut BTreeSet<(u64, u64)>,
) -> Result<(), AgentdError> {
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.uid() != 0
        || metadata.mode() & 0o7777 != 0o600 || metadata.nlink() != 1
        || !identities.insert((metadata.dev(), metadata.ino()))
    {
        return Err(invalid("task files must be distinct Root0600 single-link regular descriptors"));
    }
    // SAFETY: F_GETFL observes this borrowed descriptor; ownership stays here.
    let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
    let (mode, append) = match access {
        Access::ReadOnly => (libc::O_RDONLY, 0),
        Access::ReadWrite => (libc::O_RDWR, 0),
        Access::ReadAppend => (libc::O_RDWR, libc::O_APPEND),
    };
    if flags < 0 || flags & libc::O_ACCMODE != mode || flags & libc::O_APPEND != append {
        return Err(invalid("task descriptor access or append mode differs from its fixed role"));
    }
    Ok(())
}
