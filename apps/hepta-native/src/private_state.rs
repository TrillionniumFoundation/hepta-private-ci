use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
#[cfg(any(unix, windows))]
use std::sync::Arc;

use crate::error::ShellError;

/// A cloneable verifier for one repository-owned native state root.
///
/// The root carries no Hepta authority. It only ensures that local shell state
/// is held below one absolute, non-redirected, current-principal-private
/// directory before every state transition.
#[derive(Clone)]
pub struct PrivateStateRoot {
    path: PathBuf,
    #[cfg(unix)]
    directory: Arc<std::fs::File>,
    #[cfg(windows)]
    directory: Arc<codex_hepta_private_state::PrivateStateDirectory>,
}

#[derive(Clone, Copy)]
enum ChildMode {
    Open,
    Create,
}

impl std::fmt::Debug for PrivateStateRoot {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("PrivateStateRoot")
            .field("path", &self.path)
            .finish_non_exhaustive()
    }
}

impl PrivateStateRoot {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, ShellError> {
        let path = path.into();
        validate_absolute_local_path(&path)?;
        create_and_verify(&path)?;
        Self::open_existing(path)
    }

    pub fn open_existing(path: impl Into<PathBuf>) -> Result<Self, ShellError> {
        let path = path.into();
        validate_absolute_local_path(&path)?;
        #[cfg(unix)]
        let directory = Arc::new(open_verified_directory(&path)?);
        #[cfg(windows)]
        let directory = Arc::new(
            codex_hepta_private_state::PrivateStateDirectory::open_existing_directory(&path)
                .map_err(|error| {
                    ShellError::Security(format!(
                        "native private-state root trust changed ({}): {error}",
                        path.display()
                    ))
                })?,
        );
        #[cfg(not(any(unix, windows)))]
        verify_existing(&path)?;
        Ok(Self {
            path,
            #[cfg(any(unix, windows))]
            directory,
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub(crate) fn child_open(&self, name: &str) -> Result<Self, ShellError> {
        self.child(name, ChildMode::Open)
    }

    /// Create a private child, or tighten an existing current-user-owned Unix
    /// directory from the older staging layout, using its non-following handle.
    pub(crate) fn child_create(&self, name: &str) -> Result<Self, ShellError> {
        if let Ok(child) = self.child_open(name) {
            return Ok(child);
        }
        self.child(name, ChildMode::Create)
    }

    fn child(&self, name: &str, mode: ChildMode) -> Result<Self, ShellError> {
        let mut components = Path::new(name).components();
        if !matches!(components.next(), Some(Component::Normal(_)))
            || components.next().is_some()
            || name.contains(['\0', '/', '\\'])
        {
            return Err(ShellError::InvalidInput(
                "private-state child must be one normal path component".to_owned(),
            ));
        }
        self.verify()?;
        let path = self.path.join(name);
        #[cfg(unix)]
        let child = {
            if matches!(mode, ChildMode::Create)
                && let Err(error) = rustix::fs::mkdirat(
                    self.directory_handle(),
                    name,
                    rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR | rustix::fs::Mode::XUSR,
                )
                && error != rustix::io::Errno::EXIST
            {
                return Err(std::io::Error::from(error).into());
            }
            let directory: std::fs::File = rustix::fs::openat(
                self.directory_handle(),
                name,
                rustix::fs::OFlags::RDONLY
                    | rustix::fs::OFlags::DIRECTORY
                    | rustix::fs::OFlags::NOFOLLOW
                    | rustix::fs::OFlags::CLOEXEC,
                rustix::fs::Mode::empty(),
            )
            .map_err(std::io::Error::from)?
            .into();
            if matches!(mode, ChildMode::Create) {
                use std::os::unix::fs::MetadataExt as _;
                use std::os::unix::fs::PermissionsExt as _;

                let metadata = directory.metadata()?;
                if !metadata.is_dir() || metadata.uid() != rustix::process::geteuid().as_raw() {
                    return Err(ShellError::Security(
                        "private-state child is not a current-principal directory".to_owned(),
                    ));
                }
                directory.set_permissions(std::fs::Permissions::from_mode(0o700))?;
            }
            verify_directory_metadata(&directory.metadata()?, &path)?;
            Self {
                path,
                directory: Arc::new(directory),
            }
        };
        #[cfg(not(unix))]
        let child = match mode {
            ChildMode::Create => Self::open(path)?,
            ChildMode::Open => Self::open_existing(path)?,
        };
        self.verify()?;
        child.verify()?;
        Ok(child)
    }

    #[cfg(windows)]
    pub(crate) fn verify_file(&self, file: &std::fs::File) -> Result<(), ShellError> {
        self.directory.verify_file(file).map_err(|error| {
            ShellError::Security(format!("native private-state file trust changed: {error}"))
        })
    }

    #[cfg(windows)]
    pub(crate) fn verify_mutable_file(&self, file: &std::fs::File) -> Result<(), ShellError> {
        self.directory.verify_mutable_file(file).map_err(|error| {
            ShellError::Security(format!("native mutable-state file trust changed: {error}"))
        })
    }

    #[cfg(unix)]
    pub(crate) fn directory_handle(&self) -> &std::fs::File {
        &self.directory
    }

    pub fn verify(&self) -> Result<(), ShellError> {
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt as _;
            let current = open_verified_directory(&self.path)?.metadata()?;
            let original = self.directory.metadata()?;
            if current.dev() != original.dev() || current.ino() != original.ino() {
                return Err(ShellError::Security(format!(
                    "native private-state root identity changed: {}",
                    self.path.display()
                )));
            }
            Ok(())
        }
        #[cfg(windows)]
        {
            // The owner keeps a handle without FILE_SHARE_DELETE, so its path
            // cannot be replaced while a root (or one of its clones) is alive.
            self.directory.verify_trust().map_err(|error| {
                ShellError::Security(format!(
                    "native private-state root trust changed ({}): {error}",
                    self.path.display()
                ))
            })
        }
        #[cfg(not(any(unix, windows)))]
        verify_existing(&self.path)
    }
}

fn validate_absolute_local_path(path: &Path) -> Result<(), ShellError> {
    if !path.is_absolute() {
        return Err(ShellError::InvalidInput(
            "native private-state root must be absolute".to_owned(),
        ));
    }
    if path
        .components()
        .any(|component| matches!(component, Component::CurDir | Component::ParentDir))
    {
        return Err(ShellError::InvalidInput(
            "native private-state root cannot contain dot traversal".to_owned(),
        ));
    }
    Ok(())
}

#[cfg(unix)]
fn create_and_verify(path: &Path) -> Result<(), ShellError> {
    use std::os::unix::fs::DirBuilderExt as _;

    if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(path)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(error.into());
    }
    verify_existing(path)
}

#[cfg(unix)]
fn verify_existing(path: &Path) -> Result<(), ShellError> {
    open_verified_directory(path).map(|_| ())
}

#[cfg(unix)]
fn open_verified_directory(path: &Path) -> Result<std::fs::File, ShellError> {
    use std::fs::File;

    let directory: File = rustix::fs::open(
        path,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|error| {
        ShellError::Security(format!(
            "native private-state root is unavailable or redirected ({}): {error}",
            path.display()
        ))
    })?
    .into();
    verify_directory_metadata(&directory.metadata()?, path)?;
    Ok(directory)
}

#[cfg(unix)]
fn verify_directory_metadata(metadata: &std::fs::Metadata, path: &Path) -> Result<(), ShellError> {
    use std::os::unix::fs::MetadataExt as _;

    if !metadata.is_dir()
        || metadata.mode() & 0o777 != 0o700
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(ShellError::Security(format!(
            "native private-state root is not current-principal mode 0700: {}",
            path.display()
        )));
    }
    Ok(())
}

#[cfg(windows)]
fn create_and_verify(path: &Path) -> Result<(), ShellError> {
    codex_hepta_private_state::PrivateStateDirectory::open(path)
        .and_then(|root| root.verify_trust())
        .map_err(|error| {
            ShellError::Security(format!(
                "native private-state root is not a protected local directory ({}): {error}",
                path.display()
            ))
        })
}

#[cfg(not(any(unix, windows)))]
fn create_and_verify(_path: &Path) -> Result<(), ShellError> {
    Err(ShellError::Security(
        "native private-state roots are unsupported on this platform".to_owned(),
    ))
}

#[cfg(not(any(unix, windows)))]
fn verify_existing(_path: &Path) -> Result<(), ShellError> {
    Err(ShellError::Security(
        "native private-state roots are unsupported on this platform".to_owned(),
    ))
}

#[cfg(test)]
#[path = "private_state_child_tests.rs"]
mod child_tests;
