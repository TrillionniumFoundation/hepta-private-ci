//! Read-time namespace fencing for files provisioned by a trusted operator.
//!
//! The file owner and root are the trusted Unix principals. The immediate
//! parent excludes group/world writes; ancestors allow trusted sticky layouts.
//! This does not isolate a malicious equivalent-UID operator or root and does
//! not lock the namespace after verification.

use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

pub(crate) struct OperatorNamespace {
    directories: Vec<(PathBuf, Metadata)>,
}

impl OperatorNamespace {
    pub(crate) fn capture(path: &Path, file: &Metadata) -> io::Result<Self> {
        let parent = path
            .parent()
            .ok_or_else(|| io::Error::other("operator file has no parent"))?;
        if parent.canonicalize()? != parent {
            return Err(io::Error::other(
                "operator file namespace changed its canonical destination",
            ));
        }
        let mut directories = Vec::new();
        for (depth, directory) in parent.ancestors().enumerate() {
            let metadata = std::fs::symlink_metadata(directory)?;
            let writable = metadata.mode() & 0o022 != 0;
            let trusted_sticky_ancestor = depth != 0 && metadata.mode() & 0o1000 != 0;
            if !metadata.is_dir()
                || metadata.file_type().is_symlink()
                || (metadata.uid() != file.uid() && metadata.uid() != 0)
                || (writable && !trusted_sticky_ancestor)
            {
                return Err(io::Error::other(
                    "operator file namespace permits untrusted entry replacement",
                ));
            }
            directories.push((directory.to_path_buf(), metadata));
        }
        Ok(Self { directories })
    }

    pub(crate) fn open_regular(&self, path: &Path, before: &Metadata) -> io::Result<File> {
        if !before.is_file() || before.file_type().is_symlink() || before.nlink() != 1 {
            return Err(io::Error::other("operator read requires a regular file"));
        }
        // A replaced FIFO must not wait for a writer before FD validation,
        // and a substituted symlink must never redirect this inspected read.
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)?;
        let opened = file.metadata()?;
        if !opened.is_file() || file_version(before) != file_version(&opened) {
            return Err(io::Error::other("operator file changed while opening"));
        }
        self.verify(path, &opened)?;
        Ok(file)
    }

    pub(crate) fn verify(&self, path: &Path, file: &Metadata) -> io::Result<()> {
        let after = Self::capture(path, file)?;
        let identity = |metadata: &Metadata| {
            (
                metadata.dev(),
                metadata.ino(),
                metadata.uid(),
                metadata.mode(),
            )
        };
        if self.directories.len() != after.directories.len()
            || !self.directories.iter().zip(&after.directories).all(
                |((before_path, before), (after_path, after))| {
                    before_path == after_path && identity(before) == identity(after)
                },
            )
        {
            return Err(io::Error::other(
                "operator file namespace changed while reading",
            ));
        }
        Ok(())
    }
}

fn file_version(metadata: &Metadata) -> (u64, u64, u32, u32, u64, u64, i64, i64, i64, i64) {
    (
        metadata.dev(),
        metadata.ino(),
        metadata.uid(),
        metadata.mode(),
        metadata.nlink(),
        metadata.len(),
        metadata.mtime(),
        metadata.mtime_nsec(),
        metadata.ctime(),
        metadata.ctime_nsec(),
    )
}

#[cfg(test)]
#[path = "operator_namespace_open_tests.rs"]
mod tests;
