//! HOS2 values and destination adapter for the original production outbox.
//!
//! The immutable outbox payload is the K-to-D binding. Kernel capabilities,
//! FinalUse grants and the durable writer are supplied by their existing owners.
//! This module neither opens a writer nor issues an authorization grant.

use std::sync::Arc;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::FinalUseProductionOutboxTarget;
use crate::Hos2RetirementObservation;
use crate::Hos2RetirementPermit;
use crate::ProductionDispatchFuture;
use crate::ProductionDispatchRequest;
use crate::ProductionOutboxTarget;
use crate::ProductionTargetOutcome;
use crate::ProductionTerminalObservation;
use crate::ProductionTerminalObservationFuture;

#[path = "production_hos2_terminal.rs"]
mod terminal_receipt;
pub(crate) use terminal_receipt::Hos2TerminalReceipt;

#[path = "production_hos2_conflict.rs"]
mod protocol_conflict;
pub use protocol_conflict::Hos2InstallContradiction;
pub use protocol_conflict::Hos2InstallOutcome;
pub use protocol_conflict::Hos2ProtocolConflict;

pub const HOS2_INSTALL_TOPIC_V1: &str = "hepta.hos2.install-budget.v1";
pub const HOS2_DESTINATION_V1: &str = "hos2.cpu-budget.v1";
pub const HOS2_CPU_PERIOD_NS: u64 = 100_000_000;

/// Value identity only. Possessing a D does not grant a kernel slot or history
/// acknowledgement capability. The hexadecimal sequence preserves all u64
/// values in SQLite JSON without a signed-integer or floating-point conversion.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Hos2DeliveryId {
    pub boot_id: [u8; 16],
    pub space_id: [u8; 16],
    sequence: String,
}

impl Hos2DeliveryId {
    pub fn new(boot_id: [u8; 16], space_id: [u8; 16], sequence: u64) -> Result<Self, String> {
        let id = Self {
            boot_id,
            space_id,
            sequence: format!("{sequence:016x}"),
        };
        id.sequence()?;
        Ok(id)
    }

    pub fn sequence(&self) -> Result<u64, String> {
        let sequence = u64::from_str_radix(&self.sequence, 16)
            .map_err(|_| "invalid HOS2 sequence".to_string())?;
        if self.boot_id == [0; 16]
            || self.space_id == [0; 16]
            || sequence == 0
            || sequence == u64::MAX
            || self.sequence != format!("{sequence:016x}")
        {
            return Err("invalid HOS2 delivery identity".to_string());
        }
        Ok(sequence)
    }
}

/// Complete immutable InstallBudget request, including the original namespace
/// and exact process-image slot. Recovery must reuse these bytes for this K.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Hos2InstallBudgetV1 {
    pub schema_version: u32,
    pub delivery: Hos2DeliveryId,
    pub manage_slot: u64,
    pub manage_generation: u64,
    pub expected_revision: u64,
    pub period_ns: u64,
    pub cap_ns: u64,
}

impl Hos2InstallBudgetV1 {
    pub fn to_json(&self) -> Result<String, String> {
        self.delivery.sequence()?;
        if self.schema_version != 1
            || self.manage_slot == 0
            || self.manage_generation == 0
            || self.expected_revision == 0
            || self.expected_revision == u64::MAX
            || self.period_ns != HOS2_CPU_PERIOD_NS
            || self.cap_ns > self.period_ns
        {
            return Err("invalid HOS2 InstallBudget request".to_string());
        }
        serde_json::to_string(self).map_err(|error| error.to_string())
    }

    pub fn from_json(payload: &str) -> Result<Self, String> {
        let value: Self = serde_json::from_str(payload).map_err(|error| error.to_string())?;
        if value.to_json()? != payload {
            return Err("HOS2 outbox payload is not canonical".to_string());
        }
        Ok(value)
    }

    /// Scope binds the exact native namespace and process-image slot. Its hash
    /// is a request constraint, never a replacement for the retained capability.
    pub fn scope_digest(&self) -> Digest32 {
        let mut scope = b"hepta.hos2.cpu-budget.scope.v1\0".to_vec();
        scope.extend_from_slice(&self.delivery.boot_id);
        scope.extend_from_slice(&self.delivery.space_id);
        scope.extend_from_slice(&self.manage_slot.to_le_bytes());
        scope.extend_from_slice(&self.manage_generation.to_le_bytes());
        Digest32::of_bytes(&scope)
    }
}

/// An observation of the original D, obtained through a retained native
/// history capability. NotSeen, Retired and HistoryLost prove no terminal
/// outcome to a source that has not already persisted that outcome.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum Hos2DeliveryObservation {
    Applied {
        stable_object_id: [u8; 16],
        previous_revision: u64,
        revision: u64,
        effective_ns: u64,
        consumed_ns: u64,
    },
    NotApplied { status: u16 },
    Reserved,
    NotSeen,
    Retired,
    HistoryLost,
}

/// Native transport owned by the already-authorized process image. `install`
/// must complete its bounded synchronous device call before returning; it may
/// not enqueue an effect in a future or detached task. `query` never dispatches.
/// Implementations validate the correlated HOS2 response and exact namespace.
pub trait Hos2Device: Send + Sync {
    fn install(&self, request: &Hos2InstallBudgetV1) -> Result<Hos2InstallOutcome, String>;
    /// Validate the entire persisted request against the retained history
    /// domain and fixed resource grant before observing D. Recovery may hold
    /// another image's history namespace without being allowed to install in
    /// it. Inaccessible history remains unavailable; a known contradictory
    /// request must not be turned into an older D's terminal observation.
    fn observe(&self, request: &Hos2InstallBudgetV1) -> Result<Hos2InstallOutcome, String>;
    /// Raw history values alone do not prove the source request's binding.
    fn query(&self, delivery: &Hos2DeliveryId) -> Result<Hos2DeliveryObservation, String>;
    /// Consume only the original source owner's borrowed durable-prefix proof.
    /// The actual native history capability remains independently required.
    fn retire(&self, permit: &Hos2RetirementPermit) -> Result<Hos2RetirementObservation, String>;
}

/// Adapter attached to the existing ProductionFinalUseOutboxDispatcher. It
/// does not hold a signer, alternate dispatcher, lease or mutable database.
pub struct ProductionHos2Target {
    device: Arc<dyn Hos2Device>,
}

impl ProductionHos2Target {
    pub fn new(device: Arc<dyn Hos2Device>) -> Self {
        Self { device }
    }

    pub(crate) fn retire(&self, permit: &Hos2RetirementPermit) -> Result<Hos2RetirementObservation, String> {
        self.device.retire(permit)
    }

    fn decode(&self, request: &ProductionDispatchRequest) -> Result<Hos2InstallBudgetV1, String> {
        if request.topic != HOS2_INSTALL_TOPIC_V1
            || request.operation_destination_id != HOS2_DESTINATION_V1
            || request.occurrence_key != request.idempotency_key
            || Sha256Digest::for_bytes(request.payload_json.as_bytes()) != request.payload_sha256
            || request.expected_predecessor_sha256.is_some()
        {
            return Err("HOS2 dispatch does not match its durable operation".to_string());
        }
        let payload = Hos2InstallBudgetV1::from_json(&request.payload_json)?;
        let intent = OperationIntentV1::new(
            StableId::new(&request.occurrence_key).map_err(|error| error.to_string())?,
            StableId::new(&request.operation_subject_id).map_err(|error| error.to_string())?,
            StableId::new(HOS2_DESTINATION_V1).map_err(|error| error.to_string())?,
            Digest32::of_bytes(request.payload_json.as_bytes()),
            payload.scope_digest(),
            Generation::new(request.operation_policy_generation).map_err(|error| error.to_string())?,
            /*expected_predecessor*/ None,
        )
        .map_err(|error| error.to_string())?;
        if intent.semantic_digest().to_string() != request.operation_semantic_sha256.as_str()
            || intent.scope_digest().to_string() != request.operation_scope_sha256.as_str()
        {
            return Err("HOS2 semantic operation or scope digest mismatch".to_string());
        }
        Ok(payload)
    }
}

impl ProductionOutboxTarget for ProductionHos2Target {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        // Deliberately evaluate before constructing the future, in the
        // original synchronous FinalUse consumer-entry closure. A later
        // revocation is ordered after that entry; no task is queued here.
        let outcome = match self.decode(&request) {
            Err(reason) => ProductionTargetOutcome::Rejected { reason },
            Ok(payload) => match self.device.install(&payload) {
                Ok(Hos2InstallOutcome::Contradiction(contradiction)) => {
                    match Hos2ProtocolConflict::new(&request.occurrence_key, &payload, contradiction) {
                        Ok(evidence) => ProductionTargetOutcome::Hos2ProtocolConflict { evidence: Box::new(evidence) },
                        Err(reason) => ProductionTargetOutcome::Indeterminate { reason },
                    }
                }
                Ok(Hos2InstallOutcome::Observed(observation)) => match terminal(&payload, observation) {
                    ProductionTerminalObservation::Hos2ProtocolConflict { evidence } => {
                        ProductionTargetOutcome::Hos2ProtocolConflict { evidence }
                    }
                    ProductionTerminalObservation::Applied { receipt } => {
                        ProductionTargetOutcome::Committed { receipt }
                    }
                    ProductionTerminalObservation::NotApplied { reason } => {
                        ProductionTargetOutcome::NotApplied { reason }
                    }
                    ProductionTerminalObservation::Indeterminate { reason }
                    | ProductionTerminalObservation::Unavailable { reason }
                    | ProductionTerminalObservation::Quarantined { reason } => {
                        ProductionTargetOutcome::Indeterminate { reason }
                    }
                },
                Err(reason) => ProductionTargetOutcome::Indeterminate { reason },
            },
        };
        Box::pin(async move { outcome })
    }
}

impl FinalUseProductionOutboxTarget for ProductionHos2Target {
    fn destination_id(&self) -> &str {
        HOS2_DESTINATION_V1
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        let observation = match self.decode(request) {
            Ok(payload) => match self.device.observe(&payload) {
                Ok(Hos2InstallOutcome::Observed(observation)) => terminal(&payload, observation),
                Ok(Hos2InstallOutcome::Contradiction(contradiction)) => {
                    match Hos2ProtocolConflict::new(&request.occurrence_key, &payload, contradiction) {
                        Ok(evidence) => ProductionTerminalObservation::Hos2ProtocolConflict { evidence: Box::new(evidence) },
                        Err(reason) => ProductionTerminalObservation::Unavailable { reason },
                    }
                }
                Err(reason) => ProductionTerminalObservation::Unavailable { reason },
            },
            Err(reason) => ProductionTerminalObservation::Unavailable { reason },
        };
        Box::pin(async move { observation })
    }
}

fn terminal(
    payload: &Hos2InstallBudgetV1,
    observation: Hos2DeliveryObservation,
) -> ProductionTerminalObservation {
    let receipt = match Hos2TerminalReceipt::new(payload, observation) {
        Ok(receipt) => receipt,
        Err(reason) => return ProductionTerminalObservation::Indeterminate { reason },
    };
    let encoded = match receipt.to_json() {
        Ok(encoded) => encoded,
        Err(reason) => return ProductionTerminalObservation::Unavailable { reason },
    };
    match receipt.outcome() {
        crate::LocalReconcileOutcome::Committed => ProductionTerminalObservation::Applied { receipt: encoded },
        crate::LocalReconcileOutcome::Rejected => ProductionTerminalObservation::NotApplied { reason: encoded },
        crate::LocalReconcileOutcome::StillIndeterminate => ProductionTerminalObservation::Indeterminate {
            reason: "native terminal receipt did not carry a terminal outcome".to_string(),
        },
    }
}
