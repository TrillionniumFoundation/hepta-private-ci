use serde::{Deserialize, Serialize};

/// Exact, immutable wire binding. A request carries no authority issued by the UI.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RequestEnvelope {
    pub(crate) protocol_version: String,
    pub(crate) method: String,
    pub(crate) operation_id: String,
    pub(crate) semantic_digest: String,
    pub(crate) action: String,
    pub(crate) target_id: String,
    pub(crate) reason: String,
    pub(crate) session_id: String,
    pub(crate) connection_generation: u64,
    pub(crate) generation: u64,
    pub(crate) displayed_revision: u64,
    pub(crate) snapshot_digest: String,
}

impl RequestEnvelope {
    pub fn operation_id(&self) -> &str {
        &self.operation_id
    }
    pub fn semantic_digest(&self) -> &str {
        &self.semantic_digest
    }
    pub fn method(&self) -> &str {
        &self.method
    }
    pub fn as_value(&self) -> serde_json::Value {
        serde_json::json!({
            "protocolVersion": self.protocol_version, "method": self.method,
            "operationId": self.operation_id, "semanticDigest": self.semantic_digest,
            "action": self.action, "targetId": self.target_id, "reason": self.reason,
            "sessionId": self.session_id, "connectionGeneration": self.connection_generation,
            "generation": self.generation, "displayedRevision": self.displayed_revision,
            "snapshotDigest": self.snapshot_digest,
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum OperationState {
    Submitting,
    Pending,
    Indeterminate,
    Terminal,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OperationView {
    pub operation_id: String,
    pub semantic_digest: String,
    pub method: String,
    pub action: String,
    pub target_id: String,
    pub state: OperationState,
    pub audit_trace_id: Option<String>,
    pub generation: u64,
    pub displayed_revision: u64,
    pub created_at: u64,
    pub updated_at: u64,
    pub terminal_status: Option<String>,
    pub outcome_digest: Option<String>,
    pub authority_granted: bool,
}

/// Opaque in-memory reservation identity. It does not authorize backend admission.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DispatchTicket {
    pub(crate) reservation: u64,
    pub(crate) identity_id: String,
    pub(crate) request: RequestEnvelope,
}

impl DispatchTicket {
    pub fn request(&self) -> &RequestEnvelope {
        &self.request
    }
}

/// Duplicate callers join the existing reservation; only New may dispatch.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SubmitAdmission {
    New(DispatchTicket),
    InFlight(OperationView),
    Existing(OperationView),
}

#[derive(Clone, Debug)]
pub(crate) struct Entry {
    pub identity_id: Option<String>,
    pub reservation: u64,
    pub request: RequestEnvelope,
    pub state: OperationState,
    pub created_at: u64,
    pub updated_at: u64,
    pub audit_trace_id: Option<String>,
    pub terminal_status: Option<String>,
    pub outcome_digest: Option<String>,
}

impl Entry {
    pub fn view(&self) -> OperationView {
        OperationView {
            operation_id: self.request.operation_id.clone(),
            semantic_digest: self.request.semantic_digest.clone(),
            method: self.request.method.clone(),
            action: self.request.action.clone(),
            target_id: self.request.target_id.clone(),
            state: self.state,
            audit_trace_id: self.audit_trace_id.clone(),
            generation: self.request.generation,
            displayed_revision: self.request.displayed_revision,
            created_at: self.created_at,
            updated_at: self.updated_at,
            terminal_status: self.terminal_status.clone(),
            outcome_digest: self.outcome_digest.clone(),
            authority_granted: false,
        }
    }

    pub fn recovery_value(&self) -> serde_json::Value {
        let mut value = self.request.as_value();
        if let Some(object) = value.as_object_mut() {
            object.insert("state".into(), serde_json::json!(self.state));
            object.insert(
                "auditTraceId".into(),
                serde_json::json!(self.audit_trace_id),
            );
            object.insert("createdAt".into(), serde_json::json!(self.created_at));
            object.insert("updatedAt".into(), serde_json::json!(self.updated_at));
        }
        value
    }
}
