//! Directory-capability implementation of the owner request journal store.
//!
//! On Linux the store retains an opened root directory and resolves every child
//! with `openat2(RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS |
//! RESOLVE_NO_MAGICLINKS)`. No operation re-resolves an ancestor from an ambient
//! absolute `PathBuf`. New files are created with `EXCL`, synced, and followed by
//! an fsync of the already-open containing directory.
//!
//! Other Unix targets retain the previous `openat`/`NOFOLLOW` implementation for
//! source compatibility, but the profile is explicitly marked unqualified for
//! production durability. Product startup must inspect the exported profile and
//! refuse activation rather than silently degrading path-resolution guarantees.

#[cfg(not(unix))]
use std::fmt;
#[cfg(not(unix))]
use std::path::Path;

#[cfg(not(unix))]
use super::transaction::FsOwnerDurableStoreV1 as LexicalFsOwnerDurableStoreV1;
use super::transaction::OwnerDurableStoreV1;
use super::transaction::OwnerJournalError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OwnerCapabilityStoreProfileV1 {
    LinuxOpenat2,
    UnixOpenatNoFollowUnqualified,
    Unsupported,
}

impl OwnerCapabilityStoreProfileV1 {
    #[must_use]
    pub const fn production_qualified(self) -> bool {
        matches!(self, Self::LinuxOpenat2)
    }
}

#[must_use]
pub const fn owner_capability_store_profile_v1() -> OwnerCapabilityStoreProfileV1 {
    #[cfg(target_os = "linux")]
    {
        OwnerCapabilityStoreProfileV1::LinuxOpenat2
    }
    #[cfg(all(unix, not(target_os = "linux")))]
    {
        OwnerCapabilityStoreProfileV1::UnixOpenatNoFollowUnqualified
    }
    #[cfg(not(unix))]
    {
        OwnerCapabilityStoreProfileV1::Unsupported
    }
}

#[cfg(unix)]
mod unix {
    use std::ffi::OsStr;
    use std::ffi::OsString;
    use std::fs::File;
    use std::io;
    use std::io::Read;
    use std::io::Write;
    use std::os::fd::AsFd;
    use std::os::fd::BorrowedFd;
    use std::os::fd::OwnedFd;
    use std::path::Component;
    use std::path::Path;
    use std::path::PathBuf;

    use rustix::fs::Mode;
    use rustix::fs::OFlags;
    use rustix::fs::fsync;
    use rustix::fs::mkdirat;
    #[cfg(not(target_os = "linux"))]
    use rustix::fs::open;
    #[cfg(not(target_os = "linux"))]
    use rustix::fs::openat;
    #[cfg(target_os = "linux")]
    use rustix::fs::openat2;
    #[cfg(target_os = "linux")]
    use rustix::fs::ResolveFlags;
    #[cfg(target_os = "linux")]
    use rustix::fs::CWD;

    use crate::HostDurabilityError;
    use crate::provision_private_root_v1;

    use super::OwnerCapabilityStoreProfileV1;
    use super::OwnerDurableStoreV1;
    use super::OwnerJournalError;
    use super::owner_capability_store_profile_v1;

    pub struct CapabilityOwnerDurableStoreV1 {
        root_path: PathBuf,
        root: OwnedFd,
    }

    impl std::fmt::Debug for CapabilityOwnerDurableStoreV1 {
        fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            formatter
                .debug_struct("CapabilityOwnerDurableStoreV1")
                .field("root", &self.root_path)
                .field("profile", &self.profile())
                .finish_non_exhaustive()
        }
    }

    impl CapabilityOwnerDurableStoreV1 {
        pub fn open(root: impl AsRef<Path>) -> Result<Self, OwnerJournalError> {
            let root_path =
                provision_private_root_v1(root).map_err(OwnerJournalError::Durability)?;
            let root = open_root(&root_path)?;
            let value = Self { root_path, root };
            for relative in [
                "host",
                "host/requests",
                "host/results",
                "host/audit",
                "host/status",
                "host/backups",
            ] {
                value.ensure_directory(Path::new(relative))?;
            }
            Ok(value)
        }

        #[must_use]
        pub const fn profile(&self) -> OwnerCapabilityStoreProfileV1 {
            owner_capability_store_profile_v1()
        }

        fn with_parent<T>(
            &self,
            relative: &Path,
            operation: impl FnOnce(BorrowedFd<'_>, &OsStr) -> Result<T, OwnerJournalError>,
        ) -> Result<T, OwnerJournalError> {
            let mut components = relative_components(relative)?;
            let leaf = components.pop().ok_or(OwnerJournalError::InvalidPath)?;
            let mut current: Option<OwnedFd> = None;
            for component in components {
                let parent = match current.as_ref() {
                    Some(directory) => directory.as_fd(),
                    None => self.root.as_fd(),
                };
                current = Some(open_directory(parent, &component)?);
            }
            let parent = match current.as_ref() {
                Some(directory) => directory.as_fd(),
                None => self.root.as_fd(),
            };
            operation(parent, &leaf)
        }

        fn ensure_directory_capability(
            &self,
            relative: &Path,
        ) -> Result<(), OwnerJournalError> {
            let components = relative_components(relative)?;
            let mut current: Option<OwnedFd> = None;
            for component in components {
                let parent = match current.as_ref() {
                    Some(directory) => directory.as_fd(),
                    None => self.root.as_fd(),
                };
                let next = match open_directory(parent, &component) {
                    Ok(directory) => directory,
                    Err(OwnerJournalError::Io(error))
                        if error.kind() == io::ErrorKind::NotFound =>
                    {
                        match mkdirat(parent, &component, Mode::from_raw_mode(0o700)) {
                            Ok(()) | Err(rustix::io::Errno::EXIST) => {}
                            Err(error) => return Err(errno_to_io(error).into()),
                        }
                        fsync(parent).map_err(|error| {
                            OwnerJournalError::Durability(HostDurabilityError::Indeterminate(
                                errno_to_io(error),
                            ))
                        })?;
                        open_directory(parent, &component)?
                    }
                    Err(error) => return Err(error),
                };
                current = Some(next);
            }
            Ok(())
        }
    }

    impl OwnerDurableStoreV1 for CapabilityOwnerDurableStoreV1 {
        fn root(&self) -> &Path {
            &self.root_path
        }

        fn ensure_directory(&self, relative: &Path) -> Result<(), OwnerJournalError> {
            self.ensure_directory_capability(relative)
        }

        fn write_new(&self, relative: &Path, bytes: &[u8]) -> Result<(), OwnerJournalError> {
            self.with_parent(relative, |parent, leaf| {
                let descriptor = match open_beneath(
                    parent,
                    leaf,
                    OFlags::WRONLY
                        | OFlags::CREATE
                        | OFlags::EXCL
                        | OFlags::NOFOLLOW
                        | OFlags::CLOEXEC,
                    Mode::from_raw_mode(0o600),
                ) {
                    Ok(descriptor) => descriptor,
                    Err(OwnerJournalError::Io(error))
                        if error.kind() == io::ErrorKind::AlreadyExists =>
                    {
                        return Err(OwnerJournalError::Durability(
                            HostDurabilityError::ExistingTarget,
                        ));
                    }
                    Err(error) => return Err(error),
                };
                let mut file = File::from(descriptor);
                if !file.metadata()?.is_file() {
                    return Err(OwnerJournalError::InvalidPath);
                }
                if let Err(error) = file.write_all(bytes).and_then(|()| file.sync_all()) {
                    return Err(OwnerJournalError::Durability(
                        HostDurabilityError::Indeterminate(error),
                    ));
                }
                drop(file);
                fsync(parent).map_err(|error| {
                    OwnerJournalError::Durability(HostDurabilityError::Indeterminate(
                        errno_to_io(error),
                    ))
                })
            })
        }

        fn read_optional(
            &self,
            relative: &Path,
            maximum_bytes: usize,
        ) -> Result<Option<Vec<u8>>, OwnerJournalError> {
            self.with_parent(relative, |parent, leaf| {
                let descriptor = match open_beneath(
                    parent,
                    leaf,
                    OFlags::RDONLY
                        | OFlags::NOFOLLOW
                        | OFlags::NONBLOCK
                        | OFlags::CLOEXEC,
                    Mode::empty(),
                ) {
                    Ok(descriptor) => descriptor,
                    Err(OwnerJournalError::Io(error))
                        if error.kind() == io::ErrorKind::NotFound =>
                    {
                        return Ok(None);
                    }
                    Err(error) => return Err(error),
                };
                let file = File::from(descriptor);
                let metadata = file.metadata()?;
                if !metadata.is_file() || metadata.len() > maximum_bytes as u64 {
                    return Err(OwnerJournalError::Corrupt);
                }
                let mut bytes = Vec::with_capacity(metadata.len() as usize);
                file.take(maximum_bytes as u64 + 1)
                    .read_to_end(&mut bytes)?;
                if bytes.len() > maximum_bytes {
                    return Err(OwnerJournalError::Corrupt);
                }
                Ok(Some(bytes))
            })
        }
    }

    #[cfg(target_os = "linux")]
    fn open_root(path: &Path) -> Result<OwnedFd, OwnerJournalError> {
        openat2(
            CWD,
            path,
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC,
            Mode::empty(),
            ResolveFlags::NO_SYMLINKS | ResolveFlags::NO_MAGICLINKS,
        )
        .map_err(resolve_errno)
    }

    #[cfg(not(target_os = "linux"))]
    fn open_root(path: &Path) -> Result<OwnedFd, OwnerJournalError> {
        open(
            path,
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::empty(),
        )
        .map_err(resolve_errno)
    }

    #[cfg(target_os = "linux")]
    fn open_beneath(
        parent: BorrowedFd<'_>,
        name: &OsStr,
        flags: OFlags,
        mode: Mode,
    ) -> Result<OwnedFd, OwnerJournalError> {
        openat2(
            parent,
            name,
            flags,
            mode,
            ResolveFlags::BENEATH
                | ResolveFlags::NO_SYMLINKS
                | ResolveFlags::NO_MAGICLINKS,
        )
        .map_err(resolve_errno)
    }

    #[cfg(not(target_os = "linux"))]
    fn open_beneath(
        parent: BorrowedFd<'_>,
        name: &OsStr,
        flags: OFlags,
        mode: Mode,
    ) -> Result<OwnedFd, OwnerJournalError> {
        openat(parent, name, flags, mode).map_err(resolve_errno)
    }

    fn open_directory(
        parent: BorrowedFd<'_>,
        name: &OsStr,
    ) -> Result<OwnedFd, OwnerJournalError> {
        open_beneath(
            parent,
            name,
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::empty(),
        )
    }

    fn relative_components(path: &Path) -> Result<Vec<OsString>, OwnerJournalError> {
        if path.as_os_str().is_empty() || path.is_absolute() {
            return Err(OwnerJournalError::InvalidPath);
        }
        path.components()
            .map(|component| match component {
                Component::Normal(value) => Ok(value.to_os_string()),
                Component::CurDir
                | Component::ParentDir
                | Component::RootDir
                | Component::Prefix(_) => Err(OwnerJournalError::InvalidPath),
            })
            .collect()
    }

    fn resolve_errno(error: rustix::io::Errno) -> OwnerJournalError {
        match error {
            rustix::io::Errno::LOOP
            | rustix::io::Errno::NOTDIR
            | rustix::io::Errno::XDEV => OwnerJournalError::InvalidPath,
            other => OwnerJournalError::Io(errno_to_io(other)),
        }
    }

    fn errno_to_io(error: rustix::io::Errno) -> io::Error {
        io::Error::from_raw_os_error(error.raw_os_error())
    }

    #[cfg(test)]
    mod tests {
        use std::os::unix::fs::symlink;

        use super::*;
        use crate::owner::transaction::OwnerDurableStoreV1;
        use crate::test_support::TestDir;

        #[test]
        fn retained_root_rejects_symlink_ancestors_and_duplicate_final_files() {
            let directory = TestDir::new();
            let store = CapabilityOwnerDurableStoreV1::open(directory.0.join("store"))
                .expect("capability store");
            store
                .write_new(Path::new("host/requests/first.req"), b"first")
                .expect("first create-only write");
            assert!(store
                .write_new(Path::new("host/requests/first.req"), b"changed")
                .is_err());

            let outside = directory.0.join("outside");
            std::fs::create_dir(&outside).expect("outside directory");
            symlink(&outside, directory.0.join("store/host/link")).expect("symlink");
            assert!(matches!(
                store.write_new(Path::new("host/link/escape.req"), b"escape"),
                Err(OwnerJournalError::InvalidPath)
            ));
            assert!(!outside.join("escape.req").exists());
        }

        #[test]
        fn capability_profile_is_explicit() {
            #[cfg(target_os = "linux")]
            assert_eq!(
                owner_capability_store_profile_v1(),
                OwnerCapabilityStoreProfileV1::LinuxOpenat2
            );
            #[cfg(not(target_os = "linux"))]
            assert!(!owner_capability_store_profile_v1().production_qualified());
        }
    }
}

#[cfg(unix)]
pub use unix::CapabilityOwnerDurableStoreV1;

#[cfg(not(unix))]
pub struct CapabilityOwnerDurableStoreV1 {
    inner: LexicalFsOwnerDurableStoreV1,
}

#[cfg(not(unix))]
impl fmt::Debug for CapabilityOwnerDurableStoreV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CapabilityOwnerDurableStoreV1")
            .field("inner", &self.inner)
            .field("profile", &self.profile())
            .finish()
    }
}

#[cfg(not(unix))]
impl CapabilityOwnerDurableStoreV1 {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, OwnerJournalError> {
        Ok(Self {
            inner: LexicalFsOwnerDurableStoreV1::open(root)?,
        })
    }

    #[must_use]
    pub const fn profile(&self) -> OwnerCapabilityStoreProfileV1 {
        owner_capability_store_profile_v1()
    }
}

#[cfg(not(unix))]
impl OwnerDurableStoreV1 for CapabilityOwnerDurableStoreV1 {
    fn root(&self) -> &Path {
        self.inner.root()
    }

    fn ensure_directory(&self, relative: &Path) -> Result<(), OwnerJournalError> {
        self.inner.ensure_directory(relative)
    }

    fn write_new(&self, relative: &Path, bytes: &[u8]) -> Result<(), OwnerJournalError> {
        self.inner.write_new(relative, bytes)
    }

    fn read_optional(
        &self,
        relative: &Path,
        maximum_bytes: usize,
    ) -> Result<Option<Vec<u8>>, OwnerJournalError> {
        self.inner.read_optional(relative, maximum_bytes)
    }
}
