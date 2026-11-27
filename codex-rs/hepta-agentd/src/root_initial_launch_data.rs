//! Shared immutable Initial deployment data. The actual authenticated Root
//! profile later checks these exact public preimages; this type has no authority.

use std::path::PathBuf;

use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalSnapshotReceiptV1;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_neuron::CellGenerationObserverConfigV1;
use codex_hepta_types::Digest32;

use crate::RootGenerationInitialModeV1;

pub(crate) struct OriginalRootInitialLaunchDataV1 {
    pub(crate) mode: RootGenerationInitialModeV1,
    pub(crate) operation: String,
    pub(crate) target_journal: PathBuf,
    pub(crate) target_witness: PathBuf,
    pub(crate) target: CellGenerationObserverConfigV1,
    pub(crate) artifact_root: PathBuf,
    pub(crate) trust: ArtifactOwnerTrustV1,
    pub(crate) retained_current: SignedCurrentArtifactHeadV1,
    pub(crate) storage_binding: Digest32,
    pub(crate) withdrawal_file: PathBuf,
    pub(crate) withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1,
    pub(crate) selector: ArtifactSelectionVerifierV1,
    pub(crate) selection: SignedArtifactSelectionV1,
}
