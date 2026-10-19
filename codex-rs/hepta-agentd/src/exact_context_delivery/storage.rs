//! Descriptor-relative private storage for the single exact-delivery writer.
//! Unix path substitution must never redirect reads, truncation or publication.
use super::*;

#[cfg(unix)]
mod unix {
    use super::*;
    use std::ffi::CString;
    use std::os::fd::AsRawFd;
    use std::os::fd::FromRawFd;
    use std::os::unix::ffi::OsStrExt;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;
    use std::path::Component;

    pub(super) fn open_directory(
        path: &Path,
        create: bool,
    ) -> Result<File, ExactContextDeliveryError> {
        let absolute = if path.is_absolute() {
            path.to_path_buf()
        } else {
            std::env::current_dir()
                .map_err(|_| ExactContextDeliveryError::Unavailable)?
                .join(path)
        };
        let mut directory = open_at(libc::AT_FDCWD, c"/", libc::O_RDONLY | libc::O_DIRECTORY)?;
        for component in absolute.components() {
            let name = match component {
                Component::RootDir | Component::CurDir => continue,
                Component::Normal(name) => CString::new(name.as_bytes()),
                Component::ParentDir => CString::new(".."),
                Component::Prefix(_) => return Err(ExactContextDeliveryError::Unavailable),
            }
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
            if create {
                // SAFETY: the descriptor is owned/live and name is NUL-terminated.
                let result = unsafe { libc::mkdirat(directory.as_raw_fd(), name.as_ptr(), 0o700) };
                if result != 0
                    && std::io::Error::last_os_error().raw_os_error() != Some(libc::EEXIST)
                {
                    return Err(ExactContextDeliveryError::Unavailable);
                }
            }
            directory = open_at(
                directory.as_raw_fd(),
                &name,
                libc::O_RDONLY | libc::O_DIRECTORY,
            )?;
        }
        if create {
            let metadata = directory
                .metadata()
                .map_err(|_| ExactContextDeliveryError::Unavailable)?;
            // SAFETY: geteuid has no arguments or memory preconditions.
            if !metadata.is_dir() || metadata.uid() != unsafe { libc::geteuid() } {
                return Err(ExactContextDeliveryError::Unavailable);
            }
            // Preserve private-root initialization without chmod through a path
            // that could have been replaced after the directory was opened.
            directory
                .set_permissions(std::fs::Permissions::from_mode(0o700))
                .map_err(|_| ExactContextDeliveryError::Unavailable)?;
        }
        validate_private(&directory, /*regular*/ false)?;
        Ok(directory)
    }

    fn open_at(
        fd: i32,
        name: &std::ffi::CStr,
        flags: i32,
    ) -> Result<File, ExactContextDeliveryError> {
        // SAFETY: name is NUL-terminated, fd is live or AT_FDCWD, and the mode
        // argument is supplied for O_CREAT. Ownership transfers exactly once.
        let opened = unsafe {
            libc::openat(
                fd,
                name.as_ptr(),
                flags | libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC,
                0o600,
            )
        };
        if opened < 0 {
            return Err(ExactContextDeliveryError::Unavailable);
        }
        // SAFETY: openat returned a new owned descriptor.
        Ok(unsafe { File::from_raw_fd(opened) })
    }

    pub(super) fn validate_private(
        file: &File,
        regular: bool,
    ) -> Result<(), ExactContextDeliveryError> {
        let metadata = file
            .metadata()
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
        // SAFETY: geteuid has no arguments or memory preconditions.
        let uid = unsafe { libc::geteuid() };
        if metadata.uid() != uid
            || metadata.mode() & 0o077 != 0
            || (regular && (!metadata.is_file() || metadata.nlink() != 1))
            || (!regular && !metadata.is_dir())
        {
            return Err(ExactContextDeliveryError::Unavailable);
        }
        Ok(())
    }

    pub(super) fn same_file(left: &File, right: &File) -> Result<bool, ExactContextDeliveryError> {
        let left = left
            .metadata()
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
        let right = right
            .metadata()
            .map_err(|_| ExactContextDeliveryError::Unavailable)?;
        Ok(left.dev() == right.dev() && left.ino() == right.ino())
    }

    pub(super) fn open_file(
        directory: &File,
        name: &str,
        create: bool,
    ) -> Result<File, ExactContextDeliveryError> {
        let name = CString::new(name).map_err(|_| ExactContextDeliveryError::Unavailable)?;
        let flags = if create {
            libc::O_RDWR | libc::O_CREAT
        } else {
            libc::O_RDONLY
        };
        let file = open_at(directory.as_raw_fd(), &name, flags)?;
        validate_private(&file, /*regular*/ true)?;
        Ok(file)
    }

    pub(super) fn read_state(directory: &File) -> Result<Option<File>, ExactContextDeliveryError> {
        let name = c"context-delivery-v2.json";
        // SAFETY: the pinned directory is live and the name is NUL-terminated.
        let opened = unsafe {
            libc::openat(
                directory.as_raw_fd(),
                name.as_ptr(),
                libc::O_RDONLY | libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC,
            )
        };
        if opened < 0 {
            return if std::io::Error::last_os_error().raw_os_error() == Some(libc::ENOENT) {
                Ok(None)
            } else {
                Err(ExactContextDeliveryError::Unavailable)
            };
        }
        // SAFETY: openat returned a new owned descriptor.
        let file = unsafe { File::from_raw_fd(opened) };
        validate_private(&file, /*regular*/ true)?;
        Ok(Some(file))
    }

    pub(super) fn publish(directory: &File) -> Result<(), ExactContextDeliveryError> {
        // SAFETY: both descriptors are live and both names are NUL-terminated.
        let result = unsafe {
            libc::renameat(
                directory.as_raw_fd(),
                c"context-delivery-v2.next".as_ptr(),
                directory.as_raw_fd(),
                c"context-delivery-v2.json".as_ptr(),
            )
        };
        if result != 0 {
            return Err(ExactContextDeliveryError::Unavailable);
        }
        Ok(())
    }
}

pub(super) struct PrivateDirectory {
    #[cfg(unix)]
    file: File,
    #[cfg(not(unix))]
    root: PathBuf,
}

impl PrivateDirectory {
    pub(super) fn open(root: &Path) -> Result<Self, ExactContextDeliveryError> {
        #[cfg(unix)]
        {
            Ok(Self {
                file: unix::open_directory(root, /*create*/ true)?,
            })
        }
        #[cfg(not(unix))]
        {
            prepare_directory(root)?;
            Ok(Self {
                root: root.to_path_buf(),
            })
        }
    }

    pub(super) fn verify_identity(
        &self,
        root: &Path,
        lock: &File,
    ) -> Result<(), ExactContextDeliveryError> {
        #[cfg(unix)]
        {
            unix::validate_private(&self.file, /*regular*/ false)?;
            let current = unix::open_directory(root, /*create*/ false)?;
            let current_lock = unix::open_file(&self.file, LOCK_FILE, /*create*/ false)?;
            if !unix::same_file(&self.file, &current)? || !unix::same_file(lock, &current_lock)? {
                return Err(ExactContextDeliveryError::Unavailable);
            }
        }
        #[cfg(not(unix))]
        {
            let _ = (root, lock);
        }
        Ok(())
    }

    pub(super) fn open_writer(&self, name: &str) -> Result<File, ExactContextDeliveryError> {
        #[cfg(unix)]
        {
            unix::open_file(&self.file, name, /*create*/ true)
        }
        #[cfg(not(unix))]
        {
            OpenOptions::new()
                .create(true)
                .truncate(false)
                .read(true)
                .write(true)
                .open(self.root.join(name))
                .map_err(|_| ExactContextDeliveryError::Unavailable)
        }
    }

    pub(super) fn read_state(&self) -> Result<Option<File>, ExactContextDeliveryError> {
        #[cfg(unix)]
        {
            unix::read_state(&self.file)
        }
        #[cfg(not(unix))]
        {
            match File::open(self.root.join(STATE_FILE)) {
                Ok(file) => Ok(Some(file)),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
                Err(_) => Err(ExactContextDeliveryError::Unavailable),
            }
        }
    }

    pub(super) fn publish(&self, expected: &File) -> Result<(), ExactContextDeliveryError> {
        #[cfg(unix)]
        {
            let named = unix::open_file(&self.file, NEXT_FILE, /*create*/ false)?;
            if !unix::same_file(expected, &named)? {
                return Err(ExactContextDeliveryError::Unavailable);
            }
            unix::publish(&self.file)?;
            let published = unix::open_file(&self.file, STATE_FILE, /*create*/ false)
                .map_err(|_| ExactContextDeliveryError::IndeterminateDurability)?;
            if !unix::same_file(expected, &published)? {
                return Err(ExactContextDeliveryError::IndeterminateDurability);
            }
            Ok(())
        }
        #[cfg(not(unix))]
        {
            let _ = expected;
            std::fs::rename(self.root.join(NEXT_FILE), self.root.join(STATE_FILE))
                .map_err(|_| ExactContextDeliveryError::Unavailable)
        }
    }

    pub(super) fn sync(&self) -> Result<(), ExactContextDeliveryError> {
        #[cfg(unix)]
        {
            self.file
                .sync_all()
                .map_err(|_| ExactContextDeliveryError::IndeterminateDurability)
        }
        #[cfg(not(unix))]
        {
            sync_directory(&self.root)
        }
    }
}
