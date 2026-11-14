//! Exact Android text effects through the existing production owner/FinalUse.
//!
//! No startup registration, issuer, operation database, reconnect or replay.
//! A native apply acknowledgement and a separate later observation are needed
//! for immediate completion. Readback by itself never proves causal completion.

use std::sync::Arc;

use base64::Engine;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Serialize;

use crate::FinalUseProductionOutboxTarget;
use crate::ProductionDispatchFuture;
use crate::ProductionDispatchRequest;
use crate::ProductionOutboxTarget;
use crate::ProductionTargetOutcome;
use crate::ProductionTerminalObservation;
use crate::ProductionTerminalObservationFuture;
use crate::production_android_wire::AndroidNativeTextObservation;
use crate::production_android_wire::AndroidSetTextV1;

#[path = "production_android_response.rs"]
mod response;

pub const ANDROID_SET_TEXT_TOPIC_V1: &str = "hepta.android.set-text.v1";

/// The original host's explicitly retained, qualified fixed-helper capability.
/// Implementations must verify the original host/peer/tool pins, accept only
/// the specified helper operation, perform bounded synchronous exchanges and
/// return the actual original receiver bytes. They cannot schedule, reconnect,
/// retarget a new cell, or repeat an ambiguous effect. `readback` must make a
/// separate read-only receiver invocation. `invalidate` permanently closes the
/// effect lane after ambiguity; the retained read-only lane may still observe.
pub trait OriginalAndroidTextDevice: Send + Sync {
    fn apply(&self, helper_request: &[u8]) -> Result<Vec<u8>, String>;
    fn readback(&self, helper_request: &[u8]) -> Result<Vec<u8>, String>;
    fn invalidate(&self);
}

fn scope(observation: &AndroidNativeTextObservation) -> Result<Digest32, String> {
    #[derive(Serialize)]
    struct Scope<'a> {
        application: &'a crate::AndroidApplicationGeneration,
        generation: &'a crate::AndroidCellGeneration,
        package: &'a str,
        resource_id: &'a str,
    }
    let raw = serde_json::to_vec(&Scope {
        application: &observation.application,
        generation: &observation.generation,
        package: &observation.window.package,
        resource_id: &observation.target.resource_id,
    })
    .map_err(|e| e.to_string())?;
    Ok(Digest32::of_bytes(&raw))
}

/// Construct the authority-free intent persisted by the original writer.
/// Native accessibility exposes a checked predecessor, not an atomic CAS;
/// therefore no destination-transaction predecessor capability is claimed.
pub fn android_text_operation_intent(
    payload: &str,
    subject: StableId,
    policy_generation: Generation,
) -> Result<OperationIntentV1, String> {
    let parsed = AndroidSetTextV1::from_json(payload)?;
    OperationIntentV1::new(
        StableId::new(&parsed.operation_id).map_err(|e| e.to_string())?,
        subject,
        StableId::new(&parsed.destination_id).map_err(|e| e.to_string())?,
        Digest32::of_bytes(payload.as_bytes()),
        scope(&parsed.observation)?,
        policy_generation,
        /*expected_predecessor*/ None,
    )
    .map_err(|e| e.to_string())
}

fn helper_request(op: &str, request: &ProductionDispatchRequest) -> Result<Vec<u8>, String> {
    #[derive(Serialize)]
    struct Helper<'a> {
        op: &'a str,
        payload_base64: String,
        payload_sha256: &'a str,
    }
    serde_json::to_vec(&Helper {
        op,
        payload_base64: base64::engine::general_purpose::STANDARD
            .encode(request.payload_json.as_bytes()),
        payload_sha256: request.payload_sha256.as_str(),
    })
    .map_err(|e| e.to_string())
}

/// Explicit destination attached to the existing FinalUse dispatcher. The
/// initial observation fixes the original cell, application and exact editor.
pub struct ProductionAndroidTextTarget {
    destination: String,
    scope: Digest32,
    device: Arc<dyn OriginalAndroidTextDevice>,
}

impl ProductionAndroidTextTarget {
    pub fn new(
        observation: &AndroidNativeTextObservation,
        device: Arc<dyn OriginalAndroidTextDevice>,
    ) -> Result<Self, String> {
        observation.validate()?;
        Ok(Self {
            destination: observation.destination_id()?,
            scope: scope(observation)?,
            device,
        })
    }

    fn decode(&self, request: &ProductionDispatchRequest) -> Result<AndroidSetTextV1, String> {
        let parsed = AndroidSetTextV1::from_json(&request.payload_json)?;
        let intent = android_text_operation_intent(
            &request.payload_json,
            StableId::new(&request.operation_subject_id).map_err(|e| e.to_string())?,
            Generation::new(request.operation_policy_generation).map_err(|e| e.to_string())?,
        )?;
        if request.schema_version != crate::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION
            || request.namespace != crate::PRODUCTION_DURABLE_WRITER_NAMESPACE
            || request.topic != ANDROID_SET_TEXT_TOPIC_V1
            || parsed.destination_id != self.destination
            || scope(&parsed.observation)? != self.scope
            || request.operation_destination_id != self.destination
            || request.occurrence_key != parsed.operation_id
            || request.idempotency_key != parsed.operation_id
            || request.payload_sha256 != Sha256Digest::for_bytes(request.payload_json.as_bytes())
            || request.operation_scope_sha256.as_str() != intent.scope_digest().to_string()
            || request.operation_semantic_sha256.as_str() != intent.semantic_digest().to_string()
            || request.expected_predecessor_sha256.is_some()
        {
            return Err(
                "Android text request differs from its original durable operation".to_string(),
            );
        }
        Ok(parsed)
    }
}

impl ProductionOutboxTarget for ProductionAndroidTextTarget {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        // The actual bounded effect and independent read finish within the
        // original synchronous FinalUse consumer entry, before returning any
        // future. Cancelling/dropping an unpolled future cannot defer entry.
        let outcome = match self.decode(&request) {
            Err(reason) => ProductionTargetOutcome::Rejected { reason },
            Ok(parsed) => {
                let exchange = || {
                    let apply = self
                        .device
                        .apply(&helper_request("organ-set-text", &request)?)?;
                    let acknowledgement =
                        response::apply(&parsed, &request.payload_sha256, &apply)?;
                    let readback = self
                        .device
                        .readback(&helper_request("organ-readback", &request)?)?;
                    response::committed(
                        &parsed,
                        &request.payload_sha256,
                        &acknowledgement,
                        &apply,
                        &readback,
                    )
                };
                match exchange() {
                    Ok(receipt) => ProductionTargetOutcome::Committed { receipt },
                    Err(reason) => {
                        self.device.invalidate();
                        ProductionTargetOutcome::Indeterminate { reason }
                    }
                }
            }
        };
        Box::pin(async move { outcome })
    }
}

impl FinalUseProductionOutboxTarget for ProductionAndroidTextTarget {
    fn destination_id(&self) -> &str {
        &self.destination
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        let observe = || {
            let parsed = self.decode(request)?;
            let bytes = self
                .device
                .readback(&helper_request("organ-readback", request)?)?;
            response::readback(&parsed, &request.payload_sha256, &bytes)?;
            Ok::<_, String>(())
        };
        let observation = match observe() {
            Ok(()) => ProductionTerminalObservation::Indeterminate {
                reason: "Android state observation has no retained causal receipt; original operation must not replay".to_string(),
            },
            Err(reason) => ProductionTerminalObservation::Unavailable { reason },
        };
        Box::pin(async move { observation })
    }
}

#[cfg(test)]
#[path = "production_android_tests.rs"]
mod tests;
