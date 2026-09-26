//! Production reference host for the immutable learning-artifact owner.
//!
//! The legacy owner host remains the compatibility implementation for durable
//! artifact formats. This module adds the product boundary around it: signed
//! action-level admission, a restart-persistent replay fence, durable audit,
//! strict root provisioning, recovery-gated readiness, directory durability,
//! access-policy rotation, backup manifests, schema migration and graceful
//! shutdown. It grants no selection, activation, promotion or release authority.

mod administration;
mod bootstrap;
mod capability_validation;
mod lifecycle_commands;
mod publication_coordination;
mod reconciliation;
mod reference_host;
mod registry_commands;
mod transaction;

pub use administration::LearningArtifactShutdownReceiptV1;
pub use administration::validate_learning_artifact_restore_manifest_v1;
pub use capability_validation::LearningArtifactHostAccessError;
pub use capability_validation::LearningArtifactHostAccessPolicyV1;
pub use capability_validation::LearningArtifactHostActionV1;
pub use capability_validation::SignedLearningArtifactHostCommandV1;
pub use capability_validation::TrustedLearningArtifactHostPrincipalV1;
pub use capability_validation::VerifiedLearningArtifactHostCommandV1;
pub use reconciliation::LearningArtifactAuditError;
pub use reconciliation::LearningArtifactHostHealthV1;
pub use reconciliation::LearningArtifactHostLifecycleV1;
pub use reconciliation::LearningArtifactHostMetricsV1;
pub use reference_host::LearningArtifactReferenceHostConfigV1;
pub use reference_host::LearningArtifactReferenceHostError;
pub use reference_host::LearningArtifactReferenceHostV1;
pub use transaction::LEARNING_ARTIFACT_HOST_SCHEMA_VERSION_V1;
pub use transaction::LearningArtifactBackupManifestV1;
pub use transaction::LearningArtifactBackupRequestV1;
pub use transaction::LearningArtifactHostSchemaMigrationRequestV1;
pub use transaction::LearningArtifactHostSchemaMigrationV1;
pub use transaction::LearningArtifactShutdownRequestV1;
pub use transaction::digest_learning_artifact_access_policy_v1;
pub use transaction::digest_learning_artifact_backup_request_v1;
pub use transaction::digest_learning_artifact_current_view_request_v1;
pub use transaction::digest_learning_artifact_publish_request_v1;
pub use transaction::digest_learning_artifact_schema_migration_request_v1;
pub use transaction::digest_learning_artifact_shutdown_request_v1;
pub use transaction::digest_learning_artifact_withdrawal_frontier_v1;
