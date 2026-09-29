//! Narrow production-owner composition boundary.
//!
//! The original `LearningArtifactOwnerHost` remains the compatibility owner for
//! the durable artifact protocol. New product composition is split here into
//! bootstrap, capability validation, request transactions, publication
//! coordination, recovery, registry commands and reconciliation. Each layer is
//! independently testable and the filesystem is injected through
//! `OwnerDurableStoreV1` instead of being reopened ad hoc by the transport.

mod bootstrap;
mod capability_validation;
mod measurement;
mod publication_coordination;
mod recovery;
mod reconciliation;
mod registry_commands;
mod transaction;

pub use bootstrap::ArtifactOwnerBootstrapConfigV1;
pub use bootstrap::ArtifactOwnerBootstrapV1;
pub use bootstrap::ArtifactOwnerConfigError;
pub use bootstrap::ArtifactOwnerRuntimeConfigV1;
pub use capability_validation::ArtifactOwnerActionV1;
pub use capability_validation::ArtifactOwnerCapabilityError;
pub use capability_validation::ArtifactOwnerClientGrantV1;
pub use capability_validation::ArtifactOwnerKeyringV1;
pub use capability_validation::SignedArtifactOwnerRequestV1;
pub use measurement::ArtifactOwnerMeasuredOutcomeV1;
pub use measurement::ArtifactOwnerMeasuredStageV1;
pub use measurement::ArtifactOwnerStageRecorderV1;
pub use measurement::ArtifactOwnerStageReportV1;
pub use measurement::ArtifactOwnerStageSampleV1;
pub use measurement::MeasuredLearningArtifactOwnerHostV1;
pub use publication_coordination::ArtifactOwnerCommandError;
pub use publication_coordination::ArtifactOwnerCommandResultV1;
pub use publication_coordination::ArtifactOwnerMetricsV1;
pub use publication_coordination::LearningArtifactReferenceHostV1;
pub use recovery::ArtifactOwnerRuntimePhaseV1;
pub use recovery::ArtifactOwnerRuntimeStatusV1;
pub use recovery::ArtifactOwnerStatusError;
pub use reconciliation::ArtifactOwnerBackupReceiptV1;
pub use reconciliation::ArtifactOwnerReconciliationError;
pub use reconciliation::backup_owner_root_v1;
pub use reconciliation::migrate_owner_root_v1;
pub use reconciliation::restore_owner_root_v1;
pub use registry_commands::ArtifactManifestCommandV1;
pub use registry_commands::ArtifactOwnerCommandDecodeError;
pub use registry_commands::InstallWithdrawalSnapshotCommandV1;
pub use registry_commands::PublishArtifactCommandV1;
pub use transaction::FsOwnerDurableStoreV1;
pub use transaction::OwnerDurableStoreV1;
pub use transaction::OwnerJournalError;
pub use transaction::OwnerRequestDispositionV1;
pub use transaction::OwnerRequestJournalV1;
