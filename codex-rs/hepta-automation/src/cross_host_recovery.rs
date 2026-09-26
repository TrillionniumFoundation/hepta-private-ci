//! Fail-closed manifest for moving an already quiesced automation database to a
//! different host. The manifest does not copy bytes or create authority. It
//! binds the external host-fence receipt, SQLite checkpoint digest and next
//! writer epoch that a deployment controller must verify before target start.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::AUTOMATION_SCHEMA_VERSION;
use crate::AutomationError;
use crate::TimerDrainStatus;

pub const AUTOMATION_CROSS_HOST_RECOVERY_SCHEMA_VERSION: u32 = 1;
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
        source_host_id: impl Into<String>,
        target_host_id: impl Into<String>,
        drain_status: &TimerDrainStatus,
        sqlite_checkpoint_digest: Sha256Digest,
        external_fence_receipt_digest: Sha256Digest,
        exported_at_ms: u64,
    ) -> Result<Self, AutomationError> {
        let source_host_id = source_host_id.into();
        let target_host_id = target_host_id.into();
        validate_host_id(&source_host_id)?;
        validate_host_id(&target_host_id)?;
        validate_digest(&sqlite_checkpoint_digest)?;
        validate_digest(&external_fence_receipt_digest)?;
        if source_host_id == target_host_id
            || !drain_status.can_handoff()
            || drain_status.uncertain_dispatches != 0
            || exported_at_ms == 0
        {
            return Err(AutomationError::Conflict);
        }
        let required_target_writer_epoch = drain_status
            .writer_epoch
            .checked_add(1)
            .ok_or(AutomationError::Conflict)?;
        let mut manifest = Self {
            schema_version: AUTOMATION_CROSS_HOST_RECOVERY_SCHEMA_VERSION,
            owner_agent_id: owner_agent_id.as_str().to_string(),
            source_host_id,
            target_host_id,
            source_writer_epoch: drain_status.writer_epoch,
            required_target_writer_epoch,
            store_schema_version: AUTOMATION_SCHEMA_VERSION,
            pending_occurrences: drain_status.pending_occurrences,
            sqlite_checkpoint_digest,
            external_fence_receipt_digest,
            exported_at_ms,
            manifest_digest: Sha256Digest::for_bytes(b"uncomputed-cross-host-manifest-v1"),
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
            || self.owner_agent_id.is_empty()
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

    /// Verify the exact target tuple before opening the copied database for
    /// writes. The deployment controller must have already enforced the
    /// externally signed host-fence receipt bound into this manifest.
    pub fn admit_target(
        &self,
        target_host_id: &str,
        observed_store_schema_version: u32,
        observed_writer_epoch: u64,
        observed_checkpoint_digest: &Sha256Digest,
    ) -> Result<(), AutomationError> {
        self.validate()?;
        if target_host_id != self.target_host_id
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

        let mut bytes = b"hepta.automation.cross-host-recovery.v1\0".to_vec();
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
    if value.is_empty()
        || value.len() > MAX_HOST_ID_BYTES
        || value.chars().any(char::is_control)
    {
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
    use crate::TimerPhase;

    use super::*;

    #[test]
    fn cross_host_manifest_binds_checkpoint_fence_and_next_epoch() {
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
        let status = TimerDrainStatus {
            writer_epoch: 7,
            phase: TimerPhase::Draining,
            pending_occurrences: 3,
            leased_occurrences: 0,
            uncertain_dispatches: 0,
        };
        let checkpoint = Sha256Digest::for_bytes(b"checkpoint");
        let manifest = AutomationCrossHostRecoveryManifestV1::new(
            &agent,
            "host-a",
            "host-b",
            &status,
            checkpoint.clone(),
            Sha256Digest::for_bytes(b"external-fence"),
            42,
        )
        .expect("manifest");
        manifest.validate().expect("valid manifest");
        manifest
            .admit_target("host-b", AUTOMATION_SCHEMA_VERSION, 8, &checkpoint)
            .expect("target admission");
        assert_eq!(manifest.pending_occurrences, 3);
    }

    #[test]
    fn unresolved_provider_outcome_cannot_cross_hosts() {
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
        let status = TimerDrainStatus {
            writer_epoch: 7,
            phase: TimerPhase::Draining,
            pending_occurrences: 0,
            leased_occurrences: 0,
            uncertain_dispatches: 1,
        };
        assert!(
            AutomationCrossHostRecoveryManifestV1::new(
                &agent,
                "host-a",
                "host-b",
                &status,
                Sha256Digest::for_bytes(b"checkpoint"),
                Sha256Digest::for_bytes(b"external-fence"),
                42,
            )
            .is_err()
        );
    }
}
