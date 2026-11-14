#[cfg(not(windows))]
use std::path::Path;
#[cfg(unix)]
use std::path::PathBuf;
use std::process::Command;

use crate::AcceptanceError;

#[cfg(windows)]
#[path = "sshsig_windows.rs"]
mod windows;

#[cfg(windows)]
pub(crate) use windows::VerificationInputs;

pub(crate) fn keygen_command() -> Result<Command, AcceptanceError> {
    #[cfg(windows)]
    let mut command = {
        let system = windows::system_directory()?;
        let mut command = Command::new(system.join("OpenSSH/ssh-keygen.exe"));
        command.current_dir(system);
        command
    };
    #[cfg(not(windows))]
    let mut command = Command::new("/usr/bin/ssh-keygen");
    command.env_clear().env("LANG", "C").env("LC_ALL", "C");
    #[cfg(windows)]
    command.env("SystemRoot", windows::windows_directory()?);
    Ok(command)
}

#[cfg(unix)]
pub(crate) struct VerificationInputs {
    _allowed_signers: std::os::fd::OwnedFd,
    _signature: std::os::fd::OwnedFd,
    allowed_signers_path: PathBuf,
    signature_path: PathBuf,
}

#[cfg(unix)]
impl VerificationInputs {
    pub(crate) fn new(allowed_signers: &[u8], signature: &[u8]) -> Result<Self, AcceptanceError> {
        use std::os::fd::AsRawFd;

        let allowed_signers = inherited_pipe(allowed_signers)?;
        let signature = inherited_pipe(signature)?;
        Ok(Self {
            allowed_signers_path: PathBuf::from(format!("/dev/fd/{}", allowed_signers.as_raw_fd())),
            signature_path: PathBuf::from(format!("/dev/fd/{}", signature.as_raw_fd())),
            _allowed_signers: allowed_signers,
            _signature: signature,
        })
    }

    pub(crate) fn allowed_signers_path(&self) -> &Path {
        &self.allowed_signers_path
    }

    pub(crate) fn signature_path(&self) -> &Path {
        &self.signature_path
    }
}

#[cfg(unix)]
fn inherited_pipe(bytes: &[u8]) -> Result<std::os::fd::OwnedFd, AcceptanceError> {
    use std::fs::File;
    use std::io::Write;
    use std::os::fd::AsRawFd;
    use std::os::fd::FromRawFd;
    use std::os::fd::OwnedFd;

    let mut raw = [-1; 2];
    // SAFETY: pipe writes two new descriptors into this two-element array.
    if unsafe { libc::pipe(raw.as_mut_ptr()) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // SAFETY: successful pipe transferred ownership of both descriptors.
    let read_fd = unsafe { OwnedFd::from_raw_fd(raw[0]) };
    // SAFETY: the second newly owned descriptor is distinct from read_fd.
    let write_fd = unsafe { OwnedFd::from_raw_fd(raw[1]) };
    // SAFETY: fcntl reads and changes flags on the live descriptor, with no pointers.
    let flags = unsafe { libc::fcntl(read_fd.as_raw_fd(), libc::F_GETFD) };
    if flags == -1
        || unsafe {
            libc::fcntl(
                read_fd.as_raw_fd(),
                libc::F_SETFD,
                flags & !libc::FD_CLOEXEC,
            )
        } == -1
    {
        return Err(std::io::Error::last_os_error().into());
    }
    let mut writer = File::from(write_fd);
    writer.write_all(bytes)?;
    drop(writer);
    Ok(read_fd)
}

#[cfg(not(any(unix, windows)))]
pub(crate) struct VerificationInputs;

#[cfg(not(any(unix, windows)))]
impl VerificationInputs {
    pub(crate) fn new(_: &[u8], _: &[u8]) -> Result<Self, AcceptanceError> {
        Err(AcceptanceError::Invalid(
            "OpenSSH SSHSIG verification is unsupported on this platform".to_owned(),
        ))
    }

    pub(crate) fn allowed_signers_path(&self) -> &Path {
        Path::new("")
    }

    pub(crate) fn signature_path(&self) -> &Path {
        Path::new("")
    }
}
