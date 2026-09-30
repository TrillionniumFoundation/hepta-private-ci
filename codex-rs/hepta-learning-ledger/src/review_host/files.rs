//! Host-authorized root custody. Read handles never follow untrusted path components.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Component;
use std::path::Path;

pub(super) type ReviewResult<T> = Result<T, Box<dyn std::error::Error>>;

#[derive(Clone, Copy)]
pub(super) enum Access {
    Private,
    Immutable,
}

pub(super) fn root_directory(path: &Path) -> ReviewResult<File> {
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::CurDir | Component::ParentDir))
    {
        return Err("custody paths must be canonical absolute paths".into());
    }
    for ancestor in path.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err(format!("unprotected custody directory: {}", ancestor.display()).into());
        }
    }
    let directory = File::open(path)?;
    let metadata = directory.metadata()?;
    if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
        return Err("custody directory changed while opening".into());
    }
    Ok(directory)
}

pub(super) fn root_file(path: &Path, access: Access) -> ReviewResult<File> {
    let parent = path.parent().ok_or("custody file has no parent")?;
    root_directory(parent)?;
    let before = std::fs::symlink_metadata(path)?;
    let mask = match access {
        Access::Private => 0o077,
        Access::Immutable => 0o022,
    };
    if !before.is_file() || before.uid() != 0 || before.nlink() != 1 || before.mode() & mask != 0 {
        return Err(format!("unprotected custody file: {}", path.display()).into());
    }
    let file = File::open(path)?;
    let after = file.metadata()?;
    if before.dev() != after.dev()
        || before.ino() != after.ino()
        || !after.is_file()
        || after.uid() != 0
        || after.nlink() != 1
        || after.mode() & mask != 0
    {
        return Err("custody file changed while opening".into());
    }
    Ok(file)
}

pub(super) fn read_root(path: &Path, maximum: u64, access: Access) -> ReviewResult<Vec<u8>> {
    let file = root_file(path, access)?;
    if file.metadata()?.len() > maximum {
        return Err("custody file exceeds its bound".into());
    }
    let mut bytes = Vec::new();
    file.take(maximum + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum {
        return Err("custody file grew beyond its bound".into());
    }
    Ok(bytes)
}

pub(super) fn mutable_file(path: &Path) -> ReviewResult<File> {
    let before = root_file(path, Access::Private)?.metadata()?;
    let file = OpenOptions::new().read(true).write(true).open(path)?;
    let after = file.metadata()?;
    if before.dev() != after.dev()
        || before.ino() != after.ino()
        || after.uid() != 0
        || after.nlink() != 1
        || after.mode() & 0o077 != 0
    {
        return Err("mutable custody file changed while opening".into());
    }
    Ok(file)
}

pub(super) fn create_private(path: &Path, bytes: &[u8]) -> ReviewResult<File> {
    let parent = path.parent().ok_or("custody file has no parent")?;
    let directory = root_directory(parent)?;
    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    directory.sync_all()?;
    if file.metadata()?.uid() != 0 {
        return Err("custody creation requires the root owner".into());
    }
    Ok(file)
}
