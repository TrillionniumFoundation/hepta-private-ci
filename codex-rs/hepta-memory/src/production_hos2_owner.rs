//! HOS2 acknowledgement derives only from the original durable source owner.

use super::*;
use crate::Hos2DeliveryId;
use crate::Hos2InstallBudgetV1;
use crate::ProductionHos2Target;
use crate::production_hos2::Hos2TerminalReceipt;

/// A borrowed, non-serializable authorization to acknowledge one original
/// namespace prefix. Only the live production writer constructs this value,
/// after reading every immutable binding and durable terminal observation.
/// The digest is provenance, not a signature or a kernel capability.
pub struct Hos2RetirementPermit {
    through: Hos2DeliveryId,
    source_owner: AgentId,
    source_generation: u64,
    terminal_chain_sha256: Sha256Digest,
}

impl Hos2RetirementPermit {
    pub fn through(&self) -> &Hos2DeliveryId {
        &self.through
    }
    pub fn source_owner(&self) -> &AgentId {
        &self.source_owner
    }
    pub fn source_generation(&self) -> u64 {
        self.source_generation
    }
    pub fn terminal_chain_sha256(&self) -> &Sha256Digest {
        &self.terminal_chain_sha256
    }
}

/// Native observation only; constructing this value grants no retirement
/// authority and cannot construct a `Hos2RetirementPermit`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Hos2RetirementObservation {
    pub retired_through: u64,
    pub next_sequence: u64,
}

impl ProductionDurableWriter {
    /// Observe a complete terminal already retained by the original ledger.
    /// No caller-supplied receipt or device result can enter this read path.
    /// It grants no dispatch/retirement authority and creates no new event.
    pub async fn retained_hos2_terminal(
        &self,
        occurrence_key: &str,
    ) -> Result<(Hos2InstallBudgetV1, ProductionOutcomeReceipt, String), ProductionWriterError>
    {
        self.verify_current_authority().await?;
        let mut transaction = self
            .store
            .pool
            .begin()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let (request, receipt, terminal) = self
            .lease
            .retained_hos2_terminal(&mut transaction, occurrence_key)
            .await?;
        transaction
            .rollback()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        self.verify_current_authority().await?;
        Ok((request, receipt.into(), terminal))
    }

    /// Read a candidate D from this original owner's immutable outbox.
    /// This read grants/reserves nothing. `prepare_operation` is still the
    /// only admission: its original SQLite transaction rejects competing K,
    /// stale candidates and any nonterminal predecessor without dispatch.
    pub async fn next_hos2_delivery_candidate(
        &self,
        boot_id: [u8; 16],
        space_id: [u8; 16],
    ) -> Result<Hos2DeliveryId, ProductionWriterError> {
        self.verify_current_authority().await?;
        let namespace =
            Hos2DeliveryId::new(boot_id, space_id, 1).map_err(ProductionWriterError::Invalid)?;
        let mut transaction = self
            .store
            .pool
            .begin()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let sequence = self
            .lease
            .hos2_delivery_candidate(&mut transaction, &namespace)
            .await?;
        transaction
            .rollback()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        self.verify_current_authority().await?;
        Hos2DeliveryId::new(boot_id, space_id, sequence).map_err(ProductionWriterError::Invalid)
    }

    /// Read original durable pending state for explicit native-profile drain.
    /// Admission must already be closed and live dispatch joined by the host.
    /// A malformed/missing retained operation is an error, never a drained bit.
    pub async fn hos2_drain_blockers(&self) -> Result<u32, ProductionWriterError> {
        let retained = self.retained_pending_hos2(256).await?;
        u32::try_from(retained.len()).map_err(|_| {
            ProductionWriterError::Durability("bounded HOS2 drain count overflow".into())
        })
    }

    pub(super) async fn settle_hos2_protocol_conflict(
        &self,
        request: ProductionDispatchRequest,
        evidence: &crate::Hos2ProtocolConflict,
    ) -> Result<ProductionDispatchReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        if request.topic != crate::HOS2_INSTALL_TOPIC_V1
            || request.operation_destination_id != crate::HOS2_DESTINATION_V1
        {
            return Err(ProductionWriterError::Invalid(
                "HOS2 contradiction targets another destination".to_string(),
            ));
        }
        evidence
            .matches(&request.occurrence_key, &request.payload_json)
            .map_err(ProductionWriterError::Invalid)?;
        let reason = evidence.to_json().map_err(ProductionWriterError::Invalid)?;
        let local = self
            .lease
            .record_hos2_protocol_conflict(&request.occurrence_key, evidence)
            .await?;
        Ok(ProductionDispatchReceipt {
            request,
            state: LocalOutcomeState::RolledBack,
            target_disposition: ProductionTargetDisposition::Indeterminate,
            target_receipt: None,
            target_reason: Some(reason),
            local_event_id: local.event_id,
            external_effect: false,
        })
    }

    pub(super) async fn settle_hos2_terminal(
        &self,
        request: &ProductionDispatchRequest,
        evidence: &str,
        expected_outcome: LocalReconcileOutcome,
    ) -> Result<ProductionOutcomeReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        let payload = Hos2InstallBudgetV1::from_json(&request.payload_json)
            .map_err(ProductionWriterError::Invalid)?;
        let receipt = Hos2TerminalReceipt::from_json(evidence, &payload)
            .map_err(ProductionWriterError::Invalid)?;
        if receipt.outcome() != expected_outcome {
            return Err(ProductionWriterError::Invalid(
                "HOS2 target disposition differs from terminal evidence".to_string(),
            ));
        }
        Ok(self
            .lease
            .reconcile_hos2_terminal(&request.occurrence_key, &receipt)
            .await?
            .into())
    }

    /// Acknowledge the exact requested prefix using the target's retained
    /// history capability. A lost native acknowledgement can repeat this
    /// method: the source proof is rebuilt from the same immutable journal,
    /// and the kernel's original frontier operation is idempotent.
    pub async fn retire_hos2_through(
        &self,
        target: &ProductionHos2Target,
        through: &Hos2DeliveryId,
    ) -> Result<Hos2RetirementObservation, ProductionWriterError> {
        self.verify_authority().await?;
        let mut transaction = self
            .store
            .begin_checkpoint_barrier()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let terminal_chain_sha256 = self
            .lease
            .hos2_durable_prefix(&mut transaction, through)
            .await?;
        self.acknowledge_bound_owner_transaction(&mut transaction)
            .await?;
        let permit = Hos2RetirementPermit {
            through: through.clone(),
            source_owner: self.owner_agent_id().clone(),
            source_generation: self.generation(),
            terminal_chain_sha256,
        };
        // Recheck the original live verifier after all SQLite awaits. This
        // check is the source authorization observation immediately before
        // entry, not a claim to retain an issuer lock across the device call.
        self.retirement_live_check()?;
        let observation = target
            .retire(&permit)
            .map_err(ProductionWriterError::Durability)?;
        let requested = through.sequence().map_err(ProductionWriterError::Invalid)?;
        if observation.retired_through < requested
            || observation.next_sequence <= observation.retired_through
        {
            return Err(ProductionWriterError::Durability(
                "native retirement acknowledgement is invalid".to_string(),
            ));
        }
        transaction
            .rollback()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        Ok(observation)
    }
}
