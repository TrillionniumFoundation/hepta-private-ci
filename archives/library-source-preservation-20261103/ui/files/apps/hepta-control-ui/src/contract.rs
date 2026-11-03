use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::canonical::{
    CanonicalLimits, assert_canonical_text, assert_safe_integer, assert_sha256,
    assert_sha256_allow_zero, assert_stable_identifier, canonical_json, constant_time_equal,
    digest_canonical_with_limits, parse_canonical_json_with_limits, value_safe_integer,
};
use crate::error::{ControlError, ErrorCode, Result, invalid};

pub const UI_CONTROL_PROTOCOL_VERSION: &str = "hepta.ui-control.v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
pub enum Permission {
    #[serde(rename = "hepta://ui.control/runtime.read")]
    Read,
    #[serde(rename = "hepta://ui.control/runtime.request")]
    Request,
    #[serde(rename = "hepta://ui.control/runtime.start")]
    Start,
    #[serde(rename = "hepta://ui.control/runtime.stop")]
    Stop,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Action {
    RequestStart,
    RequestQuarantine,
    RequestReconcile,
    RequestRetry,
    RequestRollback,
    RequestStop,
}

impl Action {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::RequestStart => "request_start",
            Self::RequestQuarantine => "request_quarantine",
            Self::RequestReconcile => "request_reconcile",
            Self::RequestRetry => "request_retry",
            Self::RequestRollback => "request_rollback",
            Self::RequestStop => "request_stop",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum Method {
    #[serde(rename = "runtime/request")]
    Request,
    #[serde(rename = "runtime/start")]
    Start,
    #[serde(rename = "runtime/stop")]
    Stop,
}

impl Method {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Request => "runtime/request",
            Self::Start => "runtime/start",
            Self::Stop => "runtime/stop",
        }
    }
    pub const fn permission(self) -> Permission {
        match self {
            Self::Request => Permission::Request,
            Self::Start => Permission::Start,
            Self::Stop => Permission::Stop,
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationStatus {
    Accepted,
    Pending,
    Indeterminate,
    Succeeded,
    Failed,
    Rejected,
    Cancelled,
}

impl OperationStatus {
    pub const fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Succeeded | Self::Failed | Self::Rejected | Self::Cancelled
        )
    }
    pub const fn is_active(self) -> bool {
        !self.is_terminal()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Session {
    pub protocol_version: String,
    pub authenticated: bool,
    pub session_id: String,
    pub identity_id: String,
    pub connection_generation: u64,
    pub permission_revision: u64,
    pub expires_at: u64,
    pub revoked: bool,
    pub permissions: Vec<Permission>,
}

pub fn normalize_session(value: &Value, expected_protocol: &str, now: u64) -> Result<Session> {
    let object = value.as_object().ok_or_else(invalid)?;
    // Validate the complete bounded envelope, including ignored extension fields.
    canonical_json(value)?;
    if object.get("authenticated") != Some(&Value::Bool(true)) {
        return Err(ControlError::new(ErrorCode::PermissionDenied));
    }
    let text = |key| object.get(key).and_then(Value::as_str).ok_or_else(invalid);
    let integer = |key| value_safe_integer(object.get(key), /*min*/ 1);
    let protocol_version =
        assert_canonical_text(text("protocolVersion")?, /*max_bytes*/ 128)?.to_owned();
    if protocol_version != expected_protocol {
        return Err(ControlError::new(ErrorCode::ProtocolMismatch));
    }
    let session_id = assert_stable_identifier(text("sessionId")?)?.to_owned();
    let identity_id = assert_stable_identifier(text("identityId")?)?.to_owned();
    let connection_generation =
        assert_safe_integer(integer("connectionGeneration")?, /*min*/ 1)?;
    let permission_revision = assert_safe_integer(integer("permissionRevision")?, /*min*/ 1)?;
    let expires_at = assert_safe_integer(integer("expiresAt")?, /*min*/ 1)?;
    if expires_at <= now {
        return Err(ControlError::new(ErrorCode::SessionExpired));
    }
    if object.get("revoked") == Some(&Value::Bool(true)) {
        return Err(ControlError::new(ErrorCode::SessionRevoked));
    }
    let mut permissions: Vec<Permission> =
        serde_json::from_value(object.get("permissions").ok_or_else(invalid)?.clone())
            .map_err(|_| invalid())?;
    if permissions.is_empty() || permissions.len() > 4 {
        return Err(invalid());
    }
    permissions.sort();
    if permissions.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(invalid());
    }
    Ok(Session {
        protocol_version,
        authenticated: true,
        session_id,
        identity_id,
        connection_generation,
        permission_revision,
        expires_at,
        revoked: false,
        permissions,
    })
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OperationIntent {
    pub action: Action,
    pub target_id: String,
    pub generation: u64,
    pub displayed_revision: u64,
    pub reason: String,
}

impl OperationIntent {
    pub fn validate(&self) -> Result<()> {
        assert_stable_identifier(&self.target_id)?;
        assert_safe_integer(self.generation, /*min*/ 1)?;
        assert_safe_integer(self.displayed_revision, /*min*/ 1)?;
        assert_canonical_text(&self.reason, /*max_bytes*/ 1024)?;
        Ok(())
    }
}

pub fn build_operation_intent(value: &Value) -> Result<OperationIntent> {
    let encoded = canonical_json(value)?;
    let intent: OperationIntent = serde_json::from_str(&encoded).map_err(|_| invalid())?;
    intent.validate()?;
    Ok(intent)
}

pub fn digest_operation_intent(intent: &OperationIntent) -> Result<String> {
    intent.validate()?;
    digest_canonical_with_limits(
        "hepta.ui-control.operation-intent.v1",
        &serde_json::to_value(intent).map_err(|_| invalid())?,
        CanonicalLimits {
            max_encoded_bytes: 16 * 1024,
            ..CanonicalLimits::default()
        },
    )
}

pub fn build_local_operation_proposal_from_canonical_json(text: &str) -> Result<OperationIntent> {
    build_operation_intent(&parse_canonical_json_with_limits(
        text,
        CanonicalLimits {
            max_depth: 4,
            max_entries: 16,
            max_array_length: 8,
            max_string_bytes: 4096,
            max_encoded_bytes: 16 * 1024,
        },
    )?)
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OperationRequest {
    pub protocol_version: String,
    pub method: Method,
    pub operation_id: String,
    pub semantic_digest: String,
    pub action: Action,
    pub target_id: String,
    pub reason: String,
    pub session_id: String,
    pub connection_generation: u64,
    pub generation: u64,
    pub displayed_revision: u64,
    pub snapshot_digest: String,
}

impl OperationRequest {
    pub fn intent(&self) -> OperationIntent {
        OperationIntent {
            action: self.action,
            target_id: self.target_id.clone(),
            generation: self.generation,
            displayed_revision: self.displayed_revision,
            reason: self.reason.clone(),
        }
    }
    pub fn validate(&self) -> Result<()> {
        if self.protocol_version != UI_CONTROL_PROTOCOL_VERSION {
            return Err(ControlError::new(ErrorCode::ProtocolMismatch));
        }
        assert_stable_identifier(&self.operation_id)?;
        assert_stable_identifier(&self.session_id)?;
        assert_safe_integer(self.connection_generation, /*min*/ 1)?;
        assert_sha256(&self.snapshot_digest)?;
        assert_sha256(&self.semantic_digest)?;
        if matches!(self.method, Method::Start) && self.action != Action::RequestStart
            || matches!(self.method, Method::Stop) && self.action != Action::RequestStop
        {
            return Err(invalid());
        }
        if !constant_time_equal(
            &digest_operation_intent(&self.intent())?,
            &self.semantic_digest,
        ) {
            return Err(ControlError::new(ErrorCode::OperationConflict));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Acknowledgement {
    pub status: OperationStatus,
    pub audit_trace_id: String,
}

pub fn validate_acknowledgement(
    request: &OperationRequest,
    value: &Value,
) -> Result<Acknowledgement> {
    let object = value.as_object().ok_or_else(invalid)?;
    canonical_json(value)?;
    match object.get("accepted").and_then(Value::as_bool) {
        Some(false) => return Err(ControlError::new(ErrorCode::BackendRejected)),
        Some(true) => {}
        None => return Err(invalid()),
    }
    let text = |key| object.get(key).and_then(Value::as_str).ok_or_else(invalid);
    let operation_id = assert_stable_identifier(text("operationId")?)?;
    let semantic_digest = assert_sha256(text("semanticDigest")?)?;
    let status_text = assert_canonical_text(text("status")?, /*max_bytes*/ 32)?;
    let audit_trace_id = assert_stable_identifier(text("auditTraceId")?)?.to_owned();
    let status = serde_json::from_value::<OperationStatus>(Value::String(status_text.to_owned()))
        .map_err(|_| ControlError::new(ErrorCode::AckMismatch))?;
    if operation_id != request.operation_id
        || !constant_time_equal(semantic_digest, &request.semantic_digest)
        || !status.is_active()
    {
        return Err(ControlError::new(ErrorCode::AckMismatch));
    }
    Ok(Acknowledgement {
        status,
        audit_trace_id,
    })
}

pub fn validate_audit_trace<'a>(previous: Option<&str>, value: Option<&'a str>) -> Result<&'a str> {
    let value = value.ok_or_else(|| ControlError::new(ErrorCode::AckMismatch))?;
    if previous.is_some_and(|previous| previous != value) {
        return Err(ControlError::new(ErrorCode::AckMismatch));
    }
    assert_stable_identifier(value)
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Observation {
    pub operation_id: String,
    pub semantic_digest: String,
    pub status: OperationStatus,
    pub terminal_observed: bool,
    pub audit_trace_id: Option<String>,
    pub outcome_digest: Option<String>,
}

impl Observation {
    pub fn validate(&self) -> Result<()> {
        assert_stable_identifier(&self.operation_id)?;
        assert_sha256(&self.semantic_digest)?;
        if !self.terminal_observed || !self.status.is_terminal() {
            return Err(invalid());
        }
        if let Some(value) = &self.audit_trace_id {
            assert_stable_identifier(value)?;
        }
        if let Some(value) = &self.outcome_digest {
            assert_sha256_allow_zero(value)?;
        }
        Ok(())
    }
}

pub fn normalize_observation(value: &Value) -> Result<Observation> {
    let encoded = canonical_json(value)?;
    let observation: Observation = serde_json::from_str(&encoded).map_err(|_| invalid())?;
    observation.validate()?;
    Ok(observation)
}

#[path = "confirmation.rs"]
mod confirmation;
pub use confirmation::{
    ConfirmationContext, ConfirmationInput, assert_confirmation, capture_confirmation,
    retained_target,
};

#[cfg(test)]
#[path = "contract_tests.rs"]
mod tests;
