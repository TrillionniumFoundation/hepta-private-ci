//! Named Agentd product host for durable cognitive compaction checkpoints.
//!
//! The host composes the existing production writer owner with the canonical
//! compact.engine coordinator. It does not mint memory-write or compaction
//! authority and it never accepts a raw candidate, proof or trust key.

use std::sync::Arc;

use codex_hepta_compact_engine::{
    CompactionCoordinatorErrorV2, CompactionOperationStatusV1,
    CompactionPublicationReceiptV2, CompactionRecoveryStartupSummaryV1,
    CurrentSourceUseValidatorV1, CurrentSourceValidatedSelectionV1,
    DurableCompactionOutboxClaimV2, MemoryCheckpointCoordinatorV2,
    VerifiedCompactionPublicationV1,
};
use codex_hepta_types::Digest32;
use tokio::sync::Mutex;
use tokio::sync::MutexGuard;

use crate::{AgentdError, AgentdProductionWriterHost};

pub const AGENTD_COMPACTION_SCHEDULER_CALLER_V1: &str =
    "agentd.runtime.compaction-scheduler.v1";
const AGENTD_COMPACTION_RECOVERY_BATCH: u32 = 256;

#[derive(Clone)]
pub struct AgentdCompactionCheckpointHostV1 {
    production_writer: Arc<AgentdProductionWriterHost>,
    owner_id: String,
    coordinator: Arc<Mutex<MemoryCheckpointCoordinatorV2>>,
}

impl AgentdCompactionCheckpointHostV1 {
    #[allow(clippy::too_many_arguments)]
    pub async fn open(
        production_writer: Arc<AgentdProductionWriterHost>,
        database_url: &str,
        pinned_root_key: [u8; 32],
        manifest_chain: &[Vec<u8>],
        lease_token: &str,
        lease_epoch: u64,
        lease_expires_at_unix_seconds: u64,
        now_unix_seconds: u64,
    ) -> Result<Self, AgentdError> {
        production_writer
            .writer()
            .verify_current_authority()
            .await?;
        let owner_id = production_writer
            .writer()
            .owner_agent_id()
            .as_str()
            .to_string();
        let coordinator = MemoryCheckpointCoordinatorV2::open_with_manifest_chain(
            database_url,
            &owner_id,
            pinned_root_key,
            manifest_chain,
            lease_token,
            lease_epoch,
            lease_expires_at_unix_seconds,
            now_unix_seconds,
        )
        .await
        .map_err(compaction_error)?;
        coordinator
            .verify_integrity(now_unix_seconds)
            .await
            .map_err(compaction_error)?;
        let _ = coordinator
            .reconcile_startup(
                now_unix_seconds,
                AGENTD_COMPACTION_RECOVERY_BATCH,
            )
            .await
            .map_err(compaction_error)?;
        production_writer
            .writer()
            .verify_current_authority()
            .await?;
        Ok(Self {
            production_writer,
            owner_id,
            coordinator: Arc::new(Mutex::new(coordinator)),
        })
    }

    #[must_use]
    pub fn owner_agent_id(&self) -> &str {
        &self.owner_id
    }

    // Validate after the queue wait, not before it. The returned guard keeps
    // one host operation serialized while its owner authority is checked.
    async fn checked_coordinator(
        &self,
    ) -> Result<MutexGuard<'_, MemoryCheckpointCoordinatorV2>, AgentdError> {
        let coordinator = self.coordinator.lock().await;
        self.production_writer
            .writer()
            .verify_current_authority()
            .await?;
        Ok(coordinator)
    }

    pub async fn renew_owner_lease(
        &self,
        lease_expires_at_unix_seconds: u64,
        now_unix_seconds: u64,
    ) -> Result<(), AgentdError> {
        self.checked_coordinator()
            .await?
            .renew_lease(lease_expires_at_unix_seconds, now_unix_seconds)
            .await
            .map_err(compaction_error)
    }

    pub async fn install_successor_manifest(
        &self,
        manifest_bytes: &[u8],
        now_unix_seconds: u64,
    ) -> Result<Digest32, AgentdError> {
        self.checked_coordinator()
            .await?
            .install_successor_manifest(manifest_bytes, now_unix_seconds)
            .await
            .map_err(compaction_error)
    }

    pub async fn publish_checkpoint(
        &self,
        idempotency_key: &str,
        publication: &VerifiedCompactionPublicationV1,
        retain_source_until_unix_seconds: u64,
        now_unix_seconds: u64,
    ) -> Result<CompactionPublicationReceiptV2, AgentdError> {
        self.checked_coordinator()
            .await?
            .publish_verified_checkpoint(
                idempotency_key,
                publication,
                retain_source_until_unix_seconds,
                now_unix_seconds,
            )
            .await
            .map_err(compaction_error)
    }

    /// Product recovery always re-admits current source validity. The host does
    /// not expose the coordinator's low-level historical reconstruction path.
    pub async fn recover_current_checkpoint(
        &self,
        scope_id: &str,
        purpose_id: &str,
        now_unix_seconds: u64,
        validator: &dyn CurrentSourceUseValidatorV1,
    ) -> Result<Option<CurrentSourceValidatedSelectionV1>, AgentdError> {
        // Do not hold the Agentd serialization mutex while the external source
        // owner is consulted. The cloned coordinator rechecks manifest, lease
        // and current head after that await; a concurrent rotation fails closed.
        let coordinator = {
            let guard = self.checked_coordinator().await?;
            (*guard).clone()
        };
        let selection = coordinator
            .recover_current_checkpoint_validated(
                scope_id,
                purpose_id,
                now_unix_seconds,
                validator,
            )
            .await?;
        // Source validity cannot outlive the current Agentd writer authority.
        self.production_writer
            .writer()
            .verify_current_authority()
            .await?;
        Ok(selection)
    }

    pub async fn revoke_checkpoint(
        &self,
        checkpoint_digest: Digest32,
        reason_digest: Digest32,
        revoked_at_unix_seconds: u64,
    ) -> Result<Digest32, AgentdError> {
        self.checked_coordinator()
            .await?
            .revoke_checkpoint(
                checkpoint_digest,
                reason_digest,
                revoked_at_unix_seconds,
            )
            .await
            .map_err(compaction_error)
    }

    pub async fn release_source_retention(
        &self,
        checkpoint_digest: Digest32,
        now_unix_seconds: u64,
    ) -> Result<(), AgentdError> {
        self.checked_coordinator()
            .await?
            .release_source_retention(checkpoint_digest, now_unix_seconds)
            .await
            .map_err(compaction_error)
    }

    pub async fn claim_next_publication_event(
        &self,
        now_unix_seconds: u64,
        worker_id: &str,
        claim_token: &str,
        claim_deadline_unix_seconds: u64,
    ) -> Result<Option<DurableCompactionOutboxClaimV2>, AgentdError> {
        self.checked_coordinator()
            .await?
            .claim_next_outbox_for_worker(
                now_unix_seconds,
                worker_id,
                claim_token,
                claim_deadline_unix_seconds,
            )
            .await
            .map_err(compaction_error)
    }

    pub async fn complete_publication_event(
        &self,
        claim: &DurableCompactionOutboxClaimV2,
        delivered_at_unix_seconds: u64,
    ) -> Result<(), AgentdError> {
        self.checked_coordinator()
            .await?
            .complete_outbox_claim(claim, delivered_at_unix_seconds)
            .await
            .map_err(compaction_error)
    }

    /// Query the original operation identity after an unknown publish outcome.
    /// Callers must not mint a new idempotency key to infer whether it committed.
    pub async fn query_publication_operation(
        &self,
        idempotency_key: &str,
    ) -> Result<CompactionOperationStatusV1, AgentdError> {
        self.checked_coordinator()
            .await?
            .query_operation(idempotency_key)
            .await
            .map_err(compaction_error)
    }

    pub async fn reconcile_startup(
        &self,
        now_unix_seconds: u64,
    ) -> Result<CompactionRecoveryStartupSummaryV1, AgentdError> {
        let coordinator = self.checked_coordinator().await?;
        coordinator
            .verify_integrity(now_unix_seconds)
            .await
            .map_err(compaction_error)?;
        coordinator
            .reconcile_startup(
                now_unix_seconds,
                AGENTD_COMPACTION_RECOVERY_BATCH,
            )
            .await
            .map_err(compaction_error)
    }
}

fn compaction_error(error: CompactionCoordinatorErrorV2) -> AgentdError {
    AgentdError::Compaction(error)
}
