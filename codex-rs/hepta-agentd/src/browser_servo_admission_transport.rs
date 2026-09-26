use std::time::Duration;

use serde_json::Value;

use crate::browser_servo_admission_frame::{
    decode, digest, encode, exact, object_mut, positive, protocol, stable_id, text,
};
use crate::browser_servo_product::{BrowserServoError, BrowserServoTransport};

const RECEIPT_VERSION: u64 = 1;

#[derive(Clone, Debug)]
struct ActiveEffect {
    request_id: String,
    operation_id: String,
    generation: u64,
}

pub struct AdmissionValidatingTransport<T: BrowserServoTransport> {
    inner: T,
    active: Option<ActiveEffect>,
    admission: Option<Value>,
    rejected: bool,
}

impl<T: BrowserServoTransport> AdmissionValidatingTransport<T> {
    pub fn new(inner: T) -> Self {
        Self {
            inner,
            active: None,
            admission: None,
            rejected: false,
        }
    }

    fn outgoing(&mut self, bytes: &[u8]) -> Result<Vec<u8>, BrowserServoError> {
        let mut frame = decode(bytes)?;
        let object = object_mut(&mut frame, "Agentd Browser output frame")?;
        let kind = text(object, "kind", "Agentd Browser output frame")?.to_owned();
        let request_id =
            text(object, "requestId", "Agentd Browser output frame")?.to_owned();

        if kind == "request" {
            let payload = object
                .get("payload")
                .and_then(Value::as_object)
                .ok_or_else(|| protocol("Browser request payload must be an object"))?;
            if payload.get("method").and_then(Value::as_str) == Some("navigate_or_act") {
                if self.active.is_some() {
                    return Err(protocol(
                        "Browser transport already has an active effect",
                    ));
                }
                let input = payload
                    .get("input")
                    .and_then(Value::as_object)
                    .ok_or_else(|| protocol("Browser effect input must be an object"))?;
                let operation_id = input
                    .get("operationId")
                    .and_then(Value::as_str)
                    .ok_or_else(|| protocol("Browser effect operationId is missing"))?;
                stable_id(operation_id, "Browser effect operationId")?;
                let generation = positive(
                    input.get("generation"),
                    "Browser effect generation",
                )?;
                self.active = Some(ActiveEffect {
                    request_id,
                    operation_id: operation_id.to_owned(),
                    generation,
                });
                self.admission = None;
                self.rejected = false;
            }
            return Ok(bytes.to_vec());
        }

        if kind == "authority_enter" {
            let active = self.active.as_ref().ok_or_else(|| {
                protocol("authority entered without an active Browser effect")
            })?;
            if active.request_id != request_id {
                return Err(protocol(
                    "authority entry crossed Browser request identity",
                ));
            }
            let payload = object
                .get_mut("payload")
                .and_then(Value::as_object_mut)
                .ok_or_else(|| protocol("authority-enter payload must be an object"))?;
            exact(
                payload,
                &[
                    "authorized",
                    "authorityEpoch",
                    "requestDigest",
                    "witnessDigest",
                ],
                "authority-enter payload",
            )?;
            payload.insert(
                "admissionReceiptVersion".to_owned(),
                Value::from(RECEIPT_VERSION),
            );
            return encode(frame);
        }

        Ok(bytes.to_vec())
    }

    fn incoming(&mut self, bytes: &[u8]) -> Result<Vec<u8>, BrowserServoError> {
        let mut frame = decode(bytes)?;
        let object = object_mut(&mut frame, "Browser Agentd input frame")?;
        let kind = text(object, "kind", "Browser Agentd input frame")?.to_owned();
        let request_id =
            text(object, "requestId", "Browser Agentd input frame")?.to_owned();

        match kind.as_str() {
            "dispatch_boundary" => {
                let active = self.active.as_ref().ok_or_else(|| {
                    protocol("effect admission arrived without an active effect")
                })?;
                if active.request_id != request_id {
                    return Err(protocol(
                        "effect admission crossed Browser request identity",
                    ));
                }
                let payload = object
                    .get_mut("payload")
                    .and_then(Value::as_object_mut)
                    .ok_or_else(|| {
                        protocol("dispatch-boundary payload must be an object")
                    })?;
                exact(
                    payload,
                    &[
                        "admission",
                        "localDispatchCrossed",
                        "requestDigest",
                        "witnessDigest",
                    ],
                    "dispatch-boundary payload",
                )?;
                if payload.get("localDispatchCrossed") != Some(&Value::Bool(true)) {
                    return Err(protocol(
                        "dispatch boundary did not claim admission",
                    ));
                }
                let admission = payload
                    .remove("admission")
                    .ok_or_else(|| {
                        protocol("dispatch boundary lacks effect admission")
                    })?;
                validate_admission(&admission, active)?;
                self.admission = Some(admission);
                self.rejected = false;
                encode(frame)
            }
            "dispatch_rejected" => {
                let active = self.active.as_ref().ok_or_else(|| {
                    protocol("dispatch rejection arrived without an active effect")
                })?;
                if active.request_id != request_id {
                    return Err(protocol(
                        "dispatch rejection crossed Browser request identity",
                    ));
                }
                let payload = object
                    .get("payload")
                    .and_then(Value::as_object)
                    .ok_or_else(|| {
                        protocol("dispatch-rejected payload must be an object")
                    })?;
                exact(
                    payload,
                    &[
                        "localDispatchCrossed",
                        "requestDigest",
                        "witnessDigest",
                    ],
                    "dispatch-rejected payload",
                )?;
                if payload.get("localDispatchCrossed") != Some(&Value::Bool(false)) {
                    return Err(protocol(
                        "dispatch rejection claimed a crossed effect",
                    ));
                }
                self.admission = None;
                self.rejected = true;
                Ok(bytes.to_vec())
            }
            "response" if self.active.is_some() => {
                let active = self.active.as_ref().expect("checked above");
                if active.request_id != request_id {
                    return Err(protocol(
                        "effect response crossed Browser request identity",
                    ));
                }
                let payload = object
                    .get_mut("payload")
                    .and_then(Value::as_object_mut)
                    .ok_or_else(|| {
                        protocol("Browser response payload must be an object")
                    })?;
                if let Some(admission) = self.admission.take() {
                    if payload.get("ok") != Some(&Value::Bool(true)) {
                        return Err(BrowserServoError::Indeterminate(
                            "Browser failed after effect admission without a terminal result"
                                .into(),
                        ));
                    }
                    let result = payload
                        .get_mut("result")
                        .and_then(Value::as_object_mut)
                        .ok_or_else(|| {
                            protocol("Browser success result must be an object")
                        })?;
                    if result
                        .insert("effectAdmission".to_owned(), admission)
                        .is_some()
                    {
                        return Err(protocol(
                            "Browser result supplied its own effect admission",
                        ));
                    }
                } else if !self.rejected {
                    return Err(BrowserServoError::Indeterminate(
                        "effect response arrived without admission or rejection".into(),
                    ));
                }
                self.active = None;
                self.rejected = false;
                encode(frame)
            }
            _ => Ok(bytes.to_vec()),
        }
    }
}

impl<T: BrowserServoTransport> BrowserServoTransport for AdmissionValidatingTransport<T> {
    fn write_frame_timeout(
        &mut self,
        bytes: &[u8],
        timeout: Duration,
    ) -> Result<(), BrowserServoError> {
        let rewritten = self.outgoing(bytes)?;
        self.inner.write_frame_timeout(&rewritten, timeout)
    }

    fn read_frame_timeout(
        &mut self,
        timeout: Duration,
    ) -> Result<Vec<u8>, BrowserServoError> {
        let bytes = self.inner.read_frame_timeout(timeout)?;
        self.incoming(&bytes)
    }
}

fn validate_admission(
    value: &Value,
    active: &ActiveEffect,
) -> Result<(), BrowserServoError> {
    let object = value
        .as_object()
        .ok_or_else(|| protocol("BrowserEffectAdmissionV1 must be an object"))?;
    exact(
        object,
        &[
            "admittedAt",
            "durableOrRecoverable",
            "kind",
            "operationId",
            "pageRevision",
            "semanticDigest",
            "workerGeneration",
        ],
        "BrowserEffectAdmissionV1",
    )?;
    if object.get("kind").and_then(Value::as_str)
        != Some("BrowserEffectAdmissionV1")
    {
        return Err(protocol("effect admission kind is unsupported"));
    }
    if object.get("operationId").and_then(Value::as_str)
        != Some(active.operation_id.as_str())
    {
        return Err(BrowserServoError::BindingMismatch(
            "effect admission operationId drifted".into(),
        ));
    }
    if positive(
        object.get("workerGeneration"),
        "admission workerGeneration",
    )? != active.generation
    {
        return Err(BrowserServoError::BindingMismatch(
            "effect admission workerGeneration drifted".into(),
        ));
    }
    digest(
        object.get("semanticDigest"),
        "admission semanticDigest",
    )?;
    digest(object.get("pageRevision"), "admission pageRevision")?;
    positive(object.get("admittedAt"), "admission admittedAt")?;
    if object.get("durableOrRecoverable") != Some(&Value::Bool(true)) {
        return Err(BrowserServoError::BindingMismatch(
            "effect admission is not durable or recoverable".into(),
        ));
    }
    Ok(())
}
