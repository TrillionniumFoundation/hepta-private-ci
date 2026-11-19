//! Host-selected files are opened once before ownership transfers. Reopen has
//! no create fallback; partial fresh initialization is retained for inspection.

use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

use codex_hepta_neuron::JointGenerationProcessFilesV1;

use super::linux::Descriptor;
use super::linux::OpenMode;
use super::linux::invalid;
use crate::AgentdError;

pub(super) struct OwnerFiles {
    pub journal: File,
    pub witness: File,
    pub control: File,
}

fn check_path(path: &Path) -> Result<(), AgentdError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("generation path has no parent"))?;
    if !path.is_absolute() || path.file_name().is_none() || parent.canonicalize()? != parent {
        return Err(invalid(
            "generation paths require absolute canonical parents",
        ));
    }
    Ok(())
}

fn existing(path: &Path) -> Result<Metadata, AgentdError> {
    check_path(path)?;
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(invalid("generation files must be regular and not symlinks"));
    }
    Ok(metadata)
}

fn open_immutable(path: &Path) -> Result<File, AgentdError> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)?;
    if !file.metadata()?.is_file() {
        return Err(invalid("opened generation asset must be a regular file"));
    }
    Ok(file)
}

pub(super) fn read_bounded(path: &Path, limit: u64) -> Result<(Vec<u8>, File), AgentdError> {
    check_path(path)?;
    let mut file = open_immutable(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > limit {
        return Err(invalid(
            "generation descriptor size or file type is invalid",
        ));
    }
    let mut bytes = Vec::new();
    (&mut file).take(limit + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != metadata.len() {
        return Err(invalid("generation descriptor changed while reading"));
    }
    Ok((bytes, file))
}

pub(super) fn open_assets(d: &Descriptor) -> Result<JointGenerationProcessFilesV1, AgentdError> {
    Ok(JointGenerationProcessFilesV1 {
        executable: open_immutable(&d.executable.path)?,
        weights: open_immutable(&d.weights.path)?,
        public: open_immutable(&d.public.path)?,
    })
}

pub(super) fn validate_paths(path: &Path, d: &Descriptor) -> Result<(), AgentdError> {
    let immutable = [path, &d.executable.path, &d.weights.path, &d.public.path];
    let mutable = [&d.journal_path, &d.witness_path, &d.control_path];
    let mut seen = Vec::new();
    for item in immutable {
        let meta = existing(item)?;
        seen.push((item, Some((meta.dev(), meta.ino()))));
    }
    for item in mutable {
        check_path(item)?;
        let metadata = match d.mode {
            OpenMode::Create => match std::fs::symlink_metadata(item) {
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
                Err(error) => return Err(error.into()),
                Ok(_) => {
                    return Err(invalid(
                        "create requires every generation owner file absent",
                    ));
                }
            },
            OpenMode::Reopen => {
                let meta = existing(item)?;
                if item != &d.control_path && meta.len() == 0 {
                    return Err(invalid("reopen refuses an empty journal or witness"));
                }
                Some((meta.dev(), meta.ino()))
            }
        };
        seen.push((item.as_path(), metadata));
    }
    for (i, (left, inode)) in seen.iter().enumerate() {
        for (right, other) in seen.iter().skip(i + 1) {
            if left == right || inode.is_some() && inode == other {
                return Err(invalid("generation input and owner files must not alias"));
            }
        }
    }
    Ok(())
}

enum Access {
    ReadWrite,
    Append,
}

fn open_owner(path: &Path, mode: OpenMode, access: Access) -> Result<File, AgentdError> {
    let mut options = OpenOptions::new();
    options
        .read(true)
        .write(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    if matches!(access, Access::Append) {
        options.append(true);
    }
    if matches!(mode, OpenMode::Create) {
        options.create_new(true).mode(0o600);
    }
    let file = options.open(path)?;
    let meta = file.metadata()?;
    if !meta.is_file() || meta.mode() & 0o022 != 0 {
        return Err(invalid(
            "generation owner file must be regular and not writable by others",
        ));
    }
    Ok(file)
}

pub(super) fn open_owners(d: &Descriptor, immutable: &[&File]) -> Result<OwnerFiles, AgentdError> {
    let mut inodes = Vec::new();
    for file in immutable {
        let meta = file.metadata()?;
        let inode = (meta.dev(), meta.ino());
        if !meta.is_file() || inodes.contains(&inode) {
            return Err(invalid(
                "opened generation inputs must be distinct regular files",
            ));
        }
        inodes.push(inode);
    }
    let journal = open_owner(&d.journal_path, d.mode, Access::ReadWrite)?;
    let witness = open_owner(&d.witness_path, d.mode, Access::ReadWrite)?;
    let control = open_owner(&d.control_path, d.mode, Access::Append)?;
    let files = [&journal, &witness, &control];
    for file in files {
        let meta = file.metadata()?;
        let inode = (meta.dev(), meta.ino());
        if inodes.contains(&inode) {
            return Err(invalid(
                "opened generation input and owner files alias the same inode",
            ));
        }
        inodes.push(inode);
    }
    if matches!(d.mode, OpenMode::Reopen)
        && (journal.metadata()?.len() == 0 || witness.metadata()?.len() == 0)
    {
        return Err(invalid("reopen refuses empty opened journal or witness"));
    }
    if matches!(d.mode, OpenMode::Create) {
        for path in [&d.journal_path, &d.witness_path, &d.control_path] {
            File::open(
                path.parent()
                    .ok_or_else(|| invalid("owner path parent missing"))?,
            )?
            .sync_all()?;
        }
    }
    Ok(OwnerFiles {
        journal,
        witness,
        control,
    })
}
