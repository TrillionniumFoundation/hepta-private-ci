//! The two initial material domains share physical lifecycle owners, not pins.

use super::*;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactSelectionError;
use codex_hepta_learning_artifacts::SMOLLM_PUBLIC_INITIAL_CONTRACT_V2;
use codex_hepta_learning_artifacts::SelectedPublicInitialSmolLmMaterialV2;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;

pub(super) enum InitialMaterial {
    Historical(SelectedInitialSmolLmMaterialV1),
    Public(SelectedPublicInitialSmolLmMaterialV2),
}

impl From<SelectedInitialSmolLmMaterialV1> for InitialMaterial {
    fn from(value: SelectedInitialSmolLmMaterialV1) -> Self {
        Self::Historical(value)
    }
}

impl InitialMaterial {
    pub(super) fn manifest(&self) -> &ArtifactManifest {
        match self {
            Self::Historical(value) => value.manifest(),
            Self::Public(value) => value.manifest(),
        }
    }

    pub(super) fn selection_digest(&self) -> Digest32 {
        match self {
            Self::Historical(value) => value.selection_digest(),
            Self::Public(value) => value.selection_digest(),
        }
    }

    pub(super) fn with_current<T>(
        &mut self,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
        consume: impl FnOnce(&[u8]) -> T,
    ) -> Result<T, ArtifactSelectionError> {
        match self {
            Self::Historical(value) => value.with_current(current, now, consume),
            Self::Public(value) => value.with_current(current, now, consume),
        }
    }

    pub(super) fn validate_load(&self, load: &SmolLmMeasuredLoadV1) -> Result<(), String> {
        match self {
            Self::Historical(_) => load.fixed_initial_backbone().map(|_| ()),
            Self::Public(_) => validate_public_initial_load(load),
        }
    }
}

pub(super) fn validate_public_initial_load(load: &SmolLmMeasuredLoadV1) -> Result<(), String> {
    if load.control_load_ids().is_none()
        || load.contract_digest().to_string() != SMOLLM_PUBLIC_INITIAL_CONTRACT_V2
        || load.backbone_digest().to_string()
            != "c320c094769446c21d7e4a33795d7f9310b5e4c8ca5a6fecca40207b1f735b7c"
        || load.tokenizer_digest().to_string()
            != "a1883207efeacecee399f4dc699d2b547eb2d6ddb7500522933ed76c1521fb93"
    {
        return Err("actual Ready differs from the public V2 initial profile".to_owned());
    }
    Ok(())
}
