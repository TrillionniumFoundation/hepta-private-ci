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

/// Deterministic, one-shot fault injector for owner-state and recovery tests.
///
/// `new(0)` starts disarmed. Tests may call `arm_next` only after a host has
/// completed bootstrap, so a precise production boundary can be failed without
/// depending on the number of bootstrap synchronization calls.
pub struct FaultInjectingArtifactOwnerDurabilityV1 {
    inner: FilesystemArtifactOwnerDurabilityV1,
    fail_on_call: AtomicU64,
    calls: AtomicU64,
}

impl FaultInjectingArtifactOwnerDurabilityV1 {
    #[must_use]
    pub const fn new(fail_on_call: u64) -> Self {
        Self {
            inner: FilesystemArtifactOwnerDurabilityV1,
            fail_on_call: AtomicU64::new(fail_on_call),
            calls: AtomicU64::new(0),
        }
    }

    /// Fail exactly the next durability effect and return its absolute call
    /// number. The fault disarms itself after firing.
    #[must_use]
    pub fn arm_next(&self) -> u64 {
        let target = self.calls.load(Ordering::SeqCst).saturating_add(1);
        self.fail_on_call.store(target, Ordering::SeqCst);
        target
    }

    /// Fail the durability effect `additional_calls` calls from now.
    pub fn arm_after(&self, additional_calls: u64) -> Result<u64, DirectoryDurabilityError> {
        if additional_calls == 0 {
            return Err(DirectoryDurabilityError::InvalidPath);
        }
        let target = self
            .calls
            .load(Ordering::SeqCst)
            .saturating_add(additional_calls);
        self.fail_on_call.store(target, Ordering::SeqCst);
        Ok(target)
    }

    pub fn disarm(&self) {
        self.fail_on_call.store(0, Ordering::SeqCst);
    }

    fn before_effect(&self) -> Result<(), DirectoryDurabilityError> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        let target = self.fail_on_call.load(Ordering::SeqCst);
        if target != 0 && call == target {
            let _ = self
                .fail_on_call
                .compare_exchange(target, 0, Ordering::SeqCst, Ordering::SeqCst);
            Err(DirectoryDurabilityError::Indeterminate)
        } else {
            Ok(())
        }
    }

    #[must_use]
    pub fn calls(&self) -> u64 {
        self.calls.load(Ordering::SeqCst)
    }

    #[must_use]
    pub fn armed_call(&self) -> Option<u64> {
        match self.fail_on_call.load(Ordering::SeqCst) {
            0 => None,
            value => Some(value),
        }
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
        assert_eq!(injector.armed_call(), None);
        assert_eq!(injector.before_effect(), Ok(()));
        assert_eq!(injector.calls(), 3);
    }

    #[test]
    fn fault_injector_can_arm_after_bootstrap() {
        let injector = FaultInjectingArtifactOwnerDurabilityV1::new(0);
        assert_eq!(injector.before_effect(), Ok(()));
        assert_eq!(injector.arm_next(), 2);
        assert_eq!(injector.armed_call(), Some(2));
        assert_eq!(
            injector.before_effect(),
            Err(DirectoryDurabilityError::Indeterminate)
        );
        assert_eq!(injector.armed_call(), None);
        assert_eq!(injector.before_effect(), Ok(()));
    }
}
