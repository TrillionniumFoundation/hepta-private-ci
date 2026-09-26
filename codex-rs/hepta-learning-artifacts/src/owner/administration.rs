use std::path::PathBuf;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::capability_validation::LearningArtifactHostAccessPolicyV1;
use super::bootstrap::persist_policy_anchor;
use super::bootstrap::persist_schema_anchor;
use super::capability_validation::LearningArtifactHostAccessVerifierV1;
use super::capability_validation::LearningArtifactHostActionV1;
use super::capability_validation::SignedLearningArtifactHostCommandV1;
use super::reconciliation::LearningArtifactHostLifecycleV1;
use super::reference_host::LearningArtifactReferenceHostError;
use super::reference_host::LearningArtifactReferenceHostV1;
use super::reference_host::error_digest;
use super::transaction::LearningArtifactBackupManifestV1;
use super::transaction::LearningArtifactBackupRequestV1;
use super::transaction::LearningArtifactHostSchemaMigrationRequestV1;
use super::transaction::LearningArtifactHostSchemaMigrationV1;
use super::transaction::LearningArtifactShutdownRequestV1;
use super::transaction::digest_learning_artifact_access_policy_v1;
use super::transaction::digest_learning_artifact_backup_request_v1;
use super::transaction::digest_learning_artifact_schema_migration_request_v1;
use super::transaction::digest_learning_artifact_shutdown_request_v1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningArtifactShutdownReceiptV1 {
    pub shutdown_id: StableId,
    pub reason_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub access_policy_digest: Digest32,
    pub audit_head_digest: Digest32,
    pub stopped_at: u64,
    pub authority: AuthorityPosture,
}

impl LearningArtifactReferenceHostV1 {
    pub fn rotate_access_policy(
        &mut self,
        command: &SignedLearningArtifactHostCommandV1,
        next: LearningArtifactHostAccessPolicyV1,
        now: u64,
    ) -> Result<(), LearningArtifactReferenceHostError> {
        let request_digest = digest_learning_artifact_access_policy_v1(&next);
        let verified = self.authorize(
            command,
            LearningArtifactHostActionV1::RotateAccessPolicy,
            request_digest,
            now,
        )?;
        if let Err(error) = self.require_ready() {
            let digest = error_digest(&error);
            self.record_rejected(&verified, digest, now)?;
            return Err(error);
        }
        if next.policy_id != self.access.policy().policy_id
            || next.generation != self.access.policy().generation.saturating_add(1)
        {
            let error = LearningArtifactReferenceHostError::PolicyGeneration;
            self.record_rejected(&verified, error_digest(&error), now)?;
            return Err(error);
        }
        let next_verifier = match LearningArtifactHostAccessVerifierV1::new(
            next.clone(),
            &self.owner_trust,
        ) {
            Ok(value) => value,
            Err(error) => {
                self.record_rejected(&verified, error_digest(&error), now)?;
                return Err(error.into());
            }
        };
        if let Err(error) = persist_policy_anchor(
            &self.control_root,
            &next,
            &self.durability,
        ) {
            self.lifecycle = LearningArtifactHostLifecycleV1::Faulted;
            self.record_indeterminate(&verified, error_digest(&error), now)?;
            return Err(error);
        }
        let next_digest = next_verifier.policy_digest();
        self.access = next_verifier;
        self.record_applied(&verified, next_digest, now)?;
        self.metrics.policy_rotations = self.metrics.policy_rotations.saturating_add(1);
        Ok(())
    }

    pub fn prepare_backup_manifest(
        &mut self,
        command: &SignedLearningArtifactHostCommandV1,
        request: LearningArtifactBackupRequestV1,
    ) -> Result<LearningArtifactBackupManifestV1, LearningArtifactReferenceHostError> {
        let request_digest = digest_learning_artifact_backup_request_v1(&request);
        let verified = self.authorize(
            command,
            LearningArtifactHostActionV1::PrepareBackup,
            request_digest,
            request.requested_at,
        )?;
        if let Err(error) = self.require_ready() {
            self.record_rejected(&verified, error_digest(&error), request.requested_at)?;
            return Err(error);
        }
        if request.destination_witness_digest.is_zero() {
            let error = LearningArtifactReferenceHostError::BackupContext;
            self.record_rejected(&verified, error_digest(&error), request.requested_at)?;
            return Err(error);
        }
        if let Err(error) = self.durability.sync_publication(&self.root) {
            self.lifecycle = LearningArtifactHostLifecycleV1::Faulted;
            self.record_indeterminate(&verified, error_digest(&error), request.requested_at)?;
            return Err(error.into());
        }
        let view = match self.service.current_registry_view(request.requested_at) {
            Ok(value) => value,
            Err(error) => {
                self.record_rejected(&verified, error_digest(&error), request.requested_at)?;
                return Err(error.into());
            }
        };
        let mut manifest = LearningArtifactBackupManifestV1 {
            backup_id: request.backup_id,
            schema_version: self.schema_version,
            storage_binding: self.storage_binding,
            registry_receipt: view.receipt(),
            withdrawal_receipt: self.withdrawal_receipt,
            access_policy_digest: self.access.policy_digest(),
            destination_witness_digest: request.destination_witness_digest,
            prepared_at: request.requested_at,
            manifest_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        manifest.manifest_digest = Digest32::of_bytes(&manifest.canonical_bytes_without_digest());
        let mut bytes = manifest.canonical_bytes_without_digest();
        bytes.extend_from_slice(manifest.manifest_digest.as_array());
        let relative = PathBuf::from("backups").join(format!(
            "{}-{}.manifest",
            manifest.backup_id, manifest.manifest_digest
        ));
        if let Err(error) = self
            .durability
            .create_control_file(&self.control_root, &relative, &bytes)
            .and_then(|_| {
                self.durability
                    .sync_control_root(&self.control_root.join("backups"))
            })
            .and_then(|_| self.durability.sync_control_root(&self.control_root))
        {
            self.lifecycle = LearningArtifactHostLifecycleV1::Faulted;
            self.record_indeterminate(&verified, error_digest(&error), request.requested_at)?;
            return Err(error.into());
        }
        self.record_applied(
            &verified,
            manifest.manifest_digest,
            request.requested_at,
        )?;
        self.metrics.backup_manifests = self.metrics.backup_manifests.saturating_add(1);
        Ok(manifest)
    }

    pub fn begin_shutdown(
        &mut self,
        command: &SignedLearningArtifactHostCommandV1,
        request: &LearningArtifactShutdownRequestV1,
    ) -> Result<(), LearningArtifactReferenceHostError> {
        let request_digest = digest_learning_artifact_shutdown_request_v1(request);
        let verified = self.authorize(
            command,
            LearningArtifactHostActionV1::BeginShutdown,
            request_digest,
            request.requested_at,
        )?;
        if let Err(error) = self.require_ready() {
            self.record_rejected(&verified, error_digest(&error), request.requested_at)?;
            return Err(error);
        }
        self.lifecycle = LearningArtifactHostLifecycleV1::Draining;
        self.record_applied(&verified, request.reason_digest, request.requested_at)?;
        Ok(())
    }

    pub fn finish_shutdown(
        mut self,
        command: &SignedLearningArtifactHostCommandV1,
        request: LearningArtifactShutdownRequestV1,
    ) -> Result<LearningArtifactShutdownReceiptV1, LearningArtifactReferenceHostError> {
        let request_digest = digest_learning_artifact_shutdown_request_v1(&request);
        let verified = self.authorize(
            command,
            LearningArtifactHostActionV1::FinishShutdown,
            request_digest,
            request.requested_at,
        )?;
        if self.lifecycle != LearningArtifactHostLifecycleV1::Draining {
            let error = LearningArtifactReferenceHostError::Draining;
            self.record_rejected(&verified, error_digest(&error), request.requested_at)?;
            return Err(error);
        }
        if let Err(error) = self.durability.sync_publication(&self.root) {
            self.lifecycle = LearningArtifactHostLifecycleV1::Faulted;
            self.record_indeterminate(&verified, error_digest(&error), request.requested_at)?;
            return Err(error.into());
        }
        let mut receipt = LearningArtifactShutdownReceiptV1 {
            shutdown_id: request.shutdown_id,
            reason_digest: request.reason_digest,
            registry_head_digest: self.service.registry().snapshot().head_digest,
            withdrawal_head_digest: self.service.withdrawal_registry().head_digest(),
            access_policy_digest: self.access.policy_digest(),
            audit_head_digest: Digest32::ZERO,
            stopped_at: request.requested_at,
            authority: AuthorityPosture::DENY_ALL,
        };
        let mut bytes = b"hepta.learning-artifacts.host-shutdown-receipt.v1".to_vec();
        bytes.extend_from_slice(receipt.reason_digest.as_array());
        bytes.extend_from_slice(receipt.registry_head_digest.as_array());
        bytes.extend_from_slice(receipt.withdrawal_head_digest.as_array());
        bytes.extend_from_slice(receipt.access_policy_digest.as_array());
        bytes.extend_from_slice(&receipt.stopped_at.to_be_bytes());
        let receipt_digest = Digest32::of_bytes(&bytes);
        self.record_applied(&verified, receipt_digest, request.requested_at)?;
        receipt.audit_head_digest = self.audit.head_digest();
        let relative = PathBuf::from("shutdown").join(format!(
            "{}-{}.receipt",
            receipt.shutdown_id, receipt.audit_head_digest
        ));
        let mut durable = bytes;
        durable.extend_from_slice(receipt.audit_head_digest.as_array());
        self.durability
            .create_control_file(&self.control_root, &relative, &durable)?;
        self.durability
            .sync_control_root(&self.control_root.join("shutdown"))?;
        self.durability.sync_control_root(&self.control_root)?;
        Ok(receipt)
    }

    pub fn migrate_control_schema(
        &mut self,
        command: &SignedLearningArtifactHostCommandV1,
        request: LearningArtifactHostSchemaMigrationRequestV1,
        migration: &dyn LearningArtifactHostSchemaMigrationV1,
    ) -> Result<(), LearningArtifactReferenceHostError> {
        let request_digest = digest_learning_artifact_schema_migration_request_v1(&request);
        let verified = self.authorize(
            command,
            LearningArtifactHostActionV1::MigrateControlSchema,
            request_digest,
            request.requested_at,
        )?;
        if self.lifecycle != LearningArtifactHostLifecycleV1::Draining {
            let error = LearningArtifactReferenceHostError::Draining;
            self.record_rejected(&verified, error_digest(&error), request.requested_at)?;
            return Err(error);
        }
        if request.from_version != self.schema_version
            || request.to_version != self.schema_version.saturating_add(1)
            || request.to_version > self.maximum_supported_control_schema_version
            || migration.from_version() != request.from_version
            || migration.to_version() != request.to_version
            || migration.migration_digest() != request.migration_digest
            || request.migration_digest.is_zero()
        {
            let error = LearningArtifactReferenceHostError::MigrationContext;
            self.record_rejected(&verified, error_digest(&error), request.requested_at)?;
            return Err(error);
        }
        if let Err(error) = migration.apply(&self.control_root) {
            self.lifecycle = LearningArtifactHostLifecycleV1::Faulted;
            self.record_indeterminate(&verified, error_digest(&error), request.requested_at)?;
            return Err(error.into());
        }
        if let Err(error) = persist_schema_anchor(
            &self.control_root,
            request.to_version,
            &self.durability,
        ) {
            self.lifecycle = LearningArtifactHostLifecycleV1::Faulted;
            self.record_indeterminate(&verified, error_digest(&error), request.requested_at)?;
            return Err(error);
        }
        self.schema_version = request.to_version;
        self.record_applied(&verified, request.migration_digest, request.requested_at)?;
        self.metrics.schema_migrations = self.metrics.schema_migrations.saturating_add(1);
        Ok(())
    }

    #[must_use]
    pub fn access_policy_request_digest(
        policy: &LearningArtifactHostAccessPolicyV1,
    ) -> Digest32 {
        digest_learning_artifact_access_policy_v1(policy)
    }

    #[must_use]
    pub fn backup_request_digest(request: &LearningArtifactBackupRequestV1) -> Digest32 {
        digest_learning_artifact_backup_request_v1(request)
    }

    #[must_use]
    pub fn shutdown_request_digest(request: &LearningArtifactShutdownRequestV1) -> Digest32 {
        digest_learning_artifact_shutdown_request_v1(request)
    }

    #[must_use]
    pub fn schema_migration_request_digest(
        request: &LearningArtifactHostSchemaMigrationRequestV1,
    ) -> Digest32 {
        digest_learning_artifact_schema_migration_request_v1(request)
    }
}

#[must_use]
pub fn validate_learning_artifact_restore_manifest_v1(
    manifest: &LearningArtifactBackupManifestV1,
    expected_storage_binding: Digest32,
    expected_policy_digest: Digest32,
    maximum_supported_schema_version: u32,
) -> bool {
    manifest.verify_digest()
        && manifest.storage_binding == expected_storage_binding
        && manifest.access_policy_digest == expected_policy_digest
        && manifest.schema_version > 0
        && manifest.schema_version <= maximum_supported_schema_version
        && !manifest.destination_witness_digest.is_zero()
}
