//! Agentd composition of the durable operation ledger with the existing
//! production CognitiveStore owner.
//!
//! The source ledger never writes the destination database directly. Agentd
//! persists dispatch-start first, then enters the already-authorized
//! `ProductionDurableWriter`, whose CognitiveStore owns the terminal
//! destination dedupe/apply record. Crash recovery queries that destination
//! record; it never re-sends a dispatched operation blindly.

use std::sync::Arc;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CrossOwnerOperationApply;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_memory::ProductionWriterError;
use codex_hepta_operations::DispatchLease;
use codex_hepta_operations::DispatchStartDisposition;
use codex_hepta_operations::DurableOperationRecord;
use codex_hepta_operations::DurableOperationState;
use codex_hepta_operations::DurableOperationStore;
use codex_hepta_operations::OperationError;
use codex_hepta_operations::PreparedIntent;
use codex_hepta_operations::ReconciliationOutcome;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AgentdProductionWriterHost;

pub const AGENTD_OPERATION_SOURCE_OWNER: &str = "runtime.agentd";
pub const AGENTD_COGNITIVE_DESTINATION: &str = "cognitive.store";

#[derive(Debug, thiserror::Error)]
pub enum AgentdOperationCoordinatorError {
    #[error(transparent)]
    Operation(#[from] OperationError),
    #[error(transparent)]
    ProductionWriter(#[from] ProductionWriterError),
    #[error("invalid operation composition: {0}")]
    Invalid(String),
    #[error("operation dispatch already crossed the destination boundary; reconciliation required")]
    ReconciliationRequired,
}

#[derive(Clone)]
pub struct AgentdOperationCoordinator {
    operations: Arc<DurableOperationStore>,
    writer: Arc<ProductionDurableWriter>,
    source_owner: StableId,
    destination: StableId,
}

impl AgentdOperationCoordinator {
    pub fn from_host(
        operations: Arc<DurableOperationStore>,
        host: &AgentdProductionWriterHost,
    ) -> Result<Self, AgentdOperationCoordinatorError> {
        Ok(Self {
            operations,
            writer: host.writer(),
            source_owner: StableId::new(AGENTD_OPERATION_SOURCE_OWNER)
                .map_err(|error| AgentdOperationCoordinatorError::Invalid(error.to_string()))?,
            destination: StableId::new(AGENTD_COGNITIVE_DESTINATION)
                .map_err(|error| AgentdOperationCoordinatorError::Invalid(error.to_string()))?,
        })
    }

    pub fn operations(&self) -> &Arc<DurableOperationStore> {
        &self.operations
    }

    pub fn writer(&self) -> &Arc<ProductionDurableWriter> {
        &self.writer
    }

    pub async fn prepare(
        &self,
        operation_id: StableId,
        scope_digest: Digest32,
        payload: Vec<u8>,
        expected_predecessor: Option<Digest32>,
    ) -> Result<DurableOperationRecord, AgentdOperationCoordinatorError> {
        let owner_generation = self.current_generation()?;
        let authority_epoch = self.current_authority_epoch()?;
        let payload_digest = Digest32::of_bytes(&payload);
        let record = self
            .operations
            .prepare_intent(
                PreparedIntent {
                    operation_id,
                    owner_id: self.source_owner.clone(),
                    scope_digest,
                    payload_digest,
                    destination: self.destination.clone(),
                    expected_predecessor,
                    owner_generation,
                    authority_epoch,
                },
                payload,
            )
            .await?;
        self.align_authority(record).await
    }

    pub async fn claim(
        &self,
        operation_id: &StableId,
        worker_id: &StableId,
        lease_ms: i64,
    ) -> Result<DispatchLease, AgentdOperationCoordinatorError> {
        let record = self
            .operations
            .get(operation_id)
            .await?
            .ok_or_else(|| OperationError::Missing(operation_id.clone()))?;
        let aligned = self.align_authority(record).await?;
        Ok(self
            .operations
            .claim_outbox(
                operation_id,
                aligned.intent.owner_generation,
                aligned.intent.authority_epoch,
                worker_id,
                lease_ms,
            )
            .await?)
    }

    /// Apply one claimed operation to the real CognitiveStore owner.
    ///
    /// Dispatch-start is committed first. If destination application returns an
    /// error, the source is marked indeterminate rather than requeued.
    pub async fn apply_claimed(
        &self,
        lease: &DispatchLease,
    ) -> Result<DurableOperationRecord, AgentdOperationCoordinatorError> {
        self.require_current_lease_authority(lease)?;
        match self
            .operations
            .record_dispatch_started(lease, lease.envelope().attempt_digest())
            .await?
        {
            DispatchStartDisposition::Started => {}
            DispatchStartDisposition::AlreadyStarted => {
                return Err(AgentdOperationCoordinatorError::ReconciliationRequired);
            }
        }

        let apply = CrossOwnerOperationApply {
            operation_id: lease.operation_id().as_str().to_string(),
            source_owner_id: lease.envelope().owner_id.as_str().to_string(),
            semantic_digest: sha_digest(lease.envelope().semantic_digest)?,
            payload_digest: sha_digest(lease.envelope().payload_digest)?,
            payload: lease.payload().to_vec(),
        };
        let receipt = match self.writer.apply_cross_owner_operation(&apply).await {
            Ok(receipt) => receipt,
            Err(error) => {
                let reason = destination_error_digest(&error);
                let _ = self.operations.mark_indeterminate(lease, reason).await;
                return Err(error.into());
            }
        };
        let terminal_digest = digest32(&receipt.receipt_digest)?;
        Ok(self
            .operations
            .observe_terminal(
                lease.operation_id(),
                ReconciliationOutcome::Applied,
                terminal_digest,
                lease.envelope().owner_generation,
                lease.envelope().authority_epoch,
            )
            .await?)
    }

    /// Resolve a dispatched/indeterminate operation from the destination's
    /// authoritative dedupe/apply record. Missing means NotApplied for this
    /// local transaction boundary; a present exact receipt means Applied.
    pub async fn reconcile(
        &self,
        operation_id: &StableId,
    ) -> Result<DurableOperationRecord, AgentdOperationCoordinatorError> {
        let record = self
            .operations
            .get(operation_id)
            .await?
            .ok_or_else(|| OperationError::Missing(operation_id.clone()))?;
        if record.state.is_terminal() {
            return Ok(record);
        }
        let record = self.align_authority(record).await?;
        if !matches!(
            record.state,
            DurableOperationState::Dispatched | DurableOperationState::Indeterminate
        ) {
            return Err(OperationError::InvalidTransition {
                from: record.state.label(),
                to: "terminal_reconciliation",
            }
            .into());
        }

        let semantic = sha_digest(record.semantic_digest)?;
        let payload = sha_digest(record.intent.payload_digest)?;
        let observation = self
            .writer
            .observe_cross_owner_operation(operation_id.as_str(), &semantic, &payload)
            .await;
        let (outcome, evidence) = match observation {
            Ok(Some(receipt)) => (
                ReconciliationOutcome::Applied,
                digest32(&receipt.receipt_digest)?,
            ),
            Ok(None) => (
                ReconciliationOutcome::NotApplied,
                not_applied_observation_digest(&record),
            ),
            Err(error) => {
                if record.state == DurableOperationState::Dispatched {
                    let _ = self
                        .operations
                        .mark_recovered_indeterminate(
                            operation_id,
                            destination_error_digest(&error),
                            record.intent.owner_generation,
                            record.intent.authority_epoch,
                        )
                        .await;
                }
                return Err(error.into());
            }
        };
        Ok(self
            .operations
            .observe_terminal(
                operation_id,
                outcome,
                evidence,
                record.intent.owner_generation,
                record.intent.authority_epoch,
            )
            .await?)
    }

    async fn align_authority(
        &self,
        record: DurableOperationRecord,
    ) -> Result<DurableOperationRecord, AgentdOperationCoordinatorError> {
        if record.state.is_terminal() {
            return Ok(record);
        }
        let generation = self.current_generation()?;
        let authority_epoch = self.current_authority_epoch()?;
        if generation < record.intent.owner_generation
            || authority_epoch < record.intent.authority_epoch
        {
            return Err(AgentdOperationCoordinatorError::Invalid(
                "production writer authority regressed behind the operation ledger".to_string(),
            ));
        }
        if generation == record.intent.owner_generation {
            if authority_epoch == record.intent.authority_epoch {
                return Ok(record);
            }
            return Ok(self
                .operations
                .rotate_authority_epoch(
                    &record.intent.operation_id,
                    generation,
                    authority_epoch,
                )
                .await?);
        }
        if authority_epoch <= record.intent.authority_epoch {
            return Err(AgentdOperationCoordinatorError::Invalid(
                "new owner generation requires a newer authority epoch".to_string(),
            ));
        }
        Ok(self
            .operations
            .handoff_owner(
                &record.intent.operation_id,
                record.intent.owner_generation,
                generation,
                authority_epoch,
            )
            .await?)
    }

    fn require_current_lease_authority(
        &self,
        lease: &DispatchLease,
    ) -> Result<(), AgentdOperationCoordinatorError> {
        if lease.envelope().owner_id != self.source_owner
            || lease.envelope().destination != self.destination
            || lease.envelope().owner_generation != self.current_generation()?
            || lease.envelope().authority_epoch != self.current_authority_epoch()?
        {
            return Err(AgentdOperationCoordinatorError::Invalid(
                "dispatch lease is not bound to the current Agentd production writer".to_string(),
            ));
        }
        Ok(())
    }

    fn current_generation(&self) -> Result<Generation, AgentdOperationCoordinatorError> {
        Generation::new(self.writer.generation())
            .map_err(|error| AgentdOperationCoordinatorError::Invalid(error.to_string()))
    }

    fn current_authority_epoch(&self) -> Result<Generation, AgentdOperationCoordinatorError> {
        Generation::new(self.writer.authority().authority_epoch)
            .map_err(|error| AgentdOperationCoordinatorError::Invalid(error.to_string()))
    }
}

fn sha_digest(value: Digest32) -> Result<Sha256Digest, AgentdOperationCoordinatorError> {
    Sha256Digest::parse(value.to_string())
        .map_err(|error| AgentdOperationCoordinatorError::Invalid(error.to_string()))
}

fn digest32(value: &Sha256Digest) -> Result<Digest32, AgentdOperationCoordinatorError> {
    value
        .as_str()
        .parse()
        .map_err(|error: codex_hepta_types::DigestParseError| {
            AgentdOperationCoordinatorError::Invalid(error.to_string())
        })
}

fn destination_error_digest(error: &ProductionWriterError) -> Digest32 {
    let mut bytes = b"hepta.runtime.agentd.kernel-operations.destination-error.v1\0".to_vec();
    bytes.extend_from_slice(error.to_string().as_bytes());
    Digest32::of_bytes(&bytes)
}

fn not_applied_observation_digest(record: &DurableOperationRecord) -> Digest32 {
    let mut bytes = b"hepta.runtime.agentd.kernel-operations.not-applied.v1\0".to_vec();
    bytes.extend_from_slice(record.intent.operation_id.as_str().as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(record.semantic_digest.as_array());
    bytes.extend_from_slice(record.intent.payload_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_contracts::AgentId;
    use codex_hepta_memory::CognitiveStore;
    use codex_hepta_memory::ProductionAuthorityLease;
    use codex_hepta_memory::ProductionAuthorityToken;
    use codex_hepta_memory::ProductionAuthorityVerifier;
    use codex_hepta_paths::HeptaFleetRoot;
    use codex_state::SqliteConfig;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use tempfile::TempDir;

    struct AllowVerifier;

    impl ProductionAuthorityVerifier for AllowVerifier {
        fn verify(
            &self,
            _authority: &ProductionAuthorityLease,
            _expected_agent: &AgentId,
        ) -> Result<(), String> {
            Ok(())
        }
    }

    fn agent_id(number: u8) -> AgentId {
        AgentId::parse(format!(
            "018f4f72-5f8f-7cc1-8f55-df9fb3aa2d{number:02x}"
        ))
        .unwrap()
    }

    fn authority(agent: AgentId) -> ProductionAuthorityLease {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        ProductionAuthorityLease::from_verified_parts(
            agent,
            Sha256Digest::for_bytes(b"agentd-operation-grant"),
            9,
            4,
            now + 3_600,
            ProductionAuthorityToken::from_verified_bytes(
                b"opaque-agentd-operation-token".to_vec(),
            )
            .unwrap(),
        )
        .unwrap()
    }

    async fn fixture(
        temp: &TempDir,
    ) -> (AgentdProductionWriterHost, Arc<DurableOperationStore>) {
        let fleet_root = temp.path().join("fleet");
        std::fs::create_dir_all(&fleet_root).unwrap();
        let fleet = HeptaFleetRoot::parse(fleet_root.canonicalize().unwrap()).unwrap();
        let owner = agent_id(213);
        let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await.unwrap();
        let host = AgentdProductionWriterHost::open_with_store(
            store,
            authority(owner),
            &AllowVerifier,
            "production:kernel-operations:test",
            3,
        )
        .await
        .unwrap();

        let operations_root = temp.path().join("operations");
        std::fs::create_dir_all(&operations_root).unwrap();
        let sqlite_home = AbsolutePathBuf::try_from(operations_root.canonicalize().unwrap()).unwrap();
        let operations = Arc::new(
            DurableOperationStore::open(&SqliteConfig::from_sqlite_home(sqlite_home))
                .await
                .unwrap(),
        );
        (host, operations)
    }

    fn operation_id(value: &str) -> StableId {
        StableId::new(value).unwrap()
    }

    #[tokio::test]
    async fn product_destination_apply_is_terminal_and_destination_deduplicated() {
        let temp = TempDir::new().unwrap();
        let (host, operations) = fixture(&temp).await;
        let coordinator =
            AgentdOperationCoordinator::from_host(operations.clone(), &host).unwrap();
        let operation = operation_id("operation:agentd:cognitive:1");
        coordinator
            .prepare(
                operation.clone(),
                Digest32::of_bytes(b"agent-private-scope"),
                b"{\"kind\":\"bounded-local-operation\"}".to_vec(),
                None,
            )
            .await
            .unwrap();
        let lease = coordinator
            .claim(&operation, &operation_id("worker:agentd:1"), 60_000)
            .await
            .unwrap();

        let destination_apply = CrossOwnerOperationApply {
            operation_id: lease.operation_id().as_str().to_string(),
            source_owner_id: lease.envelope().owner_id.as_str().to_string(),
            semantic_digest: sha_digest(lease.envelope().semantic_digest).unwrap(),
            payload_digest: sha_digest(lease.envelope().payload_digest).unwrap(),
            payload: lease.payload().to_vec(),
        };
        let terminal = coordinator.apply_claimed(&lease).await.unwrap();
        assert_eq!(terminal.state, DurableOperationState::Applied);

        let replay = host
            .writer()
            .apply_cross_owner_operation(&destination_apply)
            .await
            .unwrap();
        assert!(replay.replayed);
        assert_eq!(
            operations.get(&operation).await.unwrap().unwrap().state,
            DurableOperationState::Applied
        );
    }

    #[tokio::test]
    async fn lost_source_ack_reconciles_from_destination_without_resend() {
        let temp = TempDir::new().unwrap();
        let (host, operations) = fixture(&temp).await;
        let coordinator =
            AgentdOperationCoordinator::from_host(operations.clone(), &host).unwrap();
        let operation = operation_id("operation:agentd:cognitive:lost-ack");
        coordinator
            .prepare(
                operation.clone(),
                Digest32::of_bytes(b"agent-private-scope"),
                b"payload-lost-ack".to_vec(),
                None,
            )
            .await
            .unwrap();
        let lease = coordinator
            .claim(&operation, &operation_id("worker:agentd:lost-ack"), 60_000)
            .await
            .unwrap();
        operations
            .record_dispatch_started(&lease, lease.envelope().attempt_digest())
            .await
            .unwrap();

        host.writer()
            .apply_cross_owner_operation(&CrossOwnerOperationApply {
                operation_id: operation.as_str().to_string(),
                source_owner_id: lease.envelope().owner_id.as_str().to_string(),
                semantic_digest: sha_digest(lease.envelope().semantic_digest).unwrap(),
                payload_digest: sha_digest(lease.envelope().payload_digest).unwrap(),
                payload: lease.payload().to_vec(),
            })
            .await
            .unwrap();

        let reconciled = coordinator.reconcile(&operation).await.unwrap();
        assert_eq!(reconciled.state, DurableOperationState::Applied);
    }

    #[tokio::test]
    async fn absent_destination_record_reconciles_not_applied() {
        let temp = TempDir::new().unwrap();
        let (host, operations) = fixture(&temp).await;
        let coordinator =
            AgentdOperationCoordinator::from_host(operations.clone(), &host).unwrap();
        let operation = operation_id("operation:agentd:cognitive:not-applied");
        coordinator
            .prepare(
                operation.clone(),
                Digest32::of_bytes(b"agent-private-scope"),
                b"payload-not-applied".to_vec(),
                None,
            )
            .await
            .unwrap();
        let lease = coordinator
            .claim(&operation, &operation_id("worker:agentd:not-applied"), 60_000)
            .await
            .unwrap();
        operations
            .record_dispatch_started(&lease, lease.envelope().attempt_digest())
            .await
            .unwrap();

        let reconciled = coordinator.reconcile(&operation).await.unwrap();
        assert_eq!(reconciled.state, DurableOperationState::NotApplied);
    }
}
