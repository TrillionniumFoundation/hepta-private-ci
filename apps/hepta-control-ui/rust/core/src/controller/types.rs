use crate::confirmation::{Confirmation, ConfirmationInput};
use crate::ledger::{DispatchTicket, OperationView, RequestEnvelope};
use crate::projection::{Action, RuntimeSnapshot, Session};
use serde::Serialize;
use serde_json::{Value, json};

#[derive(Clone, Debug)]
pub struct SessionTicket {
    pub(super) epoch: u64,
    pub(super) session: Session,
}
impl SessionTicket {
    pub fn session(&self) -> &Session {
        &self.session
    }
    pub fn request(&self) -> Value {
        json!({"sessionId": self.session.session_id(), "connectionGeneration": self.session.connection_generation()})
    }
}

#[derive(Clone, Debug)]
pub struct ConnectionTicket {
    pub(super) epoch: u64,
}

#[derive(Clone, Debug)]
pub struct LookupTicket {
    pub(super) observer: SessionTicket,
    pub(super) request: RequestEnvelope,
}
impl LookupTicket {
    pub fn request(&self) -> Value {
        json!({"sessionId": self.observer.session.session_id(),
            "connectionGeneration": self.observer.session.connection_generation(),
            "operationId": self.request.operation_id(), "semanticDigest": self.request.semantic_digest()})
    }
}

#[derive(Clone, Debug)]
pub struct SubmissionInput {
    pub operation_id: String,
    pub action: Action,
    pub target_id: String,
    pub reason: String,
    pub displayed_revision: u64,
    pub semantic_digest: Option<String>,
    pub confirmation: Option<Confirmation>,
}

impl SubmissionInput {
    pub(super) fn confirmation_input(&self) -> ConfirmationInput<'_> {
        ConfirmationInput {
            operation_id: &self.operation_id,
            action: self.action.as_str(),
            target_id: &self.target_id,
            reason: &self.reason,
        }
    }
}

#[derive(Clone, Debug)]
pub struct SubmissionTicket {
    pub(super) dispatch: DispatchTicket,
    pub(super) observer: SessionTicket,
    pub(super) snapshot: RuntimeSnapshot,
    pub(super) input: SubmissionInput,
    pub(super) persistence_revision: u64,
}
impl SubmissionTicket {
    pub fn request(&self) -> &RequestEnvelope {
        self.dispatch.request()
    }
}

#[derive(Clone, Debug)]
pub enum SubmissionAdmission {
    New(Box<SubmissionTicket>),
    InFlight(OperationView),
    Existing(OperationView),
}

#[derive(Clone, Debug)]
pub enum LookupAdmission {
    Query(LookupTicket),
    Local(OperationView),
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ControlView {
    pub connected: bool,
    pub authenticated: bool,
    pub session_id: Option<String>,
    pub identity_id: Option<String>,
    pub connection_generation: Option<u64>,
    pub permission_revision: Option<u64>,
    pub permissions: Vec<String>,
    pub expires_at: Option<u64>,
    pub stale: bool,
    pub snapshot: Option<RuntimeSnapshot>,
    pub pending: Vec<OperationView>,
    pub completed: Vec<OperationView>,
    pub pending_count: usize,
    pub completed_count: usize,
    pub indeterminate_count: usize,
    pub pending_max_age_ms: u64,
    pub snapshot_age_ms: Option<u64>,
    pub recovery_metrics: crate::scheduler::RecoveryMetrics,
}
