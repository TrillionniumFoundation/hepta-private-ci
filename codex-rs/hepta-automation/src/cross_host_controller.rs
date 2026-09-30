//! Cross-host source retirement and target admission on the existing timer owner.
//!
//! This controller composes the signed external fence, exact checkpoint digest,
//! copied owner store and monotone timer epoch. It does not implement transport;
//! callers must copy a closed, consistent checkpoint before invoking target
//! admission. Every mismatch fails while the target remains draining.

use codex_hepta_contracts::Sha256Digest;

use crate::AUTOMATION_SCHEMA_VERSION;
use crate::AutomationCrossHostRecoveryManifestV1;
use crate::AutomationError;
use crate::AutomationStore;
use crate::TimerPhase;
use crate::VerifiedAutomationHostFenceV1;
use crate::record_automation_timer_drain_blocked;

impl AutomationStore {
    /// Quiesce and permanently retire the source writer after producing an exact
    /// manifest for its already-captured checkpoint. Unknown effects, executing
    /// Circuit activations or leased occurrences block retirement.
    pub async fn seal_cross_host_source_v1(
        &self,
        sqlite_checkpoint_digest: Sha256Digest,
        verified_fence: &VerifiedAutomationHostFenceV1,
        now_ms: u64,
    ) -> Result<AutomationCrossHostRecoveryManifestV1, AutomationError> {
        verified_fence.validate_current(now_ms)?;
        let before = self.timer_status().await?;
        let claims = verified_fence.claims();
        if claims.owner_agent_id != self.owner_agent_id().as_str()
            || claims.source_writer_epoch != before.writer_epoch
            || claims.required_target_writer_epoch
                != before
                    .writer_epoch
                    .checked_add(1)
                    .ok_or(AutomationError::Conflict)?
            || claims.sqlite_checkpoint_digest != sqlite_checkpoint_digest
            || before.phase == TimerPhase::Retired
        {
            return Err(AutomationError::TimerFenced);
        }
        let drained = self.quiesce_timer().await?;
        if !drained.can_handoff() {
            record_automation_timer_drain_blocked();
            return Err(AutomationError::Conflict);
        }
        let manifest = AutomationCrossHostRecoveryManifestV1::new(
            self.owner_agent_id(),
            &drained,
            sqlite_checkpoint_digest,
            verified_fence,
            now_ms,
        )?;
        let retired = match self.retire_timer().await {
            Ok(status) => status,
            Err(error) => {
                record_automation_timer_drain_blocked();
                return Err(error);
            }
        };
        if retired.phase != TimerPhase::Retired
            || retired.writer_epoch != manifest.required_target_writer_epoch
        {
            return Err(AutomationError::Corrupt);
        }
        Ok(manifest)
    }

    /// Admit a copied target only after exact preflight, epoch handoff and a
    /// second post-handoff manifest verification. A failure after epoch advance
    /// leaves the copied store draining; it never reactivates the predecessor.
    pub async fn admit_cross_host_target_v1(
        &self,
        manifest: &AutomationCrossHostRecoveryManifestV1,
        verified_fence: &VerifiedAutomationHostFenceV1,
        target_host_id: &str,
        observed_checkpoint_digest: &Sha256Digest,
        now_ms: u64,
    ) -> Result<Self, AutomationError> {
        manifest.validate()?;
        verified_fence.validate_current(now_ms)?;
        let before = self.timer_status().await?;
        let claims = verified_fence.claims();
        if before.phase != TimerPhase::Draining
            || before.writer_epoch != manifest.source_writer_epoch
            || manifest.owner_agent_id != self.owner_agent_id().as_str()
            || manifest.store_schema_version != AUTOMATION_SCHEMA_VERSION
            || manifest.target_host_id != target_host_id
            || manifest.sqlite_checkpoint_digest != *observed_checkpoint_digest
            || manifest.external_fence_receipt_digest != *verified_fence.receipt_digest()
            || claims.owner_agent_id != manifest.owner_agent_id
            || claims.source_host_id != manifest.source_host_id
            || claims.target_host_id != manifest.target_host_id
            || claims.source_writer_epoch != manifest.source_writer_epoch
            || claims.required_target_writer_epoch != manifest.required_target_writer_epoch
            || claims.sqlite_checkpoint_digest != manifest.sqlite_checkpoint_digest
        {
            return Err(AutomationError::TimerFenced);
        }

        let successor = match self.handoff_timer().await {
            Ok(store) => store,
            Err(error) => {
                record_automation_timer_drain_blocked();
                return Err(error);
            }
        };
        let status = successor.timer_status().await?;
        if let Err(error) = manifest.admit_target(
            verified_fence,
            now_ms,
            target_host_id,
            successor.owner_agent_id(),
            AUTOMATION_SCHEMA_VERSION,
            status.writer_epoch,
            observed_checkpoint_digest,
        ) {
            successor.close().await;
            return Err(error);
        }
        let active = successor.resume_timer().await?;
        if active.phase != TimerPhase::Active
            || active.writer_epoch != manifest.required_target_writer_epoch
        {
            successor.close().await;
            return Err(AutomationError::Corrupt);
        }
        Ok(successor)
    }
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::Path;

    use codex_hepta_contracts::AgentId;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use crate::AUTOMATION_HOST_FENCE_SCHEMA_VERSION;
    use crate::AutomationHostFenceClaimsV1;
    use crate::AutomationHostFenceTrustV1;
    use crate::SignedAutomationHostFenceV1;

    use super::*;

    const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

    fn owner() -> AgentId {
        AgentId::parse(AGENT_ID).expect("agent")
    }

    fn verified_fence(
        checkpoint: Sha256Digest,
        source_writer_epoch: u64,
    ) -> VerifiedAutomationHostFenceV1 {
        let signing_key = SigningKey::from_bytes(&[29_u8; 32]);
        let trust = AutomationHostFenceTrustV1 {
            schema_version: AUTOMATION_HOST_FENCE_SCHEMA_VERSION,
            controller_id: "independent-automation-fence".to_string(),
            authority_epoch: 11,
            verifying_key: signing_key.verifying_key().to_bytes(),
        };
        let claims = AutomationHostFenceClaimsV1 {
            schema_version: AUTOMATION_HOST_FENCE_SCHEMA_VERSION,
            fence_id: "cross-host-fence-1".to_string(),
            controller_id: trust.controller_id.clone(),
            authority_epoch: trust.authority_epoch,
            owner_agent_id: AGENT_ID.to_string(),
            source_host_id: "host-source".to_string(),
            target_host_id: "host-target".to_string(),
            source_writer_epoch,
            required_target_writer_epoch: source_writer_epoch + 1,
            sqlite_checkpoint_digest: checkpoint,
            issued_at_ms: 1_000,
            expires_at_ms: 61_000,
        };
        let signature = signing_key.sign(&claims.signing_bytes().expect("signing bytes"));
        VerifiedAutomationHostFenceV1::verify(
            &trust,
            &SignedAutomationHostFenceV1 {
                claims,
                signature: signature.to_bytes(),
            },
            2_000,
        )
        .expect("verified fence")
    }

    fn copy_checkpoint(source_db: &Path, target_root: &Path) -> (Sha256Digest, std::path::PathBuf) {
        fs::create_dir_all(target_root).expect("target root");
        let target_db = target_root.join(source_db.file_name().expect("database filename"));
        fs::copy(source_db, &target_db).expect("copy checkpoint");
        let bytes = fs::read(&target_db).expect("checkpoint bytes");
        (Sha256Digest::for_bytes(&bytes), target_db)
    }

    #[tokio::test]
    async fn two_store_handoff_retires_source_and_activates_only_next_epoch() {
        let temp = tempfile::tempdir().expect("temp");
        let source_root = temp.path().join("source");
        let target_root = temp.path().join("target");
        let source = AutomationStore::open_root(source_root.clone(), owner())
            .await
            .expect("source");
        let drained = source.quiesce_timer().await.expect("drain");
        assert!(drained.can_handoff());
        let source_db = source.path().to_path_buf();
        source.close().await;
        let (checkpoint, _target_db) = copy_checkpoint(&source_db, &target_root);

        let source = AutomationStore::open_root(source_root, owner())
            .await
            .expect("reopen source");
        let fence = verified_fence(checkpoint.clone(), drained.writer_epoch);
        let manifest = source
            .seal_cross_host_source_v1(checkpoint.clone(), &fence, 2_000)
            .await
            .expect("seal source");
        let source_status = source.timer_status().await.expect("source status");
        assert_eq!(source_status.phase, TimerPhase::Retired);
        assert_eq!(
            source_status.writer_epoch,
            manifest.required_target_writer_epoch
        );
        assert_eq!(source.resume_timer().await, Err(AutomationError::TimerFenced));

        let copied = AutomationStore::open_root(target_root, owner())
            .await
            .expect("copied target");
        let copied_status = copied.timer_status().await.expect("copied status");
        assert_eq!(copied_status.phase, TimerPhase::Draining);
        assert_eq!(copied_status.writer_epoch, manifest.source_writer_epoch);
        let target = copied
            .admit_cross_host_target_v1(
                &manifest,
                &fence,
                "host-target",
                &checkpoint,
                3_000,
            )
            .await
            .expect("admit target");
        let target_status = target.timer_status().await.expect("target status");
        assert_eq!(target_status.phase, TimerPhase::Active);
        assert_eq!(
            target_status.writer_epoch,
            manifest.required_target_writer_epoch
        );
        assert_eq!(copied.resume_timer().await, Err(AutomationError::TimerFenced));
        source.close().await;
        copied.close().await;
        target.close().await;
    }

    #[tokio::test]
    async fn wrong_target_or_partitioned_controller_leaves_copy_draining() {
        let temp = tempfile::tempdir().expect("temp");
        let source_root = temp.path().join("source");
        let target_root = temp.path().join("target");
        let source = AutomationStore::open_root(source_root.clone(), owner())
            .await
            .expect("source");
        let drained = source.quiesce_timer().await.expect("drain");
        let source_db = source.path().to_path_buf();
        source.close().await;
        let (checkpoint, _target_db) = copy_checkpoint(&source_db, &target_root);
        let source = AutomationStore::open_root(source_root, owner())
            .await
            .expect("reopen source");
        let fence = verified_fence(checkpoint.clone(), drained.writer_epoch);
        let manifest = source
            .seal_cross_host_source_v1(checkpoint.clone(), &fence, 2_000)
            .await
            .expect("seal source");
        let copied = AutomationStore::open_root(target_root, owner())
            .await
            .expect("copied target");
        assert_eq!(
            copied
                .admit_cross_host_target_v1(
                    &manifest,
                    &fence,
                    "partitioned-or-wrong-target",
                    &checkpoint,
                    3_000,
                )
                .await
                .map(|_| ()),
            Err(AutomationError::TimerFenced)
        );
        let status = copied.timer_status().await.expect("target status");
        assert_eq!(status.phase, TimerPhase::Draining);
        assert_eq!(status.writer_epoch, manifest.source_writer_epoch);
        source.close().await;
        copied.close().await;
    }
}
