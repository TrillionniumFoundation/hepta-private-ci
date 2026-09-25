use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

use crate::error::ShellError;

/// A cloneable verifier for one repository-owned native state root.
///
/// The root carries no Hepta authority. It only ensures that local shell state
/// is held below one absolute, non-redirected, current-principal-private
/// directory before every state transition.
#[derive(Debug, Clone)]
pub struct PrivateStateRoot {
    path: PathBuf,
}

impl PrivateStateRoot {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, ShellError> {
        let path = path.into();
        validate_absolute_local_path(&path)?;
        create_and_verify(&path)?;
        Ok(Self { path })
    }

    pub fn open_existing(path: impl Into<PathBuf>) -> Result<Self, ShellError> {
        let path = path.into();
        validate_absolute_local_path(&path)?;
        verify_existing(&path)?;
        Ok(Self { path })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn verify(&self) -> Result<(), ShellError> {
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
    use std::fs::File;
    use std::os::unix::fs::MetadataExt as _;

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
    let metadata = directory.metadata()?;
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

#[cfg(windows)]
fn verify_existing(path: &Path) -> Result<(), ShellError> {
    codex_hepta_private_state::PrivateStateDirectory::open_existing_directory(path)
        .and_then(|root| root.verify_trust())
        .map_err(|error| {
            ShellError::Security(format!(
                "native private-state root trust changed ({}): {error}",
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
