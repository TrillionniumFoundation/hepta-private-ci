//! Typed X11 input through the original FinalUse operation owner. A terminal
//! receipt proves only that the selected X server accepted the input batch;
//! it never proves completion of a third-party application workflow.

use std::sync::Arc;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::FinalUseProductionOutboxTarget;
use crate::ProductionDispatchFuture;
use crate::ProductionDispatchRequest;
use crate::ProductionOutboxTarget;
use crate::ProductionTargetOutcome;
use crate::ProductionTerminalObservation;
use crate::ProductionTerminalObservationFuture;

#[path = "production_desktop_wire.rs"]
pub(crate) mod wire;
use wire::DesktopInput;
use wire::DesktopReceipt;
use wire::DesktopTargetIdentity;
use wire::InputResult;

pub const DESKTOP_INPUT_TOPIC_V1: &str = "trill.desktop.input.v1";

/// Observation capability for the separately inherited private stream. This
/// endpoint accepts exact receipt queries and captures, never input events.
pub trait DesktopObservationChannel: Send + Sync {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String>;
}

/// An explicitly inherited effect endpoint. The exchange occurs synchronously
/// inside the original FinalUse consumer entry. Implementations never queue,
/// reconnect, or retry an ambiguous input and permanently invalidate that lane.
pub trait DesktopPrivateChannel: Send + Sync {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String>;
    fn invalidate(&self);
}

pub fn desktop_operation_intent(
    target: &DesktopTargetIdentity,
    payload: &str,
    subject: StableId,
    policy_generation: Generation,
) -> Result<OperationIntentV1, String> {
    let parsed = DesktopInput::parse_exact(payload.as_bytes())?;
    if parsed.target != *target {
        return Err("desktop target identity mismatch".into());
    }
    OperationIntentV1::new(
        StableId::new(parsed.operation_id).map_err(|error| error.to_string())?,
        subject,
        StableId::new(target.destination_id()).map_err(|error| error.to_string())?,
        Digest32::of_bytes(payload.as_bytes()),
        Digest32::of_bytes(
            format!(
                "trill.desktop.scope.v1\0{}\0{}\0{}",
                target.session_instance, target.incarnation, target.display_epoch
            )
            .as_bytes(),
        ),
        policy_generation,
        Some(Digest32::of_bytes(
            format!(
                "trill.desktop.predecessor.v1\0{}\0{}\0{}\0{}",
                target.session_instance,
                target.incarnation,
                target.display_epoch,
                parsed.expected_sequence
            )
            .as_bytes(),
        )),
    )
    .map_err(|error| error.to_string())
}

/// Fixed trusted display scope, independent of the requested window. XTEST is
/// a server-wide capability; expected_window is only a checked precondition.
pub struct ProductionDesktopTarget {
    identity: DesktopTargetIdentity,
    destination: String,
    effect: Arc<dyn DesktopPrivateChannel>,
    observation: Arc<dyn DesktopObservationChannel>,
}

impl ProductionDesktopTarget {
    pub fn new(
        identity: DesktopTargetIdentity,
        effect: Arc<dyn DesktopPrivateChannel>,
        observation: Arc<dyn DesktopObservationChannel>,
    ) -> Result<Self, String> {
        identity.validate()?;
        Ok(Self {
            destination: identity.destination_id(),
            identity,
            effect,
            observation,
        })
    }

    fn decode(&self, request: &ProductionDispatchRequest) -> Result<DesktopInput, String> {
        let parsed = DesktopInput::parse_exact(request.payload_json.as_bytes())?;
        let intent = desktop_operation_intent(
            &self.identity,
            &request.payload_json,
            StableId::new(&request.operation_subject_id).map_err(|e| e.to_string())?,
            Generation::new(request.operation_policy_generation).map_err(|e| e.to_string())?,
        )?;
        if request.schema_version != crate::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION
            || request.namespace != crate::PRODUCTION_DURABLE_WRITER_NAMESPACE
            || request.topic != DESKTOP_INPUT_TOPIC_V1
            || request.operation_destination_id != self.destination
            || request.occurrence_key != parsed.operation_id
            || request.idempotency_key != parsed.operation_id
            || request.payload_sha256 != Sha256Digest::for_bytes(request.payload_json.as_bytes())
            || request.operation_scope_sha256.as_str() != intent.scope_digest().to_string()
            || request.operation_semantic_sha256.as_str() != intent.semantic_digest().to_string()
            || request
                .expected_predecessor_sha256
                .as_ref()
                .map(|value| value.as_str().to_owned())
                != intent.expected_predecessor().map(|value| value.to_string())
        {
            return Err("desktop request differs from the original durable operation".into());
        }
        Ok(parsed)
    }

    /// Reads pixels without any effect endpoint or grant. Correlated pixels
    /// remain observations and cannot be converted to terminal operation proof.
    pub fn observation_channel(&self) -> Arc<dyn DesktopObservationChannel> {
        Arc::clone(&self.observation)
    }
}

fn response(
    payload: &DesktopInput,
    raw_payload: &str,
    bytes: Vec<u8>,
) -> Result<(InputResult, String), String> {
    let reply = DesktopReceipt::parse_exact(&bytes)?;
    if reply.target != payload.target
        || reply.operation_id != payload.operation_id
        || reply.payload_sha256 != Sha256Digest::for_bytes(raw_payload.as_bytes()).as_str()
    {
        return Err("desktop response identity mismatch".into());
    }
    if let InputResult::Injected {
        previous_sequence, ..
    } = reply.result
        && previous_sequence != payload.expected_sequence
    {
        return Err("desktop response sequence mismatch".into());
    }
    Ok((
        reply.result,
        String::from_utf8(bytes).map_err(|_| "desktop response UTF-8")?,
    ))
}

impl ProductionOutboxTarget for ProductionDesktopTarget {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        // Execute now, before constructing the future, inside enter_exact.
        let outcome = match self.decode(&request) {
            Err(reason) => ProductionTargetOutcome::Rejected { reason },
            Ok(payload) => match self
                .effect
                .exchange(request.payload_json.as_bytes())
                .and_then(|bytes| response(&payload, &request.payload_json, bytes))
            {
                Ok((InputResult::Injected { .. }, receipt)) => {
                    ProductionTargetOutcome::Committed { receipt }
                }
                Ok((InputResult::NotInjected { .. }, reason)) => {
                    ProductionTargetOutcome::NotApplied { reason }
                }
                Ok((InputResult::Unknown { .. }, _)) => {
                    self.effect.invalidate();
                    ProductionTargetOutcome::Indeterminate {
                        reason: "desktop input outcome unknown".into(),
                    }
                }
                Err(reason) => {
                    self.effect.invalidate();
                    ProductionTargetOutcome::Indeterminate { reason }
                }
            },
        };
        Box::pin(async move { outcome })
    }
}

impl FinalUseProductionOutboxTarget for ProductionDesktopTarget {
    fn destination_id(&self) -> &str {
        &self.destination
    }
    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        let observed = (|| {
            let payload = self.decode(request)?;
            let query = serde_json::to_vec(&serde_json::json!({"schema_version":1,"action":"observe",
                "target":self.identity,"operation_id":payload.operation_id,"payload_sha256":request.payload_sha256.as_str()}))
                .map_err(|e| e.to_string())?;
            let bytes = self.observation.exchange(&query)?;
            response(&payload, &request.payload_json, bytes)
        })();
        let outcome = match observed {
            Ok((InputResult::Injected { .. }, receipt)) => {
                ProductionTerminalObservation::Applied { receipt }
            }
            Ok((InputResult::NotInjected { .. }, reason)) => {
                ProductionTerminalObservation::NotApplied { reason }
            }
            Ok((InputResult::Unknown { .. }, _)) => ProductionTerminalObservation::Indeterminate {
                reason: "desktop history is unknown; input must not be replayed".into(),
            },
            Err(reason) => ProductionTerminalObservation::Unavailable { reason },
        };
        Box::pin(async move { outcome })
    }
}

pub(crate) struct DesktopTerminalReceipt {
    raw: String,
    outcome: crate::LocalReconcileOutcome,
}
impl DesktopTerminalReceipt {
    pub(crate) fn from_json(payload: &str, evidence: &str) -> Result<Self, String> {
        let parsed = DesktopInput::parse_exact(payload.as_bytes())?;
        let (result, raw) = response(&parsed, payload, evidence.as_bytes().to_vec())?;
        let outcome = match result {
            InputResult::Injected { .. } => crate::LocalReconcileOutcome::Committed,
            InputResult::NotInjected { .. } => crate::LocalReconcileOutcome::Rejected,
            InputResult::Unknown { .. } => {
                return Err("unknown desktop input is not terminal".into());
            }
        };
        Ok(Self { raw, outcome })
    }
    pub(crate) fn outcome(&self) -> crate::LocalReconcileOutcome {
        self.outcome
    }
    pub(crate) fn as_str(&self) -> &str {
        &self.raw
    }
    pub(crate) fn matches(&self, payload: &str) -> Result<(), String> {
        let checked = Self::from_json(payload, &self.raw)?;
        if checked.outcome != self.outcome {
            return Err("desktop terminal mismatch".into());
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "production_desktop_tests.rs"]
mod tests;
