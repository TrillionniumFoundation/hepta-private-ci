//! Descriptor-relative directory identity for Root's physical copy only.

use super::super::OwnerRule;
use super::super::SqliteRecoveryError;
use super::super::indeterminate;
use std::ffi::CString;
use std::ffi::OsStr;
use std::ffi::OsString;
use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Component;
use std::path::Path;

pub(super) const OWNER_UID: u32 = 60001;

#[derive(Clone, Copy, Debug)]
pub(super) enum LeafOwner {
    Root,
    RegisteredOwner,
}

#[derive(Debug, Eq, PartialEq)]
struct DirectoryIdentity {
    device: u64,
    inode: u64,
    owner: u32,
    mode: u32,
}

impl DirectoryIdentity {
    fn inspect(metadata: &Metadata) -> Result<Self, SqliteRecoveryError> {
        if !metadata.is_dir() {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            owner: metadata.uid(),
            mode: metadata.mode() & 0o7777,
        })
    }
}

#[derive(Debug)]
struct Directory {
    name: OsString,
    file: File,
    identity: DirectoryIdentity,
}

/// Retains every component, including `/`; directory timestamps may change
/// during our copy, but identity, ownership and permissions may not.
#[derive(Debug)]
pub(super) struct DirectoryChain {
    directories: Vec<Directory>,
}

pub(super) fn require_root() -> Result<(), SqliteRecoveryError> {
    if OwnerRule::CurrentUser.expected_uid()? != 0 {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    Ok(())
}

fn open_root() -> Result<File, SqliteRecoveryError> {
    OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open("/")
        .map_err(indeterminate)
}

impl DirectoryChain {
    pub(super) fn bind(path: &Path, leaf: LeafOwner) -> Result<Self, SqliteRecoveryError> {
        require_root()?;
        if !path.is_absolute()
            || path.as_os_str().as_bytes().len() > 4096
            || path
                .components()
                .collect::<std::path::PathBuf>()
                .as_os_str()
                != path.as_os_str()
        {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        let mut components = path.components();
        if components.next() != Some(Component::RootDir) {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        let file = open_root()?;
        let identity = DirectoryIdentity::inspect(&file.metadata().map_err(indeterminate)?)?;
        let mut directories = vec![Directory {
            name: OsString::from("/"),
            file,
            identity,
        }];
        for component in components {
            let Component::Normal(name) = component else {
                return Err(SqliteRecoveryError::Indeterminate);
            };
            let parent = directories
                .last()
                .ok_or(SqliteRecoveryError::Indeterminate)?;
            let file = open_relative(&parent.file, name, libc::O_RDONLY | libc::O_DIRECTORY)?;
            let identity = DirectoryIdentity::inspect(&file.metadata().map_err(indeterminate)?)?;
            directories.push(Directory {
                name: name.to_os_string(),
                file,
                identity,
            });
        }
        if directories.len() < 2 {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        let last = directories.len() - 1;
        for (index, directory) in directories.iter().enumerate() {
            let expected_uid = match (index == last, leaf) {
                (true, LeafOwner::RegisteredOwner) => OWNER_UID,
                _ => 0,
            };
            if directory.identity.owner != expected_uid
                || directory.identity.mode & 0o022 != 0
                || (index == last && directory.identity.mode != 0o700)
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
        }
        let chain = Self { directories };
        chain.verify()?;
        Ok(chain)
    }

    pub(super) fn directory(&self) -> &File {
        &self.directories.last().expect("bound nonempty chain").file
    }

    pub(super) fn verify(&self) -> Result<(), SqliteRecoveryError> {
        require_root()?;
        for (index, directory) in self.directories.iter().enumerate() {
            let current = if index == 0 {
                open_root()?
            } else {
                open_relative(
                    &self.directories[index - 1].file,
                    &directory.name,
                    libc::O_RDONLY | libc::O_DIRECTORY,
                )?
            };
            for file in [&directory.file, &current] {
                if DirectoryIdentity::inspect(&file.metadata().map_err(indeterminate)?)?
                    != directory.identity
                {
                    return Err(SqliteRecoveryError::Indeterminate);
                }
            }
        }
        Ok(())
    }
}

pub(super) fn name_bytes(name: &OsStr) -> Result<CString, SqliteRecoveryError> {
    if name.as_bytes().len() > 255
        || name.as_bytes().contains(&b'/')
        || !matches!(
            Path::new(name).components().next(),
            Some(Component::Normal(_))
        )
        || Path::new(name).components().count() != 1
    {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    CString::new(name.as_bytes()).map_err(|_| SqliteRecoveryError::Indeterminate)
}

pub(super) fn open_relative(
    directory: &File,
    name: &OsStr,
    flags: libc::c_int,
) -> Result<File, SqliteRecoveryError> {
    let name = name_bytes(name)?;
    // SAFETY: directory and NUL-terminated single-component name stay alive.
    // openat returns a new descriptor; the mode applies only with O_CREAT.
    let fd = unsafe {
        libc::openat(
            directory.as_raw_fd(),
            name.as_ptr(),
            flags | libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK,
            0o600,
        )
    };
    if fd < 0 {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    // SAFETY: this successful new descriptor is transferred exactly once.
    Ok(unsafe { File::from_raw_fd(fd) })
}

pub(super) fn open_owner_file(
    directory: &File,
    name: &OsStr,
    flags: libc::c_int,
) -> Result<File, SqliteRecoveryError> {
    let encoded = name_bytes(name)?;
    let mut metadata = std::mem::MaybeUninit::<libc::stat>::uninit();
    // SAFETY: retained parent/name and writable stat storage remain live.
    let result = unsafe {
        libc::fstatat(
            directory.as_raw_fd(),
            encoded.as_ptr(),
            metadata.as_mut_ptr(),
            libc::AT_SYMLINK_NOFOLLOW,
        )
    };
    if result != 0 {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    // SAFETY: successful fstatat initialized the complete stat above.
    let before = unsafe { metadata.assume_init() };
    if before.st_mode & libc::S_IFMT != libc::S_IFREG
        || before.st_mode & 0o7777 != 0o600
        || before.st_uid != OWNER_UID
        || before.st_nlink != 1
    {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    let file = open_relative(directory, name, flags)?;
    let after = file.metadata().map_err(indeterminate)?;
    // dev_t/ino_t widths differ across supported Unix platforms.
    #[allow(clippy::unnecessary_cast)]
    let before_identity = (before.st_dev as u64, before.st_ino as u64);
    if (after.dev(), after.ino()) != before_identity {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    Ok(file)
}

pub(super) fn require_absent(directory: &File, name: &OsStr) -> Result<(), SqliteRecoveryError> {
    let name = name_bytes(name)?;
    let mut metadata = std::mem::MaybeUninit::<libc::stat>::uninit();
    // SAFETY: the descriptor/name are live; metadata is writable storage for
    // one stat. No uninitialized output is read, including on failure.
    let result = unsafe {
        libc::fstatat(
            directory.as_raw_fd(),
            name.as_ptr(),
            metadata.as_mut_ptr(),
            libc::AT_SYMLINK_NOFOLLOW,
        )
    };
    if result == -1 && std::io::Error::last_os_error().raw_os_error() == Some(libc::ENOENT) {
        Ok(())
    } else {
        Err(SqliteRecoveryError::Indeterminate)
    }
}
