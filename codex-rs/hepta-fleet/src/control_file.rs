//! Reads supervisor-owned control state through a bounded, identity-bound handle.
//!
//! Unix trusts the Fleet root's owner and root, not the reader's effective UID.
//! This excludes other-UID entry replacement and writes; an equivalent owner
//! remains trusted. Hard-link publication/recovery is deliberately supported.

use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;

use sha2::Digest;
use sha2::Sha256;

use crate::FleetRegistryError;

#[derive(Clone, Debug)]
pub(crate) struct ControlRoot {
    namespace: DirectoryGuard,
}

impl ControlRoot {
    pub(crate) fn capture(path: &Path) -> Result<Self, FleetRegistryError> {
        let canonical = path.canonicalize()?;
        let metadata = std::fs::symlink_metadata(path)?;
        let namespace = DirectoryGuard::capture(path, &canonical, &metadata)?;
        Ok(Self { namespace })
    }

    pub(crate) fn directory(&self, path: &Path) -> Result<DirectoryGuard, FleetRegistryError> {
        self.namespace.verify()?;
        let directory = DirectoryGuard::capture(
            path,
            &self.namespace.canonical,
            &self.namespace.directories[0].1,
        )?;
        self.namespace.verify()?;
        Ok(directory)
    }

    pub(crate) fn read(&self, path: &Path, maximum: u64) -> Result<Vec<u8>, FleetRegistryError> {
        ControlFile::inspect(self, path, maximum)?.read()
    }

    pub(crate) fn sha256(&self, path: &Path) -> Result<String, FleetRegistryError> {
        let inspected = ControlFile::inspect(self, path, u64::MAX - 1)?;
        let file = inspected.open()?;
        let mut input = (&file).take(inspected.metadata.len() + 1);
        let mut hasher = Sha256::new();
        let mut buffer = [0_u8; 64 * 1024];
        let mut length = 0_u64;
        loop {
            let count = input.read(&mut buffer)?;
            if count == 0 {
                break;
            }
            length += count as u64;
            hasher.update(&buffer[..count]);
        }
        inspected.verify(&file)?;
        if length != inspected.metadata.len() {
            return Err(corrupt(path, "control file changed while hashing"));
        }
        Ok(hasher
            .finalize()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect())
    }
}

#[derive(Clone, Debug)]
pub(crate) struct DirectoryGuard {
    path: PathBuf,
    canonical: PathBuf,
    root: PathBuf,
    owner: Metadata,
    directories: Vec<(PathBuf, Metadata)>,
}

impl DirectoryGuard {
    fn capture(path: &Path, root: &Path, owner: &Metadata) -> Result<Self, FleetRegistryError> {
        let metadata = std::fs::symlink_metadata(path)?;
        let canonical = path.canonicalize()?;
        if !canonical.starts_with(root) {
            return Err(corrupt(path, "directory escaped the Fleet root"));
        }
        if !metadata.is_dir() || metadata.file_type().is_symlink() {
            return Err(corrupt(path, "control path is not a physical directory"));
        }
        let mut directories = Vec::new();
        for directory in canonical.ancestors() {
            let metadata = std::fs::symlink_metadata(directory)?;
            if !metadata.is_dir() || metadata.file_type().is_symlink() {
                return Err(corrupt(
                    directory,
                    "control ancestor is not a physical directory",
                ));
            }
            #[cfg(unix)]
            {
                use std::os::unix::fs::MetadataExt;
                let sticky_ancestor = !directory.starts_with(root) && metadata.mode() & 0o1000 != 0;
                if (metadata.uid() != owner.uid() && metadata.uid() != 0)
                    || (metadata.mode() & 0o022 != 0 && !sticky_ancestor)
                {
                    return Err(corrupt(
                        directory,
                        "control namespace permits untrusted replacement",
                    ));
                }
            }
            directories.push((directory.to_path_buf(), metadata));
        }
        Ok(Self {
            path: path.to_path_buf(),
            canonical,
            root: root.to_path_buf(),
            owner: owner.clone(),
            directories,
        })
    }

    pub(crate) fn verify(&self) -> Result<(), FleetRegistryError> {
        let after = Self::capture(&self.path, &self.root, &self.owner)?;
        if self.canonical != after.canonical
            || self.directories.len() != after.directories.len()
            || !self.directories.iter().zip(&after.directories).all(
                |((path, before), (after_path, after))| {
                    path == after_path && same_directory(before, after)
                },
            )
        {
            return Err(corrupt(&self.path, "control directory identity changed"));
        }
        Ok(())
    }
}

struct ControlFile {
    path: PathBuf,
    canonical: PathBuf,
    metadata: Metadata,
    namespace: DirectoryGuard,
    maximum: u64,
}

impl ControlFile {
    fn inspect(root: &ControlRoot, path: &Path, maximum: u64) -> Result<Self, FleetRegistryError> {
        let parent = path
            .parent()
            .ok_or_else(|| corrupt(path, "control file has no parent"))?;
        let namespace = root.directory(parent)?;
        let metadata = std::fs::symlink_metadata(path)?;
        if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > maximum {
            return Err(corrupt(
                path,
                "control file is not a bounded non-symlink regular file",
            ));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if (metadata.uid() != root.namespace.owner.uid() && metadata.uid() != 0)
                || metadata.mode() & 0o022 != 0
            {
                return Err(corrupt(path, "control file permits an untrusted writer"));
            }
        }
        let canonical = path.canonicalize()?;
        if canonical.parent() != Some(namespace.canonical.as_path()) {
            return Err(corrupt(path, "control file changed its canonical parent"));
        }
        Ok(Self {
            path: path.to_path_buf(),
            canonical,
            metadata,
            namespace,
            maximum,
        })
    }

    fn open(&self) -> Result<File, FleetRegistryError> {
        self.namespace.verify()?;
        let mut options = OpenOptions::new();
        options.read(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            // NONBLOCK makes a regular->FIFO replacement fail without waiting
            // for a writer; NOFOLLOW rejects replacement by a final symlink.
            options.custom_flags(libc::O_NONBLOCK | libc::O_NOFOLLOW);
        }
        let file: File = options.open(&self.canonical)?;
        if !file.metadata()?.is_file() || !same_file(&self.metadata, &file.metadata()?) {
            return Err(corrupt(&self.path, "control file changed while opening"));
        }
        Ok(file)
    }

    fn read(self) -> Result<Vec<u8>, FleetRegistryError> {
        let file = self.open()?;
        let limit = self
            .maximum
            .checked_add(1)
            .ok_or_else(|| corrupt(&self.path, "control byte bound overflows"))?;
        let capacity = usize::try_from(self.metadata.len().min(self.maximum))
            .map_err(|_| corrupt(&self.path, "control file is too large for this platform"))?;
        let mut bytes = Vec::with_capacity(capacity);
        (&file).take(limit).read_to_end(&mut bytes)?;
        self.verify(&file)?;
        if bytes.len() as u64 != self.metadata.len() || bytes.len() as u64 > self.maximum {
            return Err(corrupt(&self.path, "control file changed while reading"));
        }
        Ok(bytes)
    }

    fn verify(&self, file: &File) -> Result<(), FleetRegistryError> {
        let after = std::fs::symlink_metadata(&self.path)?;
        self.namespace.verify()?;
        if self.path.canonicalize()? != self.canonical
            || after.file_type().is_symlink()
            || !after.is_file()
            || !same_file(&self.metadata, &after)
            || !same_file(&self.metadata, &file.metadata()?)
        {
            return Err(corrupt(&self.path, "control file changed while reading"));
        }
        Ok(())
    }
}

#[cfg(unix)]
fn same_directory(before: &Metadata, after: &Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;
    (before.dev(), before.ino(), before.uid(), before.mode())
        == (after.dev(), after.ino(), after.uid(), after.mode())
}

#[cfg(not(unix))]
fn same_directory(before: &Metadata, after: &Metadata) -> bool {
    before.created().ok() == after.created().ok()
        && before.permissions().readonly() == after.permissions().readonly()
}

fn same_file(before: &Metadata, after: &Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if !same_directory(before, after)
            || (
                before.mtime(),
                before.mtime_nsec(),
                before.ctime(),
                before.ctime_nsec(),
            ) != (
                after.mtime(),
                after.mtime_nsec(),
                after.ctime(),
                after.ctime_nsec(),
            )
        {
            return false;
        }
    }
    #[cfg(not(unix))]
    if !same_directory(before, after) || before.modified().ok() != after.modified().ok() {
        return false;
    }
    before.len() == after.len()
}

fn corrupt(path: &Path, reason: &str) -> FleetRegistryError {
    FleetRegistryError::Corrupt(format!("{reason}: {}", path.display()))
}

#[cfg(all(test, unix))]
#[path = "control_file_tests.rs"]
mod tests;
