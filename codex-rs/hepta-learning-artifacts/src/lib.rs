//! Immutable learning artifact and lineage registry.
//!
//! Registry eligibility is not selection, activation, promotion or release.
//! This crate deliberately exposes no API capable of granting those powers.

#![forbid(unsafe_code)]

mod closure_v2;
mod dataset_revocation;
mod error;
mod model;
mod pinned;
mod registry;
mod storage;

pub use closure_v2::ArtifactClosureError;
pub use closure_v2::ArtifactLifecycleEventV1;
pub use closure_v2::ArtifactLifecycleStateV1;
pub use closure_v2::DatasetWithdrawalNoticeV1;
pub use closure_v2::DatasetWithdrawalReceiptV1;
pub use closure_v2::DatasetWithdrawalRecordV1;
pub use closure_v2::DatasetWithdrawalRegistry;
pub use closure_v2::DatasetWithdrawalRegistrySnapshotV1;
pub use closure_v2::LearningArtifactManifestV2;
pub use closure_v2::ProvenanceModeV1;
pub use closure_v2::RegistryHeadReceiptV1;
pub use closure_v2::RegistryHeadRequirementV1;
pub use closure_v2::RegistryHeadWitnessV1;
pub use closure_v2::ValidatedArtifactManifestV2;
pub use closure_v2::WithdrawalAppendDispositionV1;
pub use closure_v2::validate_artifact_lifecycle_transition;
pub use closure_v2::validate_artifact_manifest_v2;
pub use closure_v2::validate_registry_head_witness;
pub use dataset_revocation::DatasetRevocationError;
pub use dataset_revocation::DatasetRevocationRequest;
pub use dataset_revocation::DatasetRevocationSummary;
pub use dataset_revocation::PreparedDatasetRevocation;
pub use dataset_revocation::prepare_dataset_revocation;
pub use error::ArtifactRegistryError;
pub use model::ArtifactEvent;
pub use model::ArtifactKind;
pub use model::ArtifactManifest;
pub use model::ArtifactRecord;
pub use model::ArtifactRegistrySnapshot;
pub use model::ArtifactState;
pub use model::LineageDisposition;
pub use model::RegistryAppendDisposition;
pub use model::RegistryAppendReceipt;
pub use model::StateChange;
pub use pinned::LoadedPinnedCandidate;
pub use pinned::PinnedCandidateLoadError;
pub use pinned::PinnedCandidateSpec;
pub use pinned::load_pinned_candidate;
pub use registry::ArtifactRegistry;
pub use storage::ArtifactStorageError;
pub use storage::CreateOnlyArtifactFile;
pub use storage::RegistrySnapshotReceipt;
pub use storage::read_candidate_payload;
pub use storage::read_registry_snapshot;
pub use storage::write_candidate_payload;
pub use storage::write_registry_snapshot;
