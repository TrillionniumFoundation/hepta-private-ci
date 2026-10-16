//! Live, read-only observation through the original artifact owner semantics.
use super::*;
#[cfg(any(target_os = "linux", target_os = "macos"))]
use std::collections::BTreeSet;
#[cfg(any(target_os = "linux", target_os = "macos"))]
use std::time::Duration;
#[cfg(any(target_os = "linux", target_os = "macos"))]
use std::time::Instant;

/// Does not acquire the lifetime writer fence or publish artifacts. Each read
/// holds the original owner's short observation fence through ACK reconciliation
/// and CURRENT verification. It can coexist with a live named writer.
/// This profile supports Linux and macOS; other platforms fail closed before
/// opening the owner store. The existing named writer retains its own platform
/// contract and is not disabled by this reader restriction.
pub struct ArtifactOwnerCurrentReaderV1 {
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    root: PathBuf,
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    verifier: ArtifactOwnerVerifierV1,
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    required_current_head: SignedCurrentArtifactHeadV1,
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    observation_fence: File,
}

impl ArtifactOwnerCurrentReaderV1 {
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    pub fn open(
        root: impl AsRef<Path>,
        trust: ArtifactOwnerTrustV1,
        required_current_head: SignedCurrentArtifactHeadV1,
    ) -> Result<Self, ArtifactOwnerHostError> {
        let root = root.as_ref();
        if !root.is_absolute()
            || root.canonicalize()? != root
            || fs::symlink_metadata(root)?.file_type().is_symlink()
        {
            return Err(ArtifactOwnerHostError::CurrentObservationFence);
        }
        let observation_fence = owner_observation::open_existing(root)?;
        Ok(Self {
            root: root.to_owned(),
            verifier: ArtifactOwnerVerifierV1::new(trust)?,
            required_current_head,
            observation_fence,
        })
    }

    #[cfg(any(target_os = "linux", target_os = "macos"))]
    pub fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        let deadline = Instant::now() + Duration::from_millis(250);
        let _guard = loop {
            match owner_observation::acquire_exclusive(&self.root, &self.observation_fence) {
                Ok(guard) => break guard,
                Err(ArtifactOwnerHostError::CurrentObservationBusy)
                    if Instant::now() < deadline =>
                {
                    std::thread::sleep(Duration::from_millis(2));
                }
                Err(error) => return Err(error),
            }
        };
        let store = owner_current_store::CurrentArtifactStoreV1 {
            root: &self.root,
            verifier: &self.verifier,
            required_current_head: Some(&self.required_current_head),
        };
        let mut operations = BTreeSet::new();
        for checkpoint in read_checkpoint_entries(&self.root)? {
            operations.insert(checkpoint.operation_id);
            if operations.len() > MAX_HEAD_RECORDS {
                return Err(ArtifactOwnerHostError::Capacity);
            }
        }
        for operation in operations {
            let recovered = store
                .recover_publication(&operation)?
                .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
            if recovered.checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged {
                return Err(ArtifactOwnerHostError::CurrentObservationUnsettled);
            }
            // After a crash readable ACK bytes may not have been synced. This
            // is an actual durability barrier while holding exclusive O, not a
            // promotion based on readable phase or a fabricated acknowledgement.
            let path = store.checkpoint_path(&operation, ArtifactPublicationPhaseV1::Acknowledged);
            let file = owner_observation::open_regular_existing(&path, MAX_SMALL_RECORD_BYTES)?;
            file.sync_all()
                .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
            File::open(
                path.parent()
                    .ok_or(ArtifactOwnerHostError::InternalInvariant)?,
            )?
            .sync_all()
            .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
        }
        let result = store.current_registry_view(now)?;
        owner_observation::validate_pinned(&self.root, &self.observation_fence)?;
        Ok(result)
    }

    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    pub fn open(
        _root: impl AsRef<Path>,
        _trust: ArtifactOwnerTrustV1,
        _required_current_head: SignedCurrentArtifactHeadV1,
    ) -> Result<Self, ArtifactOwnerHostError> {
        Err(ArtifactOwnerHostError::UnsupportedObservationPlatform)
    }

    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    pub fn current_registry_view(
        &self,
        _now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        Err(ArtifactOwnerHostError::UnsupportedObservationPlatform)
    }
}
