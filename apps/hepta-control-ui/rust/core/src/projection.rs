//! Owned, validated projections. Public callers can inspect but cannot mutate them.
use crate::canonical::{
    CanonicalLimits, EmptyText, MAX_SAFE_INTEGER, assert_canonical_text, assert_sha256,
    assert_stable_identifier, canonical_json, digest_canonical, parse_canonical_json, safe_integer,
};
use crate::error::{ControlError, ErrorCode};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};

pub const PROTOCOL_VERSION: &str = "hepta.ui-control.v1";
pub const MAX_MODULES: usize = 1000;
pub const PERMISSIONS: [&str; 4] = [
    "hepta://ui.control/runtime.read",
    "hepta://ui.control/runtime.request",
    "hepta://ui.control/runtime.start",
    "hepta://ui.control/runtime.stop",
];

pub fn runtime_canonical_limits() -> CanonicalLimits {
    CanonicalLimits {
        max_entries: 5 * MAX_MODULES + 16,
        ..CanonicalLimits::default()
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeStatus {
    Ready,
    Degraded,
    Quarantined,
    Recovering,
    Unavailable,
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
    pub fn as_str(self) -> &'static str {
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

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ModuleProjection {
    pub(crate) id: String,
    pub(crate) status: RuntimeStatus,
    pub(crate) revision: u64,
    pub(crate) semantic_digest: String,
}

impl ModuleProjection {
    pub fn id(&self) -> &str {
        &self.id
    }
    pub fn status(&self) -> RuntimeStatus {
        self.status
    }
    pub fn revision(&self) -> u64 {
        self.revision
    }
    pub fn semantic_digest(&self) -> &str {
        &self.semantic_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeProjection {
    pub(crate) generation: u64,
    pub(crate) revision: u64,
    pub(crate) modules: Vec<ModuleProjection>,
}

impl RuntimeProjection {
    pub fn generation(&self) -> u64 {
        self.generation
    }
    pub fn revision(&self) -> u64 {
        self.revision
    }
    pub fn modules(&self) -> &[ModuleProjection] {
        &self.modules
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OperationIntent {
    pub(crate) action: Action,
    pub(crate) target_id: String,
    pub(crate) generation: u64,
    pub(crate) displayed_revision: u64,
    pub(crate) reason: String,
}

impl OperationIntent {
    pub fn action(&self) -> Action {
        self.action
    }
    pub fn target_id(&self) -> &str {
        &self.target_id
    }
    pub fn generation(&self) -> u64 {
        self.generation
    }
    pub fn displayed_revision(&self) -> u64 {
        self.displayed_revision
    }
    pub fn reason(&self) -> &str {
        &self.reason
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Session {
    pub(crate) authenticated: bool,
    pub(crate) protocol_version: String,
    pub(crate) session_id: String,
    pub(crate) identity_id: String,
    pub(crate) connection_generation: u64,
    pub(crate) permission_revision: u64,
    pub(crate) expires_at: u64,
    pub(crate) revoked: bool,
    pub(crate) permissions: Vec<String>,
}

impl Session {
    pub fn authenticated(&self) -> bool {
        self.authenticated
    }
    pub fn protocol_version(&self) -> &str {
        &self.protocol_version
    }
    pub fn session_id(&self) -> &str {
        &self.session_id
    }
    pub fn identity_id(&self) -> &str {
        &self.identity_id
    }
    pub fn connection_generation(&self) -> u64 {
        self.connection_generation
    }
    pub fn permission_revision(&self) -> u64 {
        self.permission_revision
    }
    pub fn expires_at(&self) -> u64 {
        self.expires_at
    }
    pub fn revoked(&self) -> bool {
        self.revoked
    }
    pub fn permissions(&self) -> &[String] {
        &self.permissions
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeSnapshot {
    pub(crate) session_id: String,
    pub(crate) connection_generation: u64,
    pub(crate) generation: u64,
    pub(crate) revision: u64,
    pub(crate) semantic_digest: String,
    pub(crate) modules: Vec<ModuleProjection>,
    pub(crate) observed_at: Option<String>,
}

impl RuntimeSnapshot {
    pub fn session_id(&self) -> &str {
        &self.session_id
    }
    pub fn connection_generation(&self) -> u64 {
        self.connection_generation
    }
    pub fn generation(&self) -> u64 {
        self.generation
    }
    pub fn revision(&self) -> u64 {
        self.revision
    }
    pub fn semantic_digest(&self) -> &str {
        &self.semantic_digest
    }
    pub fn modules(&self) -> &[ModuleProjection] {
        &self.modules
    }
    pub fn observed_at(&self) -> Option<&str> {
        self.observed_at.as_deref()
    }
}

fn object(value: &Value) -> Result<&Map<String, Value>, ControlError> {
    let fields = value.as_object().ok_or_else(ControlError::invalid)?;
    if fields
        .keys()
        .any(|key| matches!(key.as_str(), "__proto__" | "constructor" | "prototype"))
    {
        return Err(ControlError::invalid());
    }
    Ok(fields)
}

fn exact_keys(fields: &Map<String, Value>, keys: &[&str]) -> Result<(), ControlError> {
    if fields.len() != keys.len() || keys.iter().any(|key| !fields.contains_key(*key)) {
        return Err(ControlError::invalid());
    }
    Ok(())
}

fn text<'a>(fields: &'a Map<String, Value>, key: &str) -> Result<&'a str, ControlError> {
    fields
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(ControlError::invalid)
}

fn positive_integer(fields: &Map<String, Value>, key: &str) -> Result<u64, ControlError> {
    let value = fields.get(key).ok_or_else(ControlError::invalid)?;
    Ok(safe_integer(value, 1, MAX_SAFE_INTEGER)? as u64)
}

pub fn project_runtime(value: &Value) -> Result<RuntimeProjection, ControlError> {
    let fields = object(value)?;
    exact_keys(fields, &["generation", "revision", "modules"])?;
    let generation = positive_integer(fields, "generation")?;
    let revision = positive_integer(fields, "revision")?;
    let inputs = fields["modules"]
        .as_array()
        .ok_or_else(ControlError::invalid)?;
    if inputs.len() > MAX_MODULES {
        return Err(ControlError::invalid());
    }
    canonical_json(value, &runtime_canonical_limits())?;
    let mut modules = Vec::with_capacity(inputs.len());
    for input in inputs {
        let fields = object(input)?;
        exact_keys(fields, &["id", "status", "revision", "semanticDigest"])?;
        let id = text(fields, "id")?;
        assert_stable_identifier(id)?;
        let status = serde_json::from_value(fields["status"].clone())
            .map_err(|_| ControlError::invalid())?;
        let revision = positive_integer(fields, "revision")?;
        let semantic_digest = text(fields, "semanticDigest")?;
        assert_sha256(semantic_digest)?;
        modules.push(ModuleProjection {
            id: id.to_owned(),
            status,
            revision,
            semantic_digest: semantic_digest.to_owned(),
        });
    }
    modules.sort_by(|left, right| left.id.cmp(&right.id));
    if modules.windows(2).any(|pair| pair[0].id == pair[1].id) {
        return Err(ControlError::invalid());
    }
    Ok(RuntimeProjection {
        generation,
        revision,
        modules,
    })
}

pub fn digest_runtime_projection(runtime: &RuntimeProjection) -> Result<String, ControlError> {
    digest_canonical(
        "hepta.ui-control.runtime-projection.v1",
        &json!(runtime),
        &runtime_canonical_limits(),
    )
}

pub fn build_operation_intent(value: &Value) -> Result<OperationIntent, ControlError> {
    let fields = value.as_object().ok_or_else(ControlError::invalid)?;
    let action = serde_json::from_value(fields.get("action").cloned().unwrap_or(Value::Null))
        .map_err(|_| ControlError::invalid())?;
    let target_id = text(fields, "targetId")?;
    assert_stable_identifier(target_id)?;
    let generation = positive_integer(fields, "generation")?;
    let displayed_revision = positive_integer(fields, "displayedRevision")?;
    let reason = text(fields, "reason")?;
    assert_canonical_text(reason, 1024, EmptyText::Forbidden)?;
    Ok(OperationIntent {
        action,
        target_id: target_id.to_owned(),
        generation,
        displayed_revision,
        reason: reason.to_owned(),
    })
}

pub fn digest_operation_intent(intent: &OperationIntent) -> Result<String, ControlError> {
    digest_canonical(
        "hepta.ui-control.operation-intent.v1",
        &json!(intent),
        &CanonicalLimits {
            max_encoded_bytes: 16 * 1024,
            ..CanonicalLimits::default()
        },
    )
}

pub fn project_runtime_from_local_canonical_json(
    text: &str,
) -> Result<RuntimeProjection, ControlError> {
    project_runtime(&parse_canonical_json(
        text,
        &CanonicalLimits {
            max_depth: 8,
            max_string_bytes: 4096,
            ..runtime_canonical_limits()
        },
    )?)
}

pub fn build_local_operation_proposal_from_canonical_json(
    text: &str,
) -> Result<OperationIntent, ControlError> {
    let value = parse_canonical_json(
        text,
        &CanonicalLimits {
            max_depth: 4,
            max_entries: 16,
            max_array_length: 8,
            max_string_bytes: 4096,
            max_encoded_bytes: 16 * 1024,
        },
    )?;
    exact_keys(
        object(&value)?,
        &[
            "action",
            "targetId",
            "generation",
            "displayedRevision",
            "reason",
        ],
    )?;
    build_operation_intent(&value)
}

pub fn normalize_session(
    value: &Value,
    expected_protocol: &str,
    now: u64,
) -> Result<Session, ControlError> {
    let fields = object(value)?;
    if fields.get("authenticated") != Some(&Value::Bool(true)) {
        return Err(ControlError::new(ErrorCode::PermissionDenied));
    }
    let protocol_version = text(fields, "protocolVersion")?;
    assert_canonical_text(protocol_version, 128, EmptyText::Forbidden)?;
    if protocol_version != expected_protocol {
        return Err(ControlError::new(ErrorCode::ProtocolMismatch));
    }
    let session_id = text(fields, "sessionId")?;
    assert_stable_identifier(session_id)?;
    let identity_id = text(fields, "identityId")?;
    assert_stable_identifier(identity_id)?;
    let connection_generation = positive_integer(fields, "connectionGeneration")?;
    let permission_revision = positive_integer(fields, "permissionRevision")?;
    let expires_at = positive_integer(fields, "expiresAt")?;
    if expires_at <= now {
        return Err(ControlError::new(ErrorCode::SessionExpired).retryable(true));
    }
    if fields.get("revoked") == Some(&Value::Bool(true)) {
        return Err(ControlError::new(ErrorCode::SessionRevoked));
    }
    let inputs = fields
        .get("permissions")
        .and_then(Value::as_array)
        .ok_or_else(ControlError::invalid)?;
    if inputs.is_empty() || inputs.len() > PERMISSIONS.len() {
        return Err(ControlError::invalid());
    }
    let mut permissions = Vec::with_capacity(inputs.len());
    for input in inputs {
        let permission = input.as_str().ok_or_else(ControlError::invalid)?;
        if !PERMISSIONS.contains(&permission) || permissions.iter().any(|known| known == permission)
        {
            return Err(ControlError::invalid());
        }
        permissions.push(permission.to_owned());
    }
    permissions.sort();
    Ok(Session {
        authenticated: true,
        protocol_version: protocol_version.to_owned(),
        session_id: session_id.to_owned(),
        identity_id: identity_id.to_owned(),
        connection_generation,
        permission_revision,
        expires_at,
        revoked: false,
        permissions,
    })
}

pub fn normalize_snapshot(
    value: &Value,
    session: &Session,
) -> Result<RuntimeSnapshot, ControlError> {
    let fields = object(value)?;
    canonical_json(value, &runtime_canonical_limits())?;
    let session_id = text(fields, "sessionId")?;
    assert_stable_identifier(session_id)?;
    if session_id != session.session_id {
        return Err(ControlError::invalid());
    }
    let connection_generation = positive_integer(fields, "connectionGeneration")?;
    if connection_generation != session.connection_generation {
        return Err(ControlError::new(ErrorCode::StaleGeneration).retryable(true));
    }
    let runtime = project_runtime(&json!({
        "generation": fields.get("generation"), "revision": fields.get("revision"), "modules": fields.get("modules"),
    }))?;
    let semantic_digest = digest_canonical(
        "hepta.ui-control.runtime-snapshot.v1",
        &json!({
            "sessionId": session_id, "connectionGeneration": connection_generation,
            "generation": runtime.generation, "revision": runtime.revision, "modules": runtime.modules,
        }),
        &runtime_canonical_limits(),
    )?;
    if let Some(declared) = fields.get("semanticDigest") {
        let declared = declared.as_str().ok_or_else(ControlError::invalid)?;
        assert_sha256(declared)?;
        if declared != semantic_digest {
            return Err(ControlError::new(ErrorCode::SnapshotDrift));
        }
    }
    let snapshot = RuntimeSnapshot {
        session_id: session_id.to_owned(),
        connection_generation,
        generation: runtime.generation,
        revision: runtime.revision,
        semantic_digest,
        modules: runtime.modules,
        observed_at: fields
            .get("observedAt")
            .and_then(Value::as_str)
            .map(str::to_owned),
    };
    canonical_json(&json!(snapshot), &runtime_canonical_limits())?;
    Ok(snapshot)
}

pub fn validate_snapshot_transition(
    previous: Option<&RuntimeSnapshot>,
    next: &RuntimeSnapshot,
) -> Result<RuntimeSnapshot, ControlError> {
    let Some(previous) = previous else {
        return Ok(next.clone());
    };
    if next.session_id != previous.session_id
        || next.connection_generation < previous.connection_generation
    {
        return Err(ControlError::new(ErrorCode::StaleGeneration).retryable(true));
    }
    if next.connection_generation > previous.connection_generation {
        return Ok(next.clone());
    }
    if next.generation < previous.generation {
        return Err(ControlError::new(ErrorCode::StaleGeneration).retryable(true));
    }
    if next.generation > previous.generation {
        return Ok(next.clone());
    }
    if next.revision < previous.revision {
        return Err(ControlError::new(ErrorCode::StaleRevision).retryable(true));
    }
    if next.revision > previous.revision {
        return Ok(next.clone());
    }
    if next.semantic_digest != previous.semantic_digest {
        return Err(ControlError::new(ErrorCode::SnapshotDrift));
    }
    Ok(previous.clone())
}

#[cfg(test)]
#[path = "../tests/unit/projection_tests.rs"]
mod tests;
