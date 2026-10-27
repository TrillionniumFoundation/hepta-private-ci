#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use std::path::Path;
use std::path::PathBuf;
use std::sync::OnceLock;

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

/// Generate a new test-only signature with real OpenSSH and private creation.
/// Windows OpenSSH's filename output grants Everyone access independently of
/// the parent's private DACL. Its stdout uses CRLF. Create the private file
/// before filename signing; never repair permissions or normalize signed bytes.
#[cfg(windows)]
pub(crate) fn sign_private_fixture(mut signer: std::process::Command, statement: &Path) -> PathBuf {
    use codex_utils_path::PrivateSecurityIdentity;
    use codex_utils_path::WindowsFileId;
    use std::fs::File;

    let mut signature = statement.as_os_str().to_os_string();
    signature.push(".sig");
    let signature = PathBuf::from(signature);
    let directory = codex_utils_path::RetainedPrivateDirectory::open_existing(
        statement.parent().expect("original private fixture root"),
    )
    .expect("retain original private fixture root without ACL repair");
    let statement_custody = directory
        .open_child(
            statement
                .file_name()
                .expect("original fixture statement name"),
        )
        .expect("retain original statement without concurrent write or replacement");
    let created = directory
        .write_new_child(
            signature.file_name().expect("new fixture signature name"),
            b"",
        )
        .expect("create an absent private signature before invoking OpenSSH");
    let observer = File::open(&signature).expect("inspect own newly private signature");
    let identity = WindowsFileId::inspect(&observer).expect("full native signature identity");
    let security = PrivateSecurityIdentity::inspect(&observer).expect("private owner and DACL");
    drop(created);
    let mut confirmation = statement.as_os_str().to_os_string();
    confirmation.push(".own-signing-confirmation");
    let confirmation = PathBuf::from(confirmation);
    directory
        .write_new_child(confirmation.file_name().unwrap(), b"y\n")
        .expect("create exclusively owned fixture overwrite confirmation");
    let signed = signer
        .arg(statement)
        .stdin(std::process::Stdio::from(
            File::open(confirmation).expect("read own fixture confirmation"),
        ))
        .output()
        .expect("run actual OpenSSH filename signer on original statement");
    assert!(
        signed.status.success(),
        "OpenSSH fixture signer failed: {}",
        String::from_utf8_lossy(&signed.stderr)
    );
    statement_custody
        .verify()
        .expect("original statement remained unchanged");
    let retained = directory
        .lock_existing_child(signature.file_name().unwrap())
        .expect("retain original private signature without ACL repair");
    let after = File::open(&signature).expect("inspect original filename output");
    assert_eq!(WindowsFileId::inspect(&after).unwrap(), identity);
    assert_eq!(WindowsFileId::inspect(&observer).unwrap(), identity);
    assert_eq!(PrivateSecurityIdentity::inspect(&after).unwrap(), security);
    assert_eq!(
        PrivateSecurityIdentity::inspect(&observer).unwrap(),
        security
    );
    let bytes = retained
        .read_bounded(16 * 1024)
        .expect("read unchanged original signature");
    assert!(bytes.starts_with(b"-----BEGIN SSH SIGNATURE-----\n"));
    assert!(bytes.ends_with(b"-----END SSH SIGNATURE-----\n"));
    retained
        .sync_verified()
        .expect("flush original signature and retain identity");
    directory
        .sync_verified()
        .expect("flush original private fixture directory");
    signature
}

pub(crate) struct PrivateTempDir {
    temporary: TempDir,
    #[cfg(windows)]
    _parent: TempDir,
}

impl PrivateTempDir {
    pub(crate) fn path(&self) -> &Path {
        self.temporary.path()
    }
}

pub(crate) fn private_tempdir(label: &str) -> PrivateTempDir {
    #[cfg(windows)]
    {
        let parent = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
        let private_parent = parent.path().join("private-owner");
        // Exercise the actual product bootstrap. Nothing repairs a public
        // existing directory: the absent leaf receives its private DACL at creation.
        codex_utils_path::RetainedPrivateDirectory::create_new(&private_parent)
            .unwrap_or_else(|error| panic!("private bootstrap {label}: {error}"));
        let temporary = TempDir::new_in(private_parent)
            .unwrap_or_else(|error| panic!("private child {label}: {error}"));
        PrivateTempDir {
            temporary,
            _parent: parent,
        }
    }
    #[cfg(not(windows))]
    {
        let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
        #[cfg(unix)]
        std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
            .unwrap_or_else(|error| panic!("secure {label}: {error}"));
        PrivateTempDir { temporary }
    }
}
