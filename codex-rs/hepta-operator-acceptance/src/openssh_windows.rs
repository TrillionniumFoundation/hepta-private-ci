//! Windows OpenSSH verification keeps immutable private input handles alive.
//!
//! The caller performs the strict Rust SSHSIG verification first. This second
//! verifier is the operating system's fixed OpenSSH executable, never PATH or an
//! environment-selected program. Both input paths stay pinned for the entire
//! child lifetime.

use std::ffi::OsString;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::windows::ffi::OsStringExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Mutex;

use codex_utils_path::create_private_state_child;
use codex_utils_path::create_private_state_directory;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_DISPOSITION_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FileDispositionInfo;
use windows_sys::Win32::Storage::FileSystem::SetFileInformationByHandle;
use windows_sys::Win32::System::SystemInformation::GetSystemDirectoryW;

use crate::AcceptanceError;

const DIRECTORY_ATTRIBUTE: u64 = 0x10;
const REPARSE_ATTRIBUTE: u64 = 0x400;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Kind {
    Directory,
    File,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct FileId {
    volume: u64,
    index: u64,
}

fn identity(file: &File, kind: Kind) -> Result<FileId, AcceptanceError> {
    let info = winapi_util::file::information(file)?;
    let attributes = info.file_attributes();
    if attributes & REPARSE_ATTRIBUTE != 0
        || (attributes & DIRECTORY_ATTRIBUTE != 0) != (kind == Kind::Directory)
    {
        return Err(invalid(
            "OpenSSH input or executable is redirected or has an unsafe type",
        ));
    }
    Ok(FileId {
        volume: info.volume_serial_number(),
        index: info.file_index(),
    })
}

/// Owns one newly created object. Cleanup deletes only its original file ID.
struct CreatedPath {
    path: PathBuf,
    id: FileId,
    kind: Kind,
    held: Option<File>,
}

impl Drop for CreatedPath {
    fn drop(&mut self) {
        // A read pin deliberately denies DELETE, including our own cleanup.
        // Release it only after verification, then reopen without following the
        // leaf and compare the original ID before requesting deletion by handle.
        drop(self.held.take());
        let mut options = OpenOptions::new();
        options
            .access_mode(DELETE | FILE_READ_ATTRIBUTES)
            .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS);
        let Ok(file) = options.open(&self.path) else {
            return;
        };
        if identity(&file, self.kind).ok() != Some(self.id) {
            return;
        }
        if self.kind == Kind::File
            && !winapi_util::file::information(&file).is_ok_and(|info| info.number_of_links() == 1)
        {
            return;
        }
        let disposition = FILE_DISPOSITION_INFO { DeleteFile: 1 };
        // SAFETY: this live handle was opened with DELETE, and the exact
        // structure and length remain valid for this synchronous call. A raced
        // pathname can never substitute another object after the ID comparison.
        unsafe {
            SetFileInformationByHandle(
                file.as_raw_handle() as HANDLE,
                FileDispositionInfo,
                (&disposition as *const FILE_DISPOSITION_INFO).cast(),
                std::mem::size_of::<FILE_DISPOSITION_INFO>() as u32,
            );
        }
    }
}

struct PrivateInput {
    owned: CreatedPath,
    expected: Vec<u8>,
}

impl PrivateInput {
    fn create(directory: &CreatedPath, name: &str, bytes: &[u8]) -> Result<Self, AcceptanceError> {
        let parent = directory
            .held
            .as_ref()
            .ok_or_else(|| invalid("OpenSSH private input directory is unavailable"))?;
        let file = create_private_state_child(parent, name)?;
        let mut owned = CreatedPath {
            path: directory.path.join(name),
            id: identity(&file, Kind::File)?,
            kind: Kind::File,
            held: Some(file),
        };
        let writer = owned
            .held
            .as_mut()
            .ok_or_else(|| invalid("OpenSSH private input writer is unavailable"))?;
        writer.write_all(bytes)?;
        writer.sync_all()?;
        drop(owned.held.take());

        // An existing writer or DELETE handle makes this open fail. The brief
        // writer-to-reader transition grants no trust: the new pin must still
        // identify the created object and contain the exact caller-owned bytes.
        let reader = OpenOptions::new()
            .read(true)
            .share_mode(FILE_SHARE_READ)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
            .open(&owned.path)?;
        if identity(&reader, Kind::File)? != owned.id {
            return Err(invalid(
                "OpenSSH private input was replaced before it was frozen",
            ));
        }
        owned.held = Some(reader);
        let input = Self {
            owned,
            expected: bytes.to_vec(),
        };
        input.verify()?;
        Ok(input)
    }

    fn verify(&self) -> Result<(), AcceptanceError> {
        use std::os::windows::fs::FileExt;

        let file = self
            .owned
            .held
            .as_ref()
            .ok_or_else(|| invalid("OpenSSH private input pin is unavailable"))?;
        let info = winapi_util::file::information(file)?;
        if identity(file, Kind::File)? != self.owned.id
            || info.number_of_links() != 1
            || info.file_size() != self.expected.len() as u64
        {
            return Err(invalid(
                "OpenSSH private input identity, size or link count changed",
            ));
        }
        let mut bytes = vec![0; self.expected.len()];
        let mut filled = 0;
        while filled < bytes.len() {
            let count = file.seek_read(&mut bytes[filled..], filled as u64)?;
            if count == 0 {
                return Err(invalid(
                    "OpenSSH private input ended before its exact bound",
                ));
            }
            filled += count;
        }
        if bytes != self.expected {
            return Err(invalid(
                "OpenSSH private input differs from the verified bytes",
            ));
        }
        Ok(())
    }
}

struct Inputs {
    // Rust drops fields in declaration order: children are removed while the
    // retained directory still prevents its name or ancestors being replaced.
    allowed: PrivateInput,
    signature: PrivateInput,
    directory: CreatedPath,
}

impl Inputs {
    fn new(allowed: &[u8], signature: &[u8]) -> Result<Self, AcceptanceError> {
        if allowed.len() > 64 * 1024 || signature.len() > 4 * 1024 {
            return Err(invalid(
                "OpenSSH verification input exceeds its original read bound",
            ));
        }
        let path = std::env::temp_dir().join(format!(
            "hepta-sshsig-{}",
            crate::ceremony::random_hex::<16>()?
        ));
        // Exclusive creation with the original private owner/DACL is atomic.
        // A collision or any reparse component is an error; no existing object
        // is adopted, repaired, overwritten or unlinked.
        let file = create_private_state_directory(&path)?;
        let directory = CreatedPath {
            path: path.canonicalize()?,
            id: identity(&file, Kind::Directory)?,
            kind: Kind::Directory,
            held: Some(file),
        };
        let allowed = PrivateInput::create(&directory, "allowed_signers", allowed)?;
        let signature = PrivateInput::create(&directory, "signature", signature)?;
        Ok(Self {
            allowed,
            signature,
            directory,
        })
    }

    fn verify(&self) -> Result<(), AcceptanceError> {
        let directory = self
            .directory
            .held
            .as_ref()
            .ok_or_else(|| invalid("OpenSSH input directory pin is unavailable"))?;
        if identity(directory, Kind::Directory)? != self.directory.id {
            return Err(invalid("OpenSSH input directory identity changed"));
        }
        self.allowed.verify()?;
        self.signature.verify()
    }
}

struct TrustedOpenSsh {
    path: PathBuf,
    file: File,
    id: FileId,
    // Every ancestor is opened without following reparse points and without
    // DELETE sharing. Writable directory contents do not weaken the file pin.
    _ancestors: Vec<File>,
    system_directory: PathBuf,
}

impl TrustedOpenSsh {
    fn open() -> Result<Self, AcceptanceError> {
        let mut buffer = vec![0_u16; 32_768];
        // SAFETY: the mutable UTF-16 buffer has exactly the supplied capacity.
        let length = unsafe { GetSystemDirectoryW(buffer.as_mut_ptr(), buffer.len() as u32) };
        if length == 0 || length as usize >= buffer.len() {
            return Err(invalid(
                "Windows system directory is unavailable or exceeds its bound",
            ));
        }
        let system_directory = PathBuf::from(OsString::from_wide(&buffer[..length as usize]));
        if !system_directory.is_absolute() {
            return Err(invalid("Windows system directory is not absolute"));
        }
        let path = system_directory.join("OpenSSH").join("ssh-keygen.exe");
        let parent = path
            .parent()
            .ok_or_else(|| invalid("Windows OpenSSH executable has no parent"))?;
        let mut ancestors = Vec::new();
        for directory in parent.ancestors().collect::<Vec<_>>().into_iter().rev() {
            let file = OpenOptions::new()
                .read(true)
                .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
                .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
                .open(directory)?;
            identity(&file, Kind::Directory)?;
            ancestors.push(file);
        }
        let file = OpenOptions::new()
            .read(true)
            .share_mode(FILE_SHARE_READ)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
            .open(&path)?;
        let id = identity(&file, Kind::File)?;
        Ok(Self {
            path,
            file,
            id,
            _ancestors: ancestors,
            system_directory,
        })
    }
}

// This receipt observes the existing inherited-handle path. It does not change
// the child's arguments, environment, working directory, stdio, or custody.
#[cfg(test)]
fn report_inherited_verifier_context(verifier: &TrustedOpenSsh) {
    use sha2::Digest as _;
    use std::os::windows::fs::FileExt;
    use windows_sys::Win32::Foundation::GetHandleInformation;
    use windows_sys::Win32::Storage::FileSystem::GetFileType;

    let executable_sha256 = (|| -> std::io::Result<String> {
        let length = verifier.file.metadata()?.len();
        if length > 64 * 1024 * 1024 {
            return Err(std::io::Error::other(
                "diagnostic executable exceeds 64 MiB read bound",
            ));
        }
        let mut digest = sha2::Sha256::new();
        let mut offset = 0;
        let mut bytes = [0_u8; 64 * 1024];
        while offset < length {
            let wanted = usize::try_from((length - offset).min(bytes.len() as u64)).unwrap();
            let count = verifier.file.seek_read(&mut bytes[..wanted], offset)?;
            if count == 0 {
                return Err(std::io::Error::other(
                    "diagnostic executable ended before its bound",
                ));
            }
            digest.update(&bytes[..count]);
            offset += count as u64;
        }
        Ok(format!("{:x}", digest.finalize()))
    })();
    eprintln!(
        "HEPTA_OPENSSH_DIAGNOSTIC inherited_stdio_unchanged=true executable={:?} file_id={:?} sha256={:?} cwd={:?}",
        verifier.path, verifier.id, executable_sha256, verifier.system_directory
    );
    for (name, handle) in [
        ("stdin", std::io::stdin().as_raw_handle()),
        ("stdout", std::io::stdout().as_raw_handle()),
        ("stderr", std::io::stderr().as_raw_handle()),
    ] {
        let mut flags = 0;
        // SAFETY: these borrowed process handles are observed without mutation
        // or closure. Invalid handles produce diagnostic errors only.
        let ok = unsafe { GetHandleInformation(handle as HANDLE, &mut flags) };
        let error = (ok == 0).then(std::io::Error::last_os_error);
        // SAFETY: GetFileType only observes the same borrowed process handle.
        let kind = unsafe { GetFileType(handle as HANDLE) };
        eprintln!(
            "HEPTA_OPENSSH_DIAGNOSTIC parent_handle={name} file_type={kind} handle_information_ok={ok} flags={flags} error={error:?}"
        );
    }
}

// Verification is serialized for this process. At most one child whose
// termination is unknown can retain its input/executable pins.
static PENDING_VERIFIER: Mutex<Option<ActiveVerifier>> = Mutex::new(None);

struct ActiveVerifier {
    child: Child,
    inputs: Inputs,
    verifier: TrustedOpenSsh,
}

fn reconcile_pending(pending: &mut Option<ActiveVerifier>) -> Result<(), AcceptanceError> {
    let Some(active) = pending.as_mut() else {
        return Ok(());
    };
    if active.child.try_wait()?.is_none() {
        return Err(invalid(
            "previous OpenSSH verifier has not reached a known terminal state",
        ));
    }
    let input_readback = active.inputs.verify();
    let executable_readback =
        identity(&active.verifier.file, Kind::File).map(|id| id == active.verifier.id);
    // Only an observed terminal child can release these exact-object pins.
    drop(pending.take());
    input_readback?;
    if !executable_readback? {
        return Err(invalid("previous OpenSSH executable identity changed"));
    }
    // This call only reconciles the original child. It must not silently repeat
    // the failed verification or launch a replacement child.
    Err(invalid(
        "previous OpenSSH verifier terminated; the failed request was not retried",
    ))
}

pub(crate) fn verify(
    statement: &[u8],
    signature: &[u8],
    allowed_signers: &[u8],
    principal: &str,
    namespace: &str,
) -> Result<(), AcceptanceError> {
    let mut pending = PENDING_VERIFIER
        .lock()
        .map_err(|_| invalid("Windows OpenSSH verifier lifecycle is poisoned"))?;
    reconcile_pending(&mut pending)?;
    let inputs = Inputs::new(allowed_signers, signature)?;
    let verifier = TrustedOpenSsh::open()?;
    inputs.verify()?;
    let system_root = verifier
        .system_directory
        .parent()
        .ok_or_else(|| invalid("Windows system directory has no root"))?;
    #[cfg(test)]
    report_inherited_verifier_context(&verifier);
    let mut child = Command::new(&verifier.path)
        // Diagnose the same original verifier child in tests; production stays quiet.
        .args(if cfg!(test) { &["-vvv"][..] } else { &[][..] })
        .args(["-Y", "verify", "-f"])
        .arg(&inputs.allowed.owned.path)
        .args(["-I", principal, "-n", namespace, "-s"])
        .arg(&inputs.signature.owned.path)
        .env_clear()
        // Windows side-by-side loading needs SystemRoot. Derive it from the
        // trusted OS API, never the caller's environment.
        .env("SystemRoot", system_root)
        .env("LANG", "C")
        .env("LC_ALL", "C")
        .current_dir(&verifier.system_directory)
        .stdin(Stdio::piped())
        .stdout({
            #[cfg(test)]
            {
                Stdio::inherit()
            }
            #[cfg(not(test))]
            {
                Stdio::null()
            }
        })
        .stderr({
            #[cfg(test)]
            {
                Stdio::inherit()
            }
            #[cfg(not(test))]
            {
                Stdio::null()
            }
        })
        .spawn()
        .map_err(|error| {
            invalid(format!(
                "failed to start trusted Windows ssh-keygen: {error}"
            ))
        })?;
    #[cfg(test)]
    eprintln!("HEPTA_OPENSSH_DIAGNOSTIC spawned_child_pid={}", child.id());
    let write_result = match child.stdin.take() {
        Some(mut stdin) => stdin.write_all(statement),
        None => Err(std::io::Error::other(
            "Windows ssh-keygen stdin is unavailable",
        )),
    };
    let status = match child.wait() {
        Ok(status) => status,
        Err(error) => {
            #[cfg(test)]
            eprintln!(
                "HEPTA_OPENSSH_DIAGNOSTIC wait_unknown={error:?}; original_child_and_pins_retained=true"
            );
            // Keep the original Child and its pins in the single process slot.
            // Later calls can only reconcile it until termination is observed.
            *pending = Some(ActiveVerifier {
                child,
                inputs,
                verifier,
            });
            return Err(error.into());
        }
    };
    #[cfg(test)]
    eprintln!(
        "HEPTA_OPENSSH_DIAGNOSTIC child_terminal={status:?} stdin_write_result={write_result:?}"
    );
    write_result?;
    inputs.verify()?;
    if identity(&verifier.file, Kind::File)? != verifier.id {
        return Err(invalid(
            "trusted Windows OpenSSH identity changed during verification",
        ));
    }
    if !status.success() {
        let exit_code = status.code();
        return Err(invalid(format!(
            "trusted Windows OpenSSH SSHSIG verification failed (exit code: {exit_code:?})"
        )));
    }
    Ok(())
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}

#[cfg(test)]
#[path = "openssh_windows_tests.rs"]
mod tests;
