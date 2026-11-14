//! One finite Calculator destination under the original production writer.
//! This target creates neither authority nor an operation ledger. It enters
//! synchronously under FinalUse; an ambiguous exchange is observed, never resent.

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Serialize;

use crate::FinalUseProductionOutboxTarget;
use crate::LocalReconcileOutcome;
use crate::ProductionDispatchFuture;
use crate::ProductionDispatchRequest;
use crate::ProductionOutboxTarget;
use crate::ProductionTargetOutcome;
use crate::ProductionTerminalObservation;
use crate::ProductionTerminalObservationFuture;

#[path = "production_calculator_model.rs"]
mod model;
pub use model::CALCULATOR_EVALUATE_TOPIC_V1;
pub use model::CALCULATOR_REQUEST_MAX_BYTES;
pub use model::CALCULATOR_RESPONSE_MAX_BYTES;
use model::CalculatorEvaluate;
pub use model::CalculatorOperator;
use model::CalculatorResult;
pub use model::CalculatorTargetIdentity;
pub use model::CalculatorValueState;
use model::parse_evaluate;
use model::parse_response;

#[path = "production_calculator_read.rs"]
mod read;
pub use read::CalculatorState;
pub use read::ProductionCalculatorObserver;
#[path = "production_calculator_previous.rs"]
mod previous;
#[path = "production_calculator_retire.rs"]
mod retire;
pub use previous::ProductionCalculatorRecoveryTarget;

/// A narrowed, already inherited observation capability. Implementations may
/// carry only readback, exact operation observation and terminal receipt ACKs.
pub trait CalculatorRecoveryChannel: Send + Sync {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String>;
}

/// The actual inherited Calculator channel. Exchanges are synchronous and
/// bounded; invalidation permanently closes its effect stream. Recovery owns
/// a distinct descriptor and must never reconnect or replay an effect.
pub trait CalculatorPrivateChannel: Send + Sync {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String>;
    fn invalidate(&self);
    fn recovery_handle(&self) -> Arc<dyn CalculatorRecoveryChannel>;
}

/// Compile the exact payload into the original authority-free intent. The
/// original writer must retain this intent and these unchanged payload bytes.
pub fn calculator_operation_intent(
    target: &CalculatorTargetIdentity,
    payload: &str,
    subject: StableId,
    policy_generation: Generation,
) -> Result<OperationIntentV1, String> {
    let parsed = parse_evaluate(target, payload)?;
    OperationIntentV1::new(
        StableId::new(parsed.operation_id).map_err(|error| error.to_string())?,
        subject,
        StableId::new(target.destination_id()).map_err(|error| error.to_string())?,
        Digest32::of_bytes(payload.as_bytes()),
        target.scope_digest(),
        policy_generation,
        Some(target.predecessor_digest(parsed.expected_revision)),
    )
    .map_err(|error| error.to_string())
}

/// One registered incarnation. The sole retained hash suppresses duplicate
/// metadata retirement; all durable operation state stays with the writer.
pub struct ProductionCalculatorTarget {
    identity: CalculatorTargetIdentity,
    destination: String,
    channel: Arc<dyn CalculatorPrivateChannel>,
    recovery: Arc<dyn CalculatorRecoveryChannel>,
    retired_receipt: Mutex<Option<Sha256Digest>>,
}

impl ProductionCalculatorTarget {
    pub fn new(
        identity: CalculatorTargetIdentity,
        channel: Arc<dyn CalculatorPrivateChannel>,
    ) -> Result<Self, String> {
        identity.validate()?;
        Ok(Self {
            destination: identity.destination_id(),
            identity,
            recovery: channel.recovery_handle(),
            channel,
            retired_receipt: Mutex::new(None),
        })
    }

    fn decode(&self, request: &ProductionDispatchRequest) -> Result<CalculatorEvaluate, String> {
        let parsed = parse_evaluate(&self.identity, &request.payload_json)?;
        let intent = calculator_operation_intent(
            &self.identity,
            &request.payload_json,
            StableId::new(&request.operation_subject_id).map_err(|error| error.to_string())?,
            Generation::new(request.operation_policy_generation)
                .map_err(|error| error.to_string())?,
        )?;
        let predecessor = self
            .identity
            .predecessor_digest(parsed.expected_revision)
            .to_string();
        if request.schema_version != crate::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION
            || request.namespace != crate::PRODUCTION_DURABLE_WRITER_NAMESPACE
            || request.topic != CALCULATOR_EVALUATE_TOPIC_V1
            || request.operation_destination_id != self.destination
            || request.occurrence_key != parsed.operation_id
            || request.idempotency_key != parsed.operation_id
            || request.payload_sha256 != Sha256Digest::for_bytes(request.payload_json.as_bytes())
            || request.operation_scope_sha256.as_str() != intent.scope_digest().to_string()
            || request.operation_semantic_sha256.as_str() != intent.semantic_digest().to_string()
            || request
                .expected_predecessor_sha256
                .as_ref()
                .map(Sha256Digest::as_str)
                != Some(predecessor.as_str())
        {
            return Err("Calculator differs from the original durable operation".into());
        }
        Ok(parsed)
    }
}

/// Sealed evidence for the existing source journal. Public callers cannot use
/// an untyped terminal outcome to settle a Calculator operation.
pub(crate) struct CalculatorTerminalReceipt {
    raw: String,
    outcome: LocalReconcileOutcome,
}

impl CalculatorTerminalReceipt {
    pub(crate) fn from_json(payload: &str, evidence: &str) -> Result<Self, String> {
        let parsed: CalculatorEvaluate =
            serde_json::from_str(payload).map_err(|_| "invalid Calculator payload")?;
        let parsed = parse_evaluate(&parsed.target, payload)?;
        let (result, raw) = parse_response(
            &parsed.target,
            evidence.as_bytes().to_vec(),
            &parsed,
            Sha256Digest::for_bytes(payload.as_bytes()).as_str(),
        )?;
        let outcome = match result {
            CalculatorResult::Applied { .. } => LocalReconcileOutcome::Committed,
            CalculatorResult::NotApplied { .. } => LocalReconcileOutcome::Rejected,
            CalculatorResult::Unknown { .. } => {
                return Err("unknown Calculator observation is not terminal".into());
            }
        };
        Ok(Self { raw, outcome })
    }

    pub(crate) fn outcome(&self) -> LocalReconcileOutcome {
        self.outcome
    }

    pub(crate) fn as_str(&self) -> &str {
        &self.raw
    }

    pub(crate) fn matches(&self, payload: &str) -> Result<(), String> {
        if Self::from_json(payload, &self.raw)?.outcome != self.outcome {
            return Err("Calculator terminal disposition mismatch".into());
        }
        Ok(())
    }
}

impl ProductionOutboxTarget for ProductionCalculatorTarget {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        // Actual entry happens here, while the original FinalUse barrier is
        // held. The returned future carries only the already observed outcome.
        let outcome = match self.decode(&request) {
            Err(reason) => ProductionTargetOutcome::Rejected { reason },
            Ok(parsed) => match self
                .channel
                .exchange(request.payload_json.as_bytes())
                .and_then(|bytes| {
                    parse_response(
                        &self.identity,
                        bytes,
                        &parsed,
                        request.payload_sha256.as_str(),
                    )
                }) {
                Ok((CalculatorResult::Applied { .. }, receipt)) => {
                    ProductionTargetOutcome::Committed { receipt }
                }
                Ok((
                    CalculatorResult::NotApplied {
                        reason,
                        current_revision,
                    },
                    receipt,
                )) => {
                    let _ = (reason, current_revision);
                    ProductionTargetOutcome::NotApplied { reason: receipt }
                }
                Ok((CalculatorResult::Unknown { current_revision }, _)) => {
                    self.channel.invalidate();
                    ProductionTargetOutcome::Indeterminate {
                        reason: format!("Calculator receipt absent at revision {current_revision}"),
                    }
                }
                Err(reason) => {
                    self.channel.invalidate();
                    ProductionTargetOutcome::Indeterminate { reason }
                }
            },
        };
        Box::pin(async move { outcome })
    }
}

#[derive(Serialize)]
struct CalculatorObserve<'a> {
    schema_version: u16,
    action: &'static str,
    target: &'a CalculatorTargetIdentity,
    operation_id: &'a str,
    payload_sha256: &'a str,
}

impl FinalUseProductionOutboxTarget for ProductionCalculatorTarget {
    fn destination_id(&self) -> &str {
        &self.destination
    }

    fn retire_calculator_receipt(
        &self,
        permit: &crate::CalculatorRetirementPermit,
    ) -> Result<crate::ProductionRetirementAck, String> {
        retire::retire(self, permit)
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        let observation = match self.decode(request) {
            Err(reason) => ProductionTerminalObservation::Unavailable { reason },
            Ok(parsed) => {
                let query = CalculatorObserve {
                    schema_version: 1,
                    action: "observe",
                    target: &self.identity,
                    operation_id: &parsed.operation_id,
                    payload_sha256: request.payload_sha256.as_str(),
                };
                let result = serde_json::to_vec(&query)
                    .map_err(|error| error.to_string())
                    .and_then(|bytes| self.recovery.exchange(&bytes))
                    .and_then(|bytes| {
                        parse_response(
                            &self.identity,
                            bytes,
                            &parsed,
                            request.payload_sha256.as_str(),
                        )
                    });
                match result {
                    Ok((CalculatorResult::Applied { .. }, receipt)) => {
                        ProductionTerminalObservation::Applied { receipt }
                    }
                    Ok((
                        CalculatorResult::Unknown { .. } | CalculatorResult::NotApplied { .. },
                        _,
                    )) => ProductionTerminalObservation::Indeterminate {
                        reason: "Calculator retains no exact causal receipt".into(),
                    },
                    Err(reason) => ProductionTerminalObservation::Unavailable { reason },
                }
            }
        };
        Box::pin(async move { observation })
    }
}

#[cfg(test)]
#[path = "production_calculator_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "production_calculator_golden_tests.rs"]
mod desktop_golden_tests;

#[cfg(test)]
#[path = "production_calculator_retire_golden_tests.rs"]
mod desktop_retire_golden_tests;
