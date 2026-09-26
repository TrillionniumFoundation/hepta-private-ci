//! Narrow durability port for the artifact-owner control plane.
//!
//! Domain state machines stay independent of a concrete filesystem. The
//! reference host depends on this bounded port for the three external durability
//! effects it owns, which permits deterministic I/O-failure injection without
//! granting a second registry or writer implementation.

use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use crate::DirectoryDurabilityError;
use crate::durable_create_file_beneath;
use crate::sync_artifact_owner_publication_directories;
use crate::sync_directory;

pub trait ArtifactOwnerDurabilityV1: Send + Sync {
    fn sync_publication(
        &self,
        data_root: &Path,
    ) -> Result<(), DirectoryDurabilityError>;

    fn create_control_file(
        &self,
        control_root: &Path,
        relative: &Path,
        bytes: &[u8],
    ) -> Result<PathBuf, DirectoryDurabilityError>;

    fn sync_control_root(
        &self,
        control_root: &Path,
    ) -> Result<(), DirectoryDurabilityError>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct FilesystemArtifactOwnerDurabilityV1;

impl ArtifactOwnerDurabilityV1 for FilesystemArtifactOwnerDurabilityV1 {
    fn sync_publication(
        &self,
        data_root: &Path,
    ) -> Result<(), DirectoryDurabilityError> {
        sync_artifact_owner_publication_directories(data_root)
    }

    fn create_control_file(
        &self,
        control_root: &Path,
        relative: &Path,
        bytes: &[u8],
    ) -> Result<PathBuf, DirectoryDurabilityError> {
        durable_create_file_beneath(control_root, relative, bytes)
    }

    fn sync_control_root(
        &self,
        control_root: &Path,
    ) -> Result<(), DirectoryDurabilityError> {
        sync_directory(control_root)
    }
}

/// Deterministic fault injector for owner-state model and recovery tests.
pub struct FaultInjectingArtifactOwnerDurabilityV1 {
    inner: FilesystemArtifactOwnerDurabilityV1,
    fail_on_call: u64,
    calls: AtomicU64,
}

impl FaultInjectingArtifactOwnerDurabilityV1 {
    #[must_use]
    pub const fn new(fail_on_call: u64) -> Self {
        Self {
            inner: FilesystemArtifactOwnerDurabilityV1,
            fail_on_call,
            calls: AtomicU64::new(0),
        }
    }

    fn before_effect(&self) -> Result<(), DirectoryDurabilityError> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        if self.fail_on_call != 0 && call == self.fail_on_call {
            Err(DirectoryDurabilityError::Indeterminate)
        } else {
            Ok(())
        }
    }

    #[must_use]
    pub fn calls(&self) -> u64 {
        self.calls.load(Ordering::SeqCst)
    }
}

impl ArtifactOwnerDurabilityV1 for FaultInjectingArtifactOwnerDurabilityV1 {
    fn sync_publication(
        &self,
        data_root: &Path,
    ) -> Result<(), DirectoryDurabilityError> {
        self.before_effect()?;
        self.inner.sync_publication(data_root)
    }

    fn create_control_file(
        &self,
        control_root: &Path,
        relative: &Path,
        bytes: &[u8],
    ) -> Result<PathBuf, DirectoryDurabilityError> {
        self.before_effect()?;
        self.inner
            .create_control_file(control_root, relative, bytes)
    }

    fn sync_control_root(
        &self,
        control_root: &Path,
    ) -> Result<(), DirectoryDurabilityError> {
        self.before_effect()?;
        self.inner.sync_control_root(control_root)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fault_injector_fails_exactly_one_selected_effect() {
        let injector = FaultInjectingArtifactOwnerDurabilityV1::new(2);
        assert_eq!(injector.before_effect(), Ok(()));
        assert_eq!(
            injector.before_effect(),
            Err(DirectoryDurabilityError::Indeterminate)
        );
        assert_eq!(injector.before_effect(), Ok(()));
        assert_eq!(injector.calls(), 3);
    }
}
