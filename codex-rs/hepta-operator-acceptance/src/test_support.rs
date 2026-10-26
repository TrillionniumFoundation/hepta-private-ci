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
