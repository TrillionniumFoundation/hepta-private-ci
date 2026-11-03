//! Publicly reconstructible genesis, separate from the historical V1 profile.
//! The tensor blob is deliberately reused; compatibility and contract are new.
//! Neither profile can be loaded through the other's selection constructor.

use super::*;

pub const SMOLLM_PUBLIC_INITIAL_PROFILE_V2: &[u8] =
    include_bytes!("../profiles/smollm2-public-initial-v2.profile");
pub const SMOLLM_PUBLIC_INITIAL_CONTRACT_V2: &str =
    "c9b06f9a029a3257801844f89acb59b5f59f6a39087335af323f274e9152992f";

/// Original selected material under the distinct published V2 contract.
/// No external construction, conversion to V1, cloning, or activation exists.
#[derive(Debug)]
pub struct SelectedPublicInitialSmolLmMaterialV2 {
    material: SelectedInitialSmolLmMaterialV1,
}

impl VerifiedArtifactSelectionV1 {
    /// Preserve the exact independently verified selector window and CURRENT
    /// owner while admitting only the public V2 genesis compatibility domain.
    pub fn load_public_initial_smollm_material_v2(
        self,
        snapshot_file: File,
        payload_file: File,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
    ) -> Result<SelectedPublicInitialSmolLmMaterialV2, ArtifactSelectionError> {
        let manifest = &self.pin.manifest;
        if manifest.compatibility_digest != Digest32::of_bytes(SMOLLM_PUBLIC_INITIAL_PROFILE_V2)
            || manifest.kind != crate::ArtifactKind::Parameters
            || manifest.generation.get() != 1
            || manifest.predecessor_id.is_some()
            || manifest.encoded_size_bytes != 933_664
            || manifest.content_digest.to_string()
                != "1c5af7b5a7144a619dfac83b14bd83ae77f1e2227b18a6a9c5dcb214889a0cba"
        {
            return Err(ArtifactSelectionError::InitialGenesisMaterial);
        }
        self.initial_window.validate_at(now)?;
        if current.trust_digest() != self.initial_window.owner_trust_digest {
            return Err(ArtifactSelectionError::OwnerTrustMismatch);
        }
        let window = self.initial_window;
        let selection_digest = self.selection_digest;
        let candidate = load_selected_candidate(snapshot_file, payload_file, self)?;
        let mut material = SelectedInitialSmolLmMaterialV1 {
            candidate,
            selection_digest,
            window,
            last_observed_at: now,
            unavailable: false,
        };
        material.with_current(current, now, |_| ())?;
        Ok(SelectedPublicInitialSmolLmMaterialV2 { material })
    }
}

impl SelectedPublicInitialSmolLmMaterialV2 {
    pub fn manifest(&self) -> &ArtifactManifest {
        self.material.manifest()
    }

    pub const fn selection_digest(&self) -> Digest32 {
        self.material.selection_digest()
    }

    /// Same original fail-closed CURRENT and immutable selector-window owner.
    pub fn with_current<T>(
        &mut self,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
        consume: impl FnOnce(&[u8]) -> T,
    ) -> Result<T, ArtifactSelectionError> {
        self.material.with_current(current, now, consume)
    }
}
