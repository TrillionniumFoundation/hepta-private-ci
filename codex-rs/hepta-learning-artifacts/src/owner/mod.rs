//! Narrow production-owner composition boundary.
//!
//! The original `LearningArtifactOwnerHost` remains the compatibility owner for
//! the durable artifact protocol. Product composition is split here into
//! bootstrap, capability validation, request transactions, publication
//! coordination, recovery, registry commands, reconciliation, operational
//! projection and measurement. Each layer is independently testable and the
//! filesystem is injected through `OwnerDurableStoreV1` instead of being
//! reopened ad hoc by the transport.

mod bootstrap;
mod capability_store;
mod capability_validation;
mod durable_contract;
mod durable_host;
mod measurement;
mod operational;
mod prometheus;
mod publication_coordination;
mod recovery;
mod reconciliation;
mod registry_commands;
mod transaction;

pub use bootstrap::ArtifactOwnerBootstrapConfigV1;
pub use bootstrap::ArtifactOwnerBootstrapV1;
pub use bootstrap::ArtifactOwnerConfigError;
pub use bootstrap::ArtifactOwnerRuntimeConfigV1;
pub use capability_store::CapabilityOwnerDurableStoreV1 as FsOwnerDurableStoreV1;
pub use capability_validation::ArtifactOwnerActionV1;
pub use capability_validation::ArtifactOwnerCapabilityError;
pub use capability_validation::ArtifactOwnerClientGrantV1;
pub use capability_validation::ArtifactOwnerKeyringV1;
pub use capability_validation::SignedArtifactOwnerRequestV1;
pub use durable_contract::DurableCommitReceiptV1;
pub use durable_contract::DurableContractErrorV1;
pub use durable_contract::DurableLearningArtifactOwnerServiceV1;
pub use durable_contract::DurableOwnerServiceErrorV1;
pub use durable_contract::DurablePublicationPhaseV1;
pub use durable_contract::MonotonicGenerationAnchorV1;
pub use durable_contract::RouteCommitReceiptV1;
pub use durable_contract::VerifiedWithdrawalFrontierV1;
pub use durable_contract::VerifiedWriterFenceV1;
pub use durable_host::DurableInstrumentedLearningArtifactReferenceHostV1;
pub use measurement::ArtifactOwnerStageSampleV1;
pub use measurement::ArtifactOwnerStageSummaryV1;
pub use measurement::ArtifactOwnerStageV1;
pub use measurement::measure_candidate_payload_write;
pub use measurement::measure_checkpoint;
pub use measurement::measure_owner_open;
pub use measurement::measure_payload_encode_hash;
pub use measurement::measure_pinned_load;
pub use measurement::measure_registry_head_witness_write;
pub use measurement::measure_registry_snapshot_write;
pub use measurement::measure_stage;
pub use operational::ArtifactOperationalObservationError;
pub use operational::ArtifactOwnerFailureClassV1;
pub use operational::ArtifactOwnerOperationalMetricsV1;
pub use operational::ArtifactOwnerRetryDispositionV1;
pub use operational::ArtifactRetentionObservationV1;
pub use operational::InstrumentedLearningArtifactReferenceHostV1;
pub use prometheus::ArtifactOwnerPrometheusSnapshotV1;
pub use prometheus::render_artifact_owner_prometheus_v1;
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
pub use transaction::OwnerDurableStoreV1;
pub use transaction::OwnerJournalError;
pub use transaction::OwnerRequestDispositionV1;
pub use transaction::OwnerRequestJournalV1;
