//! Fail-closed manifest for moving an already quiesced automation database to a
//! different host. The manifest does not copy bytes or create authority. It
//! consumes an authenticated external host-fence receipt and binds that receipt,
//! the SQLite checkpoint digest and the next writer epoch into target admission.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::AUTOMATION_SCHEMA_VERSION;
use crate::AutomationError;
use crate::TimerDrainStatus;
use crate::VerifiedAutomationHostFenceV1;

pub const AUTOMATION_CROSS_HOST_RECOVERY_SCHEMA_VERSION: u32 = 2;
const MAX_HOST_ID_BYTES: usize = 256;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationCrossHostRecoveryManifestV1 {
    pub schema_version: u32,
    pub owner_agent_id: String,
    pub source_host_id: String,
    pub target_host_id: String,
    pub source_writer_epoch: u64,
    pub required_target_writer_epoch: u64,
    pub store_schema_version: u32,
    pub pending_occurrences: u64,
    pub sqlite_checkpoint_digest: Sha256Digest,
    pub external_fence_receipt_digest: Sha256Digest,
    pub exported_at_ms: u64,
    pub manifest_digest: Sha256Digest,
}

impl AutomationCrossHostRecoveryManifestV1 {
    pub fn new(
        owner_agent_id: &AgentId,
        drain_status: &TimerDrainStatus,
        sqlite_checkpoint_digest: Sha256Digest,
        verified_fence: &VerifiedAutomationHostFenceV1,
        exported_at_ms: u64,
    ) -> Result<Self, AutomationError> {
        verified_fence.validate_current(exported_at_ms)?;
        validate_digest(&sqlite_checkpoint_digest)?;
        let fence = verified_fence.claims();
        validate_host_id(&fence.source_host_id)?;
        validate_host_id(&fence.target_host_id)?;
        if !drain_status.can_handoff()
            || drain_status.uncertain_dispatches != 0
            || exported_at_ms == 0
            || fence.owner_agent_id != owner_agent_id.as_str()
            || fence.source_writer_epoch != drain_status.writer_epoch
            || fence.required_target_writer_epoch
                != drain_status
                    .writer_epoch
                    .checked_add(1)
                    .ok_or(AutomationError::Conflict)?
            || fence.sqlite_checkpoint_digest != sqlite_checkpoint_digest
        {
            return Err(AutomationError::Conflict);
        }
        let mut manifest = Self {
            schema_version: AUTOMATION_CROSS_HOST_RECOVERY_SCHEMA_VERSION,
            owner_agent_id: owner_agent_id.as_str().to_string(),
            source_host_id: fence.source_host_id.clone(),
            target_host_id: fence.target_host_id.clone(),
            source_writer_epoch: drain_status.writer_epoch,
            required_target_writer_epoch: fence.required_target_writer_epoch,
            store_schema_version: AUTOMATION_SCHEMA_VERSION,
            pending_occurrences: drain_status.pending_occurrences,
            sqlite_checkpoint_digest,
            external_fence_receipt_digest: verified_fence.receipt_digest().clone(),
            exported_at_ms,
            manifest_digest: Sha256Digest::for_bytes(b"uncomputed-cross-host-manifest-v2"),
        };
        manifest.manifest_digest = manifest.compute_digest()?;
        Ok(manifest)
    }

    pub fn validate(&self) -> Result<(), AutomationError> {
        validate_host_id(&self.source_host_id)?;
        validate_host_id(&self.target_host_id)?;
        validate_digest(&self.sqlite_checkpoint_digest)?;
        validate_digest(&self.external_fence_receipt_digest)?;
        if self.schema_version != AUTOMATION_CROSS_HOST_RECOVERY_SCHEMA_VERSION
            || self.store_schema_version != AUTOMATION_SCHEMA_VERSION
            || AgentId::parse(&self.owner_agent_id).is_err()
            || self.source_host_id == self.target_host_id
            || self.source_writer_epoch == 0
            || self.required_target_writer_epoch
                != self
                    .source_writer_epoch
                    .checked_add(1)
                    .ok_or(AutomationError::Corrupt)?
            || self.exported_at_ms == 0
            || self.manifest_digest != self.compute_digest()?
        {
            return Err(AutomationError::Corrupt);
        }
        Ok(())
    }

    /// Verify the exact target tuple and the still-current authenticated source
    /// fence before opening the copied database for writes. The owner Agent ID,
    /// schema, writer epoch and checkpoint are observations from the target
    /// store, not values accepted from the manifest alone.
    #[allow(clippy::too_many_arguments)]
    pub fn admit_target(
        &self,
        verified_fence: &VerifiedAutomationHostFenceV1,
        now_ms: u64,
        target_host_id: &str,
        observed_owner_agent_id: &AgentId,
        observed_store_schema_version: u32,
        observed_writer_epoch: u64,
        observed_checkpoint_digest: &Sha256Digest,
    ) -> Result<(), AutomationError> {
        self.validate()?;
        verified_fence.validate_current(now_ms)?;
        let fence = verified_fence.claims();
        if verified_fence.receipt_digest() != &self.external_fence_receipt_digest
            || fence.owner_agent_id != self.owner_agent_id
            || fence.source_host_id != self.source_host_id
            || fence.target_host_id != self.target_host_id
            || fence.source_writer_epoch != self.source_writer_epoch
            || fence.required_target_writer_epoch != self.required_target_writer_epoch
            || fence.sqlite_checkpoint_digest != self.sqlite_checkpoint_digest
            || target_host_id != self.target_host_id
            || observed_owner_agent_id.as_str() != self.owner_agent_id
            || observed_store_schema_version != self.store_schema_version
            || observed_writer_epoch != self.required_target_writer_epoch
            || observed_checkpoint_digest != &self.sqlite_checkpoint_digest
        {
            return Err(AutomationError::TimerFenced);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Result<Sha256Digest, AutomationError> {
        #[derive(Serialize)]
        struct Canonical<'a> {
            schema_version: u32,
            owner_agent_id: &'a str,
            source_host_id: &'a str,
            target_host_id: &'a str,
            source_writer_epoch: u64,
            required_target_writer_epoch: u64,
            store_schema_version: u32,
            pending_occurrences: u64,
            sqlite_checkpoint_digest: &'a Sha256Digest,
            external_fence_receipt_digest: &'a Sha256Digest,
            exported_at_ms: u64,
        }

        let mut bytes = b"hepta.automation.cross-host-recovery.v2\0".to_vec();
        bytes.extend_from_slice(
            &serde_json::to_vec(&Canonical {
                schema_version: self.schema_version,
                owner_agent_id: &self.owner_agent_id,
                source_host_id: &self.source_host_id,
                target_host_id: &self.target_host_id,
                source_writer_epoch: self.source_writer_epoch,
                required_target_writer_epoch: self.required_target_writer_epoch,
                store_schema_version: self.store_schema_version,
                pending_occurrences: self.pending_occurrences,
                sqlite_checkpoint_digest: &self.sqlite_checkpoint_digest,
                external_fence_receipt_digest: &self.external_fence_receipt_digest,
                exported_at_ms: self.exported_at_ms,
            })
            .map_err(|_| AutomationError::Corrupt)?,
        );
        Ok(Sha256Digest::for_bytes(&bytes))
    }
}

fn validate_host_id(value: &str) -> Result<(), AutomationError> {
    if value.is_empty() || value.len() > MAX_HOST_ID_BYTES || value.chars().any(char::is_control) {
        return Err(AutomationError::Invalid);
    }
    Ok(())
}

fn validate_digest(value: &Sha256Digest) -> Result<(), AutomationError> {
    let text = value.as_str();
    if text.len() != 64 || text.bytes().all(|byte| byte == b'0') {
        return Err(AutomationError::Invalid);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use crate::AUTOMATION_HOST_FENCE_SCHEMA_VERSION;
    use crate::AutomationHostFenceClaimsV1;
    use crate::AutomationHostFenceTrustV1;
    use crate::SignedAutomationHostFenceV1;
    use crate::TimerPhase;

    use super::*;

    fn owner() -> AgentId {
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent")
    }

    fn fence(uncertain_dispatches: u64) -> (TimerDrainStatus, VerifiedAutomationHostFenceV1) {
        let signing_key = SigningKey::from_bytes(&[11_u8; 32]);
        let trust = AutomationHostFenceTrustV1 {
            schema_version: AUTOMATION_HOST_FENCE_SCHEMA_VERSION,
            controller_id: "deployment-controller".to_string(),
            authority_epoch: 4,
            verifying_key: signing_key.verifying_key().to_bytes(),
        };
        let claims = AutomationHostFenceClaimsV1 {
            schema_version: AUTOMATION_HOST_FENCE_SCHEMA_VERSION,
            fence_id: "fence-automation-7".to_string(),
            controller_id: trust.controller_id.clone(),
            authority_epoch: trust.authority_epoch,
            owner_agent_id: owner().as_str().to_string(),
            source_host_id: "host-a".to_string(),
            target_host_id: "host-b".to_string(),
            source_writer_epoch: 7,
            required_target_writer_epoch: 8,
            sqlite_checkpoint_digest: Sha256Digest::for_bytes(b"checkpoint"),
            issued_at_ms: 1_000,
            expires_at_ms: 61_000,
        };
        let signature = signing_key.sign(&claims.signing_bytes().expect("signing bytes"));
        let signed = SignedAutomationHostFenceV1 {
            claims,
            signature: signature.to_bytes(),
        };
        let verified =
            VerifiedAutomationHostFenceV1::verify(&trust, &signed, 2_000).expect("fence");
        (
            TimerDrainStatus {
                writer_epoch: 7,
                phase: TimerPhase::Draining,
                pending_occurrences: 3,
                leased_occurrences: 0,
                uncertain_dispatches,
            },
            verified,
        )
    }

    fn manifest() -> (
        AutomationCrossHostRecoveryManifestV1,
        VerifiedAutomationHostFenceV1,
    ) {
        let (status, fence) = fence(0);
        let manifest = AutomationCrossHostRecoveryManifestV1::new(
            &owner(),
            &status,
            Sha256Digest::for_bytes(b"checkpoint"),
            &fence,
            2_000,
        )
        .expect("manifest");
        (manifest, fence)
    }

    #[test]
    fn cross_host_manifest_binds_signed_fence_and_next_epoch() {
        let (manifest, fence) = manifest();
        let checkpoint = manifest.sqlite_checkpoint_digest.clone();
        manifest.validate().expect("valid manifest");
        manifest
            .admit_target(
                &fence,
                3_000,
                "host-b",
                &owner(),
                AUTOMATION_SCHEMA_VERSION,
                8,
                &checkpoint,
            )
            .expect("target admission");
        assert_eq!(manifest.pending_occurrences, 3);
    }

    #[test]
    fn target_owner_drift_is_fenced() {
        let (manifest, fence) = manifest();
        let checkpoint = manifest.sqlite_checkpoint_digest.clone();
        let wrong_owner =
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c99").expect("wrong owner");
        assert_eq!(
            manifest.admit_target(
                &fence,
                3_000,
                "host-b",
                &wrong_owner,
                AUTOMATION_SCHEMA_VERSION,
                8,
                &checkpoint,
            ),
            Err(AutomationError::TimerFenced)
        );
    }

    #[test]
    fn recomputed_digest_does_not_legitimize_an_invalid_owner_agent_id() {
        let (mut manifest, _) = manifest();
        manifest.owner_agent_id = "not-an-agent-id".to_string();
        manifest.manifest_digest = manifest.compute_digest().expect("recomputed digest");
        assert!(matches!(manifest.validate(), Err(AutomationError::Corrupt)));
    }

    #[test]
    fn unresolved_provider_outcome_cannot_cross_hosts() {
        let (status, fence) = fence(1);
        assert!(
            AutomationCrossHostRecoveryManifestV1::new(
                &owner(),
                &status,
                Sha256Digest::for_bytes(b"checkpoint"),
                &fence,
                2_000,
            )
            .is_err()
        );
    }

    #[test]
    fn different_or_expired_fence_cannot_admit_target() {
        let (manifest, _) = manifest();
        let (_, other_fence) = fence(0);
        let checkpoint = manifest.sqlite_checkpoint_digest.clone();
        assert_eq!(
            manifest.admit_target(
                &other_fence,
                61_000,
                "host-b",
                &owner(),
                AUTOMATION_SCHEMA_VERSION,
                8,
                &checkpoint,
            ),
            Err(AutomationError::TimerFenced)
        );
    }
}
