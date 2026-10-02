mod model;

pub(crate) use model::Entry;
pub use model::{DispatchTicket, OperationState, OperationView, RequestEnvelope, SubmitAdmission};

use crate::error::{ControlError, ErrorCode};
use serde_json::Value;
use std::collections::{BTreeMap, VecDeque};

const MAX_COMPLETED: usize = 1024;

/// Bounded, authority-free local operation reservations. The backend durable ledger remains final.
#[derive(Debug)]
pub struct OperationLedger {
    pub(crate) pending: BTreeMap<String, Entry>,
    pub(crate) completed: BTreeMap<String, Entry>,
    completed_order: VecDeque<String>,
    pub(crate) max_pending: usize,
    pub(crate) identity_id: Option<String>,
    next_reservation: u64,
}

impl OperationLedger {
    pub fn new(max_pending: usize) -> Result<Self, ControlError> {
        if !(1..=4096).contains(&max_pending) {
            return Err(ControlError::invalid());
        }
        Ok(Self {
            pending: BTreeMap::new(),
            completed: BTreeMap::new(),
            completed_order: VecDeque::new(),
            max_pending,
            identity_id: None,
            next_reservation: 0,
        })
    }

    pub(crate) fn set_identity(&mut self, identity_id: &str) {
        if self.identity_id.is_none() {
            for entry in self.pending.values_mut().chain(self.completed.values_mut()) {
                entry.identity_id = Some(identity_id.to_owned());
            }
        }
        self.identity_id = Some(identity_id.to_owned());
    }

    pub fn pending_views(&self) -> Vec<OperationView> {
        self.pending
            .values()
            .filter(|entry| entry.identity_id == self.identity_id)
            .map(Entry::view)
            .collect()
    }

    pub fn completed_views(&self) -> Vec<OperationView> {
        let mut views: Vec<_> = self
            .completed
            .values()
            .filter(|entry| entry.identity_id == self.identity_id)
            .map(Entry::view)
            .collect();
        views.sort_by(|left, right| {
            right
                .updated_at
                .cmp(&left.updated_at)
                .then_with(|| left.operation_id.cmp(&right.operation_id))
        });
        views
    }

    pub(crate) fn reserve(
        &mut self,
        request: RequestEnvelope,
        now: u64,
    ) -> Result<SubmitAdmission, ControlError> {
        let identity_id = self
            .identity_id
            .as_ref()
            .ok_or_else(|| ControlError::new(ErrorCode::NotConnected))?;
        if let Some(prior) = self
            .completed
            .get(&request.operation_id)
            .or_else(|| self.pending.get(&request.operation_id))
        {
            if prior.identity_id.as_ref() != Some(identity_id) || prior.request != request {
                return Err(ControlError::new(ErrorCode::OperationConflict));
            }
            return Ok(if prior.state == OperationState::Submitting {
                SubmitAdmission::InFlight(prior.view())
            } else {
                SubmitAdmission::Existing(prior.view())
            });
        }
        if self.pending.len() >= self.max_pending {
            return Err(ControlError::new(ErrorCode::PendingLimit).retryable(true));
        }
        self.next_reservation = self
            .next_reservation
            .checked_add(1)
            .ok_or_else(ControlError::invalid)?;
        let ticket = DispatchTicket {
            reservation: self.next_reservation,
            identity_id: identity_id.clone(),
            request: request.clone(),
        };
        self.pending.insert(
            request.operation_id.clone(),
            Entry {
                identity_id: Some(identity_id.clone()),
                reservation: ticket.reservation,
                request,
                state: OperationState::Submitting,
                created_at: now,
                updated_at: now,
                audit_trace_id: None,
                terminal_status: None,
                outcome_digest: None,
            },
        );
        Ok(SubmitAdmission::New(ticket))
    }

    pub(crate) fn active_entry(&self, operation_id: &str) -> Option<&Entry> {
        self.pending
            .get(operation_id)
            .filter(|entry| entry.identity_id == self.identity_id)
    }

    pub(crate) fn completed_entry(&self, operation_id: &str) -> Option<&Entry> {
        self.completed
            .get(operation_id)
            .filter(|entry| entry.identity_id == self.identity_id)
    }

    pub fn recovery_record(&self, ticket: &DispatchTicket) -> Result<Value, ControlError> {
        Ok(self.match_ticket(ticket)?.recovery_value())
    }

    fn match_ticket(&self, ticket: &DispatchTicket) -> Result<&Entry, ControlError> {
        self.pending
            .get(&ticket.request.operation_id)
            .filter(|entry| {
                entry.reservation == ticket.reservation
                    && entry.request == ticket.request
                    && entry.identity_id.as_deref() == Some(ticket.identity_id.as_str())
            })
            .ok_or_else(|| ControlError::new(ErrorCode::OperationConflict))
    }

    pub(crate) fn acknowledge(
        &mut self,
        ticket: &DispatchTicket,
        acknowledgement: &Value,
        now: u64,
    ) -> Result<OperationView, ControlError> {
        if let Some(completed) = self.completed.get(&ticket.request.operation_id) {
            if completed.reservation == ticket.reservation && completed.request == ticket.request {
                return Ok(completed.view());
            }
            return Err(ControlError::new(ErrorCode::OperationConflict));
        }
        self.match_ticket(ticket)?;
        let result = validate_ack(&ticket.request, acknowledgement);
        let (status, audit) = match result {
            Ok(validated) => validated,
            Err(error) => return self.fail(ticket, &error, now),
        };
        let entry = self
            .pending
            .get_mut(&ticket.request.operation_id)
            .ok_or_else(ControlError::invalid)?;
        entry.state = if status == "indeterminate" {
            OperationState::Indeterminate
        } else {
            OperationState::Pending
        };
        entry.audit_trace_id = Some(audit);
        entry.updated_at = now;
        Ok(entry.view())
    }

    pub(crate) fn fail(
        &mut self,
        ticket: &DispatchTicket,
        error: &ControlError,
        now: u64,
    ) -> Result<OperationView, ControlError> {
        if let Some(completed) = self.completed.get(&ticket.request.operation_id)
            && completed.reservation == ticket.reservation
            && completed.request == ticket.request
        {
            return Ok(completed.view());
        }
        self.match_ticket(ticket)?;
        if error.definitely_not_accepted() {
            self.pending.remove(&ticket.request.operation_id);
            return Err(error.clone());
        }
        let entry = self
            .pending
            .get_mut(&ticket.request.operation_id)
            .ok_or_else(ControlError::invalid)?;
        entry.state = OperationState::Indeterminate;
        entry.updated_at = now;
        Err(ControlError::new(ErrorCode::AmbiguousSubmission)
            .retryable(true)
            .with_dispatch(true)
            .detail(
                "operationId",
                Value::String(ticket.request.operation_id.clone()),
            )
            .detail(
                "semanticDigest",
                Value::String(ticket.request.semantic_digest.clone()),
            ))
    }

    /// This is crate-private: only the controller's session-bound lookup completion may call it.
    pub(crate) fn observe(
        &mut self,
        request: &RequestEnvelope,
        observation: &Value,
        now: u64,
    ) -> Result<OperationView, ControlError> {
        if let Some(entry) = self.completed_entry(&request.operation_id) {
            if entry.request != *request {
                return Err(ControlError::new(ErrorCode::OperationConflict));
            }
            return Ok(entry.view());
        }
        validate_response_object(observation)?;
        let retained = self
            .active_entry(&request.operation_id)
            .ok_or_else(ControlError::invalid)?;
        if retained.request != *request {
            return Err(ControlError::new(ErrorCode::OperationConflict));
        }
        if observation.get("found") == Some(&Value::Bool(false)) {
            if retained.audit_trace_id.is_some() {
                return Err(ControlError::new(ErrorCode::AckMismatch));
            }
            let entry = self
                .pending
                .get_mut(&request.operation_id)
                .ok_or_else(ControlError::invalid)?;
            entry.state = OperationState::Indeterminate;
            entry.updated_at = now;
            return Ok(entry.view());
        }
        if observation.get("found") != Some(&Value::Bool(true)) {
            return Err(ControlError::invalid());
        }
        if observation.get("operationId").and_then(Value::as_str)
            != Some(request.operation_id.as_str())
            || observation.get("semanticDigest").and_then(Value::as_str)
                != Some(request.semantic_digest.as_str())
        {
            return Err(ControlError::new(ErrorCode::AckMismatch));
        }
        let audit = bounded_id(observation.get("auditTraceId"))?;
        if retained
            .audit_trace_id
            .as_ref()
            .is_some_and(|expected| expected != &audit)
        {
            return Err(ControlError::new(ErrorCode::AckMismatch));
        }
        let status = observation
            .get("status")
            .and_then(Value::as_str)
            .ok_or_else(ControlError::invalid)?;
        let terminal = matches!(status, "succeeded" | "failed" | "rejected" | "cancelled");
        if !terminal && !matches!(status, "accepted" | "pending" | "indeterminate") {
            return Err(ControlError::invalid());
        }
        let outcome = match observation.get("outcomeDigest") {
            None | Some(Value::Null) => None,
            Some(Value::String(value)) if is_digest(value) => Some(value.clone()),
            Some(_) => return Err(ControlError::invalid()),
        };
        let entry = self
            .pending
            .get_mut(&request.operation_id)
            .ok_or_else(ControlError::invalid)?;
        entry.audit_trace_id = Some(audit);
        entry.updated_at = now;
        if terminal {
            entry.state = OperationState::Terminal;
            entry.terminal_status = Some(status.to_owned());
            entry.outcome_digest = outcome;
            let terminal = self
                .pending
                .remove(&request.operation_id)
                .ok_or_else(ControlError::invalid)?;
            let view = terminal.view();
            self.completed_order.push_back(request.operation_id.clone());
            self.completed
                .insert(request.operation_id.clone(), terminal);
            while self.completed.len() > MAX_COMPLETED {
                if let Some(id) = self.completed_order.pop_front() {
                    self.completed.remove(&id);
                }
            }
            Ok(view)
        } else {
            entry.state = if status == "indeterminate" {
                OperationState::Indeterminate
            } else {
                OperationState::Pending
            };
            Ok(entry.view())
        }
    }
}

pub(crate) fn is_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

pub(crate) fn bounded_id(value: Option<&Value>) -> Result<String, ControlError> {
    let value = value
        .and_then(Value::as_str)
        .ok_or_else(|| ControlError::new(ErrorCode::AckMismatch))?;
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
    {
        return Err(ControlError::new(ErrorCode::AckMismatch));
    }
    Ok(value.to_owned())
}

fn validate_ack(
    request: &RequestEnvelope,
    acknowledgement: &Value,
) -> Result<(String, String), ControlError> {
    validate_response_object(acknowledgement)?;
    match acknowledgement.get("accepted") {
        Some(Value::Bool(false)) => return Err(ControlError::new(ErrorCode::BackendRejected)),
        Some(Value::Bool(true)) => {}
        _ => return Err(ControlError::invalid()),
    }
    let operation_id = bounded_id(acknowledgement.get("operationId"))?;
    let digest = acknowledgement
        .get("semanticDigest")
        .and_then(Value::as_str)
        .ok_or_else(ControlError::invalid)?;
    let status = acknowledgement
        .get("status")
        .and_then(Value::as_str)
        .ok_or_else(ControlError::invalid)?;
    let audit = bounded_id(acknowledgement.get("auditTraceId"))?;
    if operation_id != request.operation_id
        || digest != request.semantic_digest
        || !matches!(status, "accepted" | "pending" | "indeterminate")
    {
        return Err(ControlError::new(ErrorCode::AckMismatch));
    }
    Ok((status.to_owned(), audit))
}

/// Validate a backend object before any local recovery-retirement decision.
pub fn validate_response_object(value: &Value) -> Result<(), ControlError> {
    let object = value.as_object().ok_or_else(ControlError::invalid)?;
    if object
        .keys()
        .any(|key| matches!(key.as_str(), "__proto__" | "constructor" | "prototype"))
    {
        return Err(ControlError::invalid());
    }
    Ok(())
}
