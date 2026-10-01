//! Read-time namespace fencing for files provisioned by a trusted operator.
//!
//! The file owner and root are the trusted Unix principals. The immediate
//! parent excludes group/world writes; ancestors allow trusted sticky layouts.
//! This does not isolate a malicious equivalent-UID operator or root and does
//! not lock the namespace after verification.

use std::fs::Metadata;
use std::io;
use std::os::unix::fs::MetadataExt;
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
