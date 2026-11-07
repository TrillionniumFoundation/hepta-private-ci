#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use std::path::Path;
use std::path::PathBuf;
use std::sync::OnceLock;

#[cfg(windows)]
use pretty_assertions::assert_eq;
use tempfile::TempDir;

/// Resolve one installed OpenSSH executable for fixture generation only.
/// Production trust verification deliberately keeps its original binary policy.
pub(crate) fn openssh_keygen() -> &'static Path {
    static EXECUTABLE: OnceLock<PathBuf> = OnceLock::new();
    EXECUTABLE.get_or_init(|| {
        let mut candidates = Vec::new();
        #[cfg(windows)]
        let executable = "ssh-keygen.exe";
        #[cfg(not(windows))]
        let executable = "ssh-keygen";
        #[cfg(windows)]
        if let Some(system_root) = std::env::var_os("SystemRoot") {
            candidates.push(
                PathBuf::from(system_root)
                    .join("System32/OpenSSH")
                    .join(executable),
            );
        }
        #[cfg(not(windows))]
        candidates.push(PathBuf::from("/usr/bin/ssh-keygen"));
        if let Some(path) = std::env::var_os("PATH") {
            candidates.extend(
                std::env::split_paths(&path).map(|directory| directory.join(executable)),
            );
        }
        let resolved = candidates
            .into_iter()
            .filter(|path| path.is_absolute())
            .find_map(|path| path.canonicalize().ok().filter(|resolved| resolved.is_file()))
            .unwrap_or_else(|| {
                panic!("signing fixtures require OpenSSH {executable}; not found in platform directory or absolute PATH")
            });
        eprintln!("HEPTA_FIXTURE_OPENSSH_KEYGEN={}", resolved.display());
        resolved
    })
}

/// Keep fixture subprocesses on the resolved OpenSSH executable and supply
/// the one OS-owned location required by Win32 OpenSSH during initialization.
pub(crate) fn openssh_command() -> std::process::Command {
    let command = std::process::Command::new(openssh_keygen());
    #[cfg(windows)]
    let command = {
        use std::ffi::OsString;
        use std::os::windows::ffi::OsStringExt as _;

        use windows_sys::Win32::UI::Shell::GetAllUsersProfileDirectoryW;

        // Match the production verifier's bounded OS query. Do not guess a
        // drive or reuse a possibly absent caller-provided environment value.
        let mut buffer = vec![0_u16; 32_768];
        let mut capacity = buffer.len() as u32;
        // SAFETY: both pointers remain valid for this synchronous query and
        // the buffer has the stated number of writable UTF-16 elements.
        if unsafe { GetAllUsersProfileDirectoryW(buffer.as_mut_ptr(), &mut capacity) } == 0 {
            panic!(
                "query fixture ProgramData: {}",
                std::io::Error::last_os_error()
            );
        }
        let Some(length) = buffer
            .iter()
            .position(|character| *character == 0)
            .filter(|length| *length > 0)
        else {
            panic!("fixture ProgramData path is empty or exceeds its bound");
        };
        let path = PathBuf::from(OsString::from_wide(&buffer[..length]));
        assert!(
            path.is_absolute(),
            "fixture ProgramData path must be absolute"
        );
        let mut command = command;
        command.env("ProgramData", path);
        command
    };
    command
}

#[cfg(not(windows))]
pub(crate) type PrivateTempDir = TempDir;

#[cfg(windows)]
#[derive(Debug)]
pub(crate) struct PrivateTempDir {
    _temporary: TempDir,
    path: PathBuf,
}

#[cfg(windows)]
impl PrivateTempDir {
    pub(crate) fn path(&self) -> &Path {
        &self.path
    }
}

pub(crate) fn private_tempdir(label: &str) -> PrivateTempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    #[cfg(windows)]
    {
        let path = temporary.path().join("private");
        drop(
            codex_utils_path::create_private_state_directory(&path)
                .unwrap_or_else(|error| panic!("secure {label}: {error}")),
        );
        PrivateTempDir {
            _temporary: temporary,
            path,
        }
    }
    #[cfg(not(windows))]
    temporary
}

#[cfg(windows)]
pub(crate) fn private_generated_signature(path: &Path) -> PathBuf {
    use std::fs::File;
    use std::fs::OpenOptions;
    use std::io::Read as _;
    use std::os::windows::fs::OpenOptionsExt;

    use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
    use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
    use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
    use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;

    // Preserve the external signer's original output. Its default owner/ACL
    // need not satisfy private-state policy. Pin its directory and exact file
    // against replacement and writes before publishing the same signature bytes.
    let parent = path
        .parent()
        .unwrap_or_else(|| panic!("external test signature has no parent"));
    let _directory = codex_utils_path::open_existing_private_state_directory(parent)
        .unwrap_or_else(|error| panic!("pin external test signature directory: {error}"));
    let mut options = OpenOptions::new();
    options
        .read(true)
        .share_mode(FILE_SHARE_READ)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
    let file = options
        .open(path)
        .unwrap_or_else(|error| panic!("pin external test signature: {error}"));
    let observe = |file: &File| {
        let info = winapi_util::file::information(file)
            .unwrap_or_else(|error| panic!("observe external test signature: {error}"));
        assert_eq!(
            info.file_attributes()
                & u64::from(FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT),
            0,
            "external test signature must be a regular non-reparse file"
        );
        assert_eq!(
            info.number_of_links(),
            1,
            "external signature must have one link"
        );
        assert!(
            info.file_size() <= 4 * 1024,
            "signature exceeds the original bound"
        );
        (
            info.volume_serial_number(),
            info.file_index(),
            info.number_of_links(),
            info.file_size(),
            info.file_attributes(),
            info.creation_time(),
            info.last_write_time(),
        )
    };
    let expected_identity = observe(&file);
    let mut bytes = Vec::new();
    (&file)
        .take(4 * 1024 + 1)
        .read_to_end(&mut bytes)
        .unwrap_or_else(|error| panic!("read bounded test signature: {error}"));
    assert!(
        bytes.len() <= 4 * 1024,
        "test signature exceeds the original bound"
    );
    assert_eq!(bytes.len() as u64, expected_identity.3);
    let current_path = options
        .open(path)
        .unwrap_or_else(|error| panic!("reopen external test signature: {error}"));
    assert_eq!(observe(&file), expected_identity);
    assert_eq!(observe(&current_path), expected_identity);

    let mut destination = path.as_os_str().to_os_string();
    destination.push(".private");
    let destination = PathBuf::from(destination);
    crate::durable::write_private_new(&destination, &bytes)
        .unwrap_or_else(|error| panic!("retain private test signature: {error}"));
    let retained = crate::durable::secure_read(&destination, bytes.len())
        .unwrap_or_else(|error| panic!("read back private test signature: {error}"));
    assert!(
        retained == bytes,
        "private signature must preserve the external bytes"
    );
    assert_eq!(observe(&file), expected_identity);
    assert_eq!(observe(&current_path), expected_identity);
    // Both original file pins remain held through the copy and readback. The
    // original signature is never rewritten, chmodded, renamed, or removed.
    destination
}
