//! Immutable learning artifact and lineage registry.
//!
//! Registry eligibility is not selection, activation, promotion or release.
//! This crate deliberately exposes no API capable of granting those powers.

#![forbid(unsafe_code)]

mod admission_v3;
mod closure_v2;
mod control_storage;
mod dataset_revocation;
mod error;
mod iteration;
mod iteration_ledger;
mod lifecycle_journal;
mod limits;
mod model;
mod pinned;
mod publication;
mod registry;
mod service;
mod storage;

pub use admission_v3::ArtifactAdmissionError;
pub use admission_v3::WithdrawalAuthorityDomainV1;
pub use admission_v3::WithdrawalBoundArtifactAdmissionV3;
pub use admission_v3::admit_manifest_at_withdrawal_head_v3;
pub use admission_v3::validate_artifact_publication_v3;
pub use admission_v3::verify_artifact_admission_v3;
pub use admission_v3::withdrawal_head_digest_v3;
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
pub use control_storage::{
    ArtifactLifecycleSnapshotReceiptV2, DatasetWithdrawalSnapshotReceiptV1,
    read_artifact_lifecycle_snapshot_v2, read_dataset_withdrawal_snapshot_v1,
    write_artifact_lifecycle_snapshot_v2, write_dataset_withdrawal_snapshot_v1,
};
pub use dataset_revocation::DatasetRevocationError;
pub use dataset_revocation::DatasetRevocationRequest;
pub use dataset_revocation::DatasetRevocationSummary;
pub use dataset_revocation::PreparedDatasetRevocation;
pub use dataset_revocation::prepare_dataset_revocation;
pub use error::ArtifactRegistryError;
pub use iteration::IterationCandidateStateV1;
pub use iteration::IterationCandidateV1;
pub use iteration::IterationEnvelopeV1;
pub use iteration::validate_iteration_transition;
pub use iteration_ledger::{
    IterationEvidenceKindV1, IterationEvidenceV1, IterationLedgerError, IterationLedgerEventV1,
    IterationLedgerSnapshotV1, IterationLedgerV1, MAX_ITERATION_EVENTS,
};
pub use lifecycle_journal::ArtifactLifecycleJournalError;
pub use lifecycle_journal::ArtifactLifecycleJournalReceiptV2;
pub use lifecycle_journal::ArtifactLifecycleJournalRecordV2;
pub use lifecycle_journal::ArtifactLifecycleJournalSnapshotV2;
pub use lifecycle_journal::ArtifactLifecycleJournalV2;
pub use lifecycle_journal::LifecycleActorEvidenceV2;
pub use lifecycle_journal::LifecycleActorRoleV2;
pub use lifecycle_journal::LifecycleAppendDispositionV2;
pub use limits::{MAX_DURABLE_ARTIFACT_RECORDS, MAX_DURABLE_ARTIFACT_SNAPSHOT_BYTES};
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
pub use pinned::RevalidatingCandidate;
pub use pinned::load_pinned_candidate;
pub use publication::{
    ArtifactPublicationError, ArtifactPublicationRecoveryV1, ArtifactPublicationTransactionV1,
    classify_artifact_publication_recovery_v1, prepare_artifact_publication_transaction_v1,
};
pub use registry::ArtifactRegistry;
pub use service::{ArtifactOwnerStatusV1, inspect_artifact_owner_status_v1};
pub use storage::ArtifactStorageError;
pub use storage::CreateOnlyArtifactFile;
pub use storage::PreparedCandidatePayloadV1;
pub use storage::PreparedRegistryHeadWitnessV1;
pub use storage::PreparedRegistrySnapshotV1;
pub use storage::RegistryHeadWitnessReceipt;
pub use storage::RegistrySnapshotReceipt;
pub use storage::read_candidate_payload;
pub use storage::read_registry_head_witness;
pub use storage::read_registry_snapshot;
pub use storage::prepare_candidate_payload_v1;
pub use storage::prepare_registry_head_witness_v1;
pub use storage::prepare_registry_snapshot_v1;
pub use storage::write_candidate_payload;
pub use storage::write_prepared_candidate_payload_v1;
pub use storage::write_prepared_registry_head_witness_v1;
pub use storage::write_prepared_registry_snapshot_v1;
pub use storage::write_registry_head_witness;
pub use storage::write_registry_snapshot;
