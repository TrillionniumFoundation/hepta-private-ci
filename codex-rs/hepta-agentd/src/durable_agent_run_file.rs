//! Bounded atomic images under one lifetime sidecar lock. Live bytes are checked
//! before every acknowledgement; uncertain storage errors poison this owner.
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use sha2::Digest;
use sha2::Sha256;

use super::AgentRunError;
use super::failure;

const MAX_BYTES: usize = 16 * 1024 * 1024;

#[cfg(all(test, unix))]
#[derive(Clone, Copy)]
pub(super) enum FaultAction {
    Error,
    Crash,
}

pub(super) struct RunFile {
    path: PathBuf,
    lock_path: PathBuf,
    lock: File,
    current: Option<File>,
    expected: Option<[u8; 32]>,
    poisoned: bool,
    #[cfg(unix)]
    directory: File,
    #[cfg(unix)]
    directory_path: PathBuf,
    #[cfg(all(test, unix))]
    fault: Option<(&'static str, FaultAction)>,
}

impl RunFile {
    #[cfg(unix)]
    pub fn open(path: PathBuf) -> Result<(Self, Option<Vec<u8>>), AgentRunError> {
        let name = path
            .file_name()
            .ok_or_else(|| failure("run store filename missing"))?;
        let parent = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .ok_or_else(|| failure("run store parent missing"))?;
        use std::os::unix::fs::OpenOptionsExt;
        let directory_path = fs::canonicalize(parent).map_err(io_error)?;
        let directory = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(&directory_path)
            .map_err(io_error)?;
        verify_directory(&directory, &directory_path)?;
        let path = directory_path.join(name);
        reject_non_file(&path)?;
        let lock_path = path.with_extension("lock");
        let (lock, origin) = acquire_lock(&lock_path)?;
        let mut current = match private_options().open(&path) {
            Ok(file) => Some(file),
            Err(e)
                if e.kind() == std::io::ErrorKind::NotFound
                    && matches!(origin, LockOrigin::Created) =>
            {
                None
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                return Err(failure(
                    "run store image missing behind existing lifecycle lock; restore inspected history before reopening",
                ));
            }
            Err(e) => return Err(io_error(e)),
        };
        let bytes = match current.as_mut() {
            Some(file) => {
                verify_identity(file, &path)?;
                if file.metadata().map_err(io_error)?.len() > MAX_BYTES as u64 {
                    return Err(failure("run store exceeds bound"));
                }
                let mut bytes = Vec::new();
                file.take((MAX_BYTES + 1) as u64)
                    .read_to_end(&mut bytes)
                    .map_err(io_error)?;
                if bytes.len() > MAX_BYTES {
                    return Err(failure("run store grew beyond bound"));
                }
                Some(bytes)
            }
            None => None,
        };
        let expected = bytes.as_ref().map(|b| Sha256::digest(b).into());
        let mut owner = Self {
            path,
            lock_path,
            lock,
            current,
            expected,
            poisoned: false,
            directory,
            directory_path,
            #[cfg(all(test, unix))]
            fault: None,
        };
        owner.verify()?;
        Ok((owner, bytes))
    }

    #[cfg(not(unix))]
    pub fn open(_path: PathBuf) -> Result<(Self, Option<Vec<u8>>), AgentRunError> {
        Err(failure(
            "durable Agentd run-store profile requires Unix retained identity/private permissions; non-Unix qualification is pending",
        ))
    }

    #[cfg(all(test, unix))]
    pub(super) fn fail_at(&mut self, cut: &'static str, action: FaultAction) {
        self.fault = Some((cut, action));
    }

    #[cfg(all(test, unix))]
    fn injected_failure(&self, cut: &'static str) -> Result<(), AgentRunError> {
        if let Some((selected, action)) = self.fault
            && selected == cut
        {
            if matches!(action, FaultAction::Crash) {
                std::process::exit(37);
            }
            return Err(failure(format!("injected persistence failure at {cut}")));
        }
        Ok(())
    }

    pub fn verify(&mut self) -> Result<(), AgentRunError> {
        if self.poisoned {
            return Err(failure(
                "run store owner poisoned; inspected reopen required",
            ));
        }
        let result = self.verify_inner();
        if result.is_err() {
            self.poisoned = true;
        }
        result
    }

    fn verify_inner(&mut self) -> Result<(), AgentRunError> {
        #[cfg(unix)]
        verify_directory(&self.directory, &self.directory_path)?;
        verify_identity(&self.lock, &self.lock_path)?;
        match (self.current.as_mut(), self.expected) {
            (Some(file), Some(expected)) => {
                verify_identity(file, &self.path)?;
                file.seek(SeekFrom::Start(0)).map_err(io_error)?;
                let mut hash = Sha256::new();
                let mut bytes = 0usize;
                let mut buffer = [0u8; 65536];
                loop {
                    let n = file.read(&mut buffer).map_err(io_error)?;
                    if n == 0 {
                        break;
                    }
                    bytes = bytes
                        .checked_add(n)
                        .ok_or_else(|| failure("run store length overflow"))?;
                    if bytes > MAX_BYTES {
                        return Err(failure("run store exceeds bound"));
                    }
                    hash.update(&buffer[..n]);
                }
                let digest: [u8; 32] = hash.finalize().into();
                if digest != expected {
                    return Err(failure("retained run store changed"));
                }
                verify_identity(file, &self.path)
            }
            (None, None) => match fs::symlink_metadata(&self.path) {
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
                _ => Err(failure("run store appeared before initialization")),
            },
            _ => Err(failure("run store retention state inconsistent")),
        }
    }

    pub fn persist(&mut self, bytes: &[u8]) -> Result<(), AgentRunError> {
        if bytes.is_empty() || bytes.len() > MAX_BYTES {
            return Err(failure("run store image outside bound"));
        }
        self.verify()?;
        // One pending slot bounds failed-attempt retention across restarts.
        // Existing pending bytes are never overwritten or removed implicitly.
        let temporary = self.path.with_extension("pending");
        let result = (|| {
            let mut file = private_options()
                .create_new(true)
                .open(&temporary)
                .map_err(io_error)?;
            #[cfg(all(test, unix))]
            self.injected_failure("before_write")?;
            file.write_all(bytes).map_err(io_error)?;
            #[cfg(all(test, unix))]
            self.injected_failure("after_write")?;
            #[cfg(all(test, unix))]
            self.injected_failure("before_flush")?;
            file.flush().map_err(io_error)?;
            #[cfg(all(test, unix))]
            self.injected_failure("before_sync")?;
            file.sync_all().map_err(io_error)?;
            self.verify()?;
            #[cfg(all(test, unix))]
            self.injected_failure("before_rename")?;
            fs::rename(&temporary, &self.path).map_err(io_error)?;
            #[cfg(all(test, unix))]
            self.injected_failure("after_rename")?;
            #[cfg(unix)]
            self.directory.sync_all().map_err(io_error)?;
            #[cfg(all(test, unix))]
            self.injected_failure("after_parent_sync")?;
            self.current = Some(file);
            self.expected = Some(Sha256::digest(bytes).into());
            #[cfg(all(test, unix))]
            self.injected_failure("after_install")?;
            self.verify()
        })();
        if result.is_err() {
            self.poisoned = true;
        }
        // Failed attempts retain their temporary image for inspection. Do not
        // delete a pre-existing/colliding path, stable lock or authoritative
        // image as a recovery shortcut.
        result
    }
}

fn private_options() -> OpenOptions {
    let mut options = OpenOptions::new();
    options.read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    options
}
#[cfg(unix)]
fn reject_non_file(path: &Path) -> Result<bool, AgentRunError> {
    match fs::symlink_metadata(path) {
        Ok(m) if m.file_type().is_file() => Ok(true),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
        _ => Err(failure("run store/lock must be a regular non-symlink file")),
    }
}
fn verify_identity(file: &File, path: &Path) -> Result<(), AgentRunError> {
    let current = fs::symlink_metadata(path).map_err(io_error)?;
    let retained = file.metadata().map_err(io_error)?;
    if !current.file_type().is_file() || !retained.is_file() {
        return Err(failure("run store path is not a regular file"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let valid = current.dev() == retained.dev()
            && current.ino() == retained.ino()
            && retained.uid() == effective_uid()
            && retained.nlink() == 1
            && retained.mode() & 0o777 == 0o600;
        if !valid {
            return Err(failure(
                "run store retained identity or private permissions changed",
            ));
        }
    }
    Ok(())
}
fn io_error(error: std::io::Error) -> AgentRunError {
    failure(format!("run store I/O: {error}"))
}

#[cfg(all(test, not(unix)))]
#[path = "durable_agent_run_nonunix_tests.rs"]
mod nonunix_tests;

#[cfg(unix)]
fn effective_uid() -> u32 {
    // SAFETY: geteuid has no pointer arguments or side effects.
    unsafe { libc::geteuid() }
}

#[cfg(unix)]
fn verify_directory(file: &File, path: &Path) -> Result<(), AgentRunError> {
    use std::os::unix::fs::MetadataExt;
    let current = fs::symlink_metadata(path).map_err(io_error)?;
    let retained = file.metadata().map_err(io_error)?;
    if !current.file_type().is_dir()
        || !retained.is_dir()
        || current.dev() != retained.dev()
        || current.ino() != retained.ino()
        || retained.uid() != effective_uid()
        || retained.mode() & 0o022 != 0
        || retained.mode() & 0o700 != 0o700
    {
        return Err(failure(
            "run store parent must remain owned, stable and non-writable by other users",
        ));
    }
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "durable_agent_run_open_tests.rs"]
mod open_tests;

#[cfg(unix)]
#[derive(Debug, Eq, PartialEq)]
enum LockOrigin {
    Created,
    Existing,
}

#[cfg(unix)]
fn acquire_lock(path: &Path) -> Result<(File, LockOrigin), AgentRunError> {
    reject_non_file(path)?;
    // The kernel's exclusive creation result, not a pre-open existence hint,
    // is the only bootstrap permission for an absent image.
    let (file, origin) = match private_options().create_new(true).open(path) {
        Ok(file) => (file, LockOrigin::Created),
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => (
            private_options().open(path).map_err(io_error)?,
            LockOrigin::Existing,
        ),
        Err(error) => return Err(io_error(error)),
    };
    verify_identity(&file, path)?;
    file.try_lock()
        .map_err(|error| failure(format!("run store owner unavailable: {error}")))?;
    verify_identity(&file, path)?;
    Ok((file, origin))
}
