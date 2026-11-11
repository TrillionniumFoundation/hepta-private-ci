//! Independent read-only access to the original Artifact owner's physical
//! CURRENT and withdrawal frontier. A retained signed snapshot is only a floor.

use std::os::unix::fs::MetadataExt;
use std::sync::Mutex;

use super::*;

#[derive(Clone, Debug, Eq, PartialEq)]
struct DirectoryPin {
    relative: &'static str,
    device: u64,
    inode: u64,
    uid: u32,
    mode: u32,
}

struct ReadState {
    floor: SignedCurrentArtifactHeadV1,
    withdrawal: Option<(Digest32, DatasetWithdrawalRegistry)>,
    observed_at: u64,
    fenced: bool,
}

/// This type neither opens the original writer fence nor supplies publication,
/// selection, signing or activation rights. Every use rereads original files.
pub struct LearningArtifactReadViewV1 {
    root: PathBuf,
    consumer_uid: u32,
    directories: Vec<DirectoryPin>,
    verifier: ArtifactOwnerVerifierV1,
    state: Mutex<ReadState>,
}

impl LearningArtifactReadViewV1 {
    pub fn open_original(
        root: PathBuf,
        consumer_uid: u32,
        trust: ArtifactOwnerTrustV1,
        retained_floor: SignedCurrentArtifactHeadV1,
        now: u64,
    ) -> Result<Self, ArtifactOwnerHostError> {
        if !root.is_absolute() || fs::canonicalize(&root)? != root {
            return Err(ArtifactOwnerHostError::PathBoundary);
        }
        let directories = ["", "heads", "transactions", "registries"]
            .into_iter().map(|relative| directory(&root, relative, consumer_uid))
            .collect::<Result<Vec<_>, _>>()?;
        let reader = Self {
            root, consumer_uid, directories,
            verifier: ArtifactOwnerVerifierV1::new(trust)?,
            state: Mutex::new(ReadState {
                floor: retained_floor, withdrawal: None, observed_at: now, fenced: false,
            }),
        };
        reader.read_original_registry(now)?;
        Ok(reader)
    }

    pub fn consumer_uid(&self) -> u32 { self.consumer_uid }

    pub fn trust_digest(&self) -> Digest32 { self.verifier.trust_digest() }

    /// Supply an independently retained floor, then read the actual durable
    /// frontier published by the same original writer. Missing is an error.
    pub fn with_original_withdrawal_floor(
        self,
        binding: Digest32,
        floor: DatasetWithdrawalRegistry,
    ) -> Result<Self, ArtifactOwnerHostError> {
        if binding.is_zero() || floor.scope_digest() != Some(self.verifier.trust.withdrawal_scope_digest) {
            return Err(ArtifactOwnerHostError::CurrentHeadContext);
        }
        {
            let mut state = self.state.try_lock().map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
            if state.fenced || state.withdrawal.is_some() {
                return Err(ArtifactOwnerHostError::Indeterminate);
            }
            state.withdrawal = Some((binding, floor));
        }
        self.read_original_withdrawals()?;
        Ok(self)
    }

    pub fn read_original_registry(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        let mut state = self.state.try_lock().map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
        if state.fenced || now < state.observed_at {
            return Err(ArtifactOwnerHostError::Indeterminate);
        }
        state.fenced = true;
        self.require_directories()?;
        let view = read_view::ArtifactOwnerReadView {
            root: &self.root, verifier: &self.verifier, required_current_head: Some(&state.floor),
        };
        if !view.recovery_required_operations()?.is_empty() {
            return Err(ArtifactOwnerHostError::Indeterminate);
        }
        let before = view.discover_current_head(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        let registry = view.registry_at_current(&before)?;
        let after = view.discover_current_head(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        if before.signed != after.signed || !view.recovery_required_operations()?.is_empty() {
            return Err(ArtifactOwnerHostError::Indeterminate);
        }
        self.require_directories()?;
        state.floor = after.signed;
        state.observed_at = now;
        state.fenced = false;
        Ok(registry)
    }

    pub fn read_original_withdrawals(&self) -> Result<DatasetWithdrawalRegistry, ArtifactOwnerHostError> {
        let mut state = self.state.try_lock().map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
        if state.fenced {
            return Err(ArtifactOwnerHostError::Indeterminate);
        }
        state.fenced = true;
        self.require_directories()?;
        let (binding, floor) = state.withdrawal.as_ref().ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        let current = withdrawal_frontier::read_original(&self.root, *binding)?;
        withdrawal_frontier::require_extension(floor, &current)?;
        self.require_directories()?;
        state.withdrawal = Some((*binding, current.clone()));
        state.fenced = false;
        Ok(current)
    }

    fn require_directories(&self) -> Result<(), ArtifactOwnerHostError> {
        for pin in &self.directories {
            if &directory(&self.root, pin.relative, self.consumer_uid)? != pin {
                return Err(ArtifactOwnerHostError::PathBoundary);
            }
        }
        Ok(())
    }
}

fn directory(
    root: &Path,
    relative: &'static str,
    consumer_uid: u32,
) -> Result<DirectoryPin, ArtifactOwnerHostError> {
    let metadata = fs::symlink_metadata(root.join(relative))?;
    if !metadata.is_dir() || metadata.file_type().is_symlink()
        || metadata.uid() != consumer_uid || metadata.mode() & 0o022 != 0
    {
        return Err(ArtifactOwnerHostError::PathBoundary);
    }
    Ok(DirectoryPin {
        relative, device: metadata.dev(), inode: metadata.ino(),
        uid: metadata.uid(), mode: metadata.mode(),
    })
}
