//! One bounded operation identity owner. Local records never prove external success.
use crate::contract::{Observation, OperationRequest, OperationStatus, validate_audit_trace};
use crate::{ControlError, ErrorCode, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationState {
    Submitting,
    Pending,
    Indeterminate,
    Terminal,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationView {
    pub operation_id: String,
    pub semantic_digest: String,
    pub target_id: String,
    pub state: OperationState,
    pub audit_trace_id: Option<String>,
    pub terminal_status: Option<OperationStatus>,
    pub outcome_digest: Option<String>,
    pub generation: u64,
    pub displayed_revision: u64,
    pub created_at: u64,
    pub updated_at: u64,
}

#[derive(Clone)]
pub(crate) struct Record {
    pub identity_id: String,
    pub request: OperationRequest,
    pub state: OperationState,
    pub audit_trace_id: Option<String>,
    pub terminal_status: Option<OperationStatus>,
    pub outcome_digest: Option<String>,
    pub created_at: u64,
    pub updated_at: u64,
    pub admitted_record: Value,
    pub cleanup_complete: bool,
}

impl Record {
    pub fn view(&self) -> OperationView {
        OperationView {
            operation_id: self.request.operation_id.clone(),
            semantic_digest: self.request.semantic_digest.clone(),
            target_id: self.request.target_id.clone(),
            state: self.state,
            audit_trace_id: self.audit_trace_id.clone(),
            terminal_status: self.terminal_status,
            outcome_digest: self.outcome_digest.clone(),
            generation: self.request.generation,
            displayed_revision: self.request.displayed_revision,
            created_at: self.created_at,
            updated_at: self.updated_at,
        }
    }
}

// Failed terminal cleanup keeps its slot: no import or new admission may erase it.
pub(crate) const MAX_RETAINED_OPERATIONS: usize = 4096;

pub(crate) struct OperationLedger {
    pub pending: BTreeMap<String, Record>,
    pub completed: BTreeMap<String, Record>,
    identity: Option<String>,
    capacity: usize,
}

impl OperationLedger {
    pub fn new(capacity: usize) -> Result<Self> {
        if capacity == 0 || capacity > 4096 {
            return Err(ControlError::new(ErrorCode::InvalidInput));
        }
        Ok(Self {
            pending: BTreeMap::new(),
            completed: BTreeMap::new(),
            identity: None,
            capacity,
        })
    }
    pub fn set_identity(&mut self, identity: &str) -> Result<()> {
        crate::canonical::assert_stable_identifier(identity)?;
        self.identity = Some(identity.into());
        Ok(())
    }
    pub fn pending_views(&self) -> Vec<OperationView> {
        self.pending
            .values()
            .filter(|record| Some(&record.identity_id) == self.identity.as_ref())
            .map(Record::view)
            .collect()
    }
    pub fn completed_views(&self) -> Vec<OperationView> {
        let mut result: Vec<_> = self
            .completed
            .values()
            .filter(|record| Some(&record.identity_id) == self.identity.as_ref())
            .map(Record::view)
            .collect();
        result.sort_by(|a, b| {
            b.updated_at
                .cmp(&a.updated_at)
                .then_with(|| a.operation_id.cmp(&b.operation_id))
        });
        result
    }
    pub fn find(&self, id: &str) -> Option<&Record> {
        self.pending
            .get(id)
            .or_else(|| self.completed.get(id))
            .filter(|record| Some(&record.identity_id) == self.identity.as_ref())
    }
    pub fn reserve(
        &mut self,
        request: OperationRequest,
        now: u64,
    ) -> Result<(OperationView, bool)> {
        request.validate()?;
        crate::canonical::assert_safe_integer(now, 1)?;
        let identity = self
            .identity
            .clone()
            .ok_or_else(|| ControlError::new(ErrorCode::NotConnected))?;
        if let Some(prior) = self
            .pending
            .get(&request.operation_id)
            .or_else(|| self.completed.get(&request.operation_id))
        {
            if prior.identity_id != identity || prior.request != request {
                return Err(ControlError::new(ErrorCode::OperationConflict));
            }
            return Ok((prior.view(), false));
        }
        if self.pending.len() >= self.capacity
            || self.pending.len() + self.completed.len() >= MAX_RETAINED_OPERATIONS
        {
            return Err(ControlError::new(ErrorCode::PendingLimit));
        }
        let mut admitted_record = serde_json::to_value(&request)
            .map_err(|_| ControlError::new(ErrorCode::InvalidInput))?;
        let object = admitted_record
            .as_object_mut()
            .ok_or_else(|| ControlError::new(ErrorCode::InvalidInput))?;
        object.extend([
            ("state".into(), json!("submitting")),
            ("auditTraceId".into(), Value::Null),
            ("createdAt".into(), json!(now)),
            ("updatedAt".into(), json!(now)),
        ]);
        let record = Record {
            identity_id: identity,
            request,
            state: OperationState::Submitting,
            audit_trace_id: None,
            terminal_status: None,
            outcome_digest: None,
            created_at: now,
            updated_at: now,
            admitted_record,
            cleanup_complete: false,
        };
        let view = record.view();
        self.pending
            .insert(record.request.operation_id.clone(), record);
        Ok((view, true))
    }
    pub fn mark_active(
        &mut self,
        id: &str,
        status: OperationStatus,
        audit: Option<String>,
        now: u64,
    ) -> Result<OperationView> {
        let record = self
            .pending
            .get_mut(id)
            .ok_or_else(|| ControlError::new(ErrorCode::InvalidInput))?;
        if Some(&record.identity_id) != self.identity.as_ref() {
            return Err(ControlError::new(ErrorCode::OperationConflict));
        }
        if let Some(audit) = audit {
            validate_audit_trace(record.audit_trace_id.as_deref(), Some(&audit))?;
            record.audit_trace_id = Some(audit);
        }
        if !status.is_active() {
            return Err(ControlError::new(ErrorCode::InvalidInput));
        }
        record.state = if status == OperationStatus::Indeterminate {
            OperationState::Indeterminate
        } else {
            OperationState::Pending
        };
        record.updated_at = now;
        Ok(record.view())
    }
    pub fn reconcile(&mut self, observation: Observation, now: u64) -> Result<OperationView> {
        observation.validate()?;
        let existing = self
            .find(&observation.operation_id)
            .ok_or_else(|| ControlError::new(ErrorCode::InvalidInput))?;
        if existing.request.semantic_digest != observation.semantic_digest {
            return Err(ControlError::new(ErrorCode::OperationConflict));
        }
        validate_audit_trace(
            existing.audit_trace_id.as_deref(),
            observation.audit_trace_id.as_deref(),
        )?;
        if existing.state == OperationState::Terminal {
            if existing.terminal_status != Some(observation.status)
                || existing.outcome_digest != observation.outcome_digest
            {
                return Err(ControlError::new(ErrorCode::OperationConflict));
            }
            return Ok(existing.view());
        }
        let mut record = self
            .pending
            .remove(&observation.operation_id)
            .ok_or_else(|| ControlError::new(ErrorCode::InvalidInput))?;
        record.state = OperationState::Terminal;
        record.terminal_status = Some(observation.status);
        record.audit_trace_id = observation.audit_trace_id;
        record.outcome_digest = observation.outcome_digest;
        record.updated_at = now;
        let view = record.view();
        self.completed.insert(observation.operation_id, record);
        // Keep terminal records until durable cleanup succeeds; bounded history never drops outstanding maintenance.
        Ok(view)
    }
    pub fn prune_completed(&mut self, id: &str) {
        if let Some(record) = self.completed.get_mut(id) {
            record.cleanup_complete = true;
        }
        while self.completed.len() > 1024 {
            let oldest = self
                .completed
                .iter()
                .filter(|(_, record)| record.cleanup_complete)
                .min_by_key(|(_, record)| record.updated_at)
                .map(|(id, _)| id.clone());
            if let Some(oldest) = oldest {
                self.completed.remove(&oldest);
            } else {
                break;
            }
        }
    }
    pub fn restore(&mut self, values: BTreeMap<String, Value>) -> Result<()> {
        let identity = self
            .identity
            .clone()
            .ok_or_else(|| ControlError::new(ErrorCode::NotConnected))?;
        if values.len() > self.capacity {
            return Err(ControlError::new(ErrorCode::PendingLimit));
        }
        let mut additions = BTreeMap::new();
        for (id, value) in values {
            let mut object = value
                .as_object()
                .cloned()
                .ok_or_else(|| ControlError::new(ErrorCode::InvalidInput))?;
            let time = |key: &str| -> Result<u64> {
                crate::canonical::assert_safe_integer(
                    value[key]
                        .as_u64()
                        .ok_or_else(|| ControlError::new(ErrorCode::InvalidInput))?,
                    1,
                )
            };
            let created_at = time("createdAt")?;
            let updated_at = time("updatedAt")?;
            let audit_trace_id = match value.get("auditTraceId") {
                None | Some(Value::Null) => None,
                Some(Value::String(value)) => Some(value.clone()),
                Some(_) => return Err(ControlError::new(ErrorCode::InvalidInput)),
            };
            if let Some(audit) = &audit_trace_id {
                crate::canonical::assert_stable_identifier(audit)?;
            }
            for key in ["state", "auditTraceId", "createdAt", "updatedAt"] {
                object.remove(key);
            }
            let request: OperationRequest = serde_json::from_value(Value::Object(object))
                .map_err(|_| ControlError::new(ErrorCode::InvalidInput))?;
            request.validate()?;
            if id != request.operation_id {
                return Err(ControlError::new(ErrorCode::OperationConflict));
            }
            if let Some(prior) = self.pending.get(&id).or_else(|| self.completed.get(&id)) {
                if prior.identity_id != identity || prior.request != request {
                    return Err(ControlError::new(ErrorCode::OperationConflict));
                }
            } else {
                additions.insert(
                    id,
                    Record {
                        identity_id: identity.clone(),
                        request,
                        state: OperationState::Indeterminate,
                        audit_trace_id,
                        terminal_status: None,
                        outcome_digest: None,
                        created_at,
                        updated_at,
                        admitted_record: value,
                        cleanup_complete: false,
                    },
                );
            }
        }
        if self.pending.len() + additions.len() > self.capacity
            || self.pending.len() + self.completed.len() + additions.len() > MAX_RETAINED_OPERATIONS
        {
            return Err(ControlError::new(ErrorCode::PendingLimit));
        }
        self.pending.extend(additions);
        Ok(())
    }
}
