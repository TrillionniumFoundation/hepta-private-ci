//! Synchronous decisions and opaque effect tickets. No await can precede reservation.
use crate::canonical::{assert_sha256, assert_stable_identifier};
use crate::confirmation::{
    Confirmation, ConfirmationView, assert_confirmation, capture_confirmation,
};
use crate::error::{ControlError, ErrorCode};
use crate::ledger::{
    OperationLedger, OperationState, OperationView, RequestEnvelope, SubmitAdmission,
};
use crate::projection::{
    Action, PROTOCOL_VERSION, RuntimeSnapshot, Session, build_operation_intent,
    digest_operation_intent, normalize_session, normalize_snapshot, validate_snapshot_transition,
};
use serde_json::{Value, json};

const READ: &str = "hepta://ui.control/runtime.read";

mod recovery;
mod types;
pub use types::*;

/// One presentation/session owner; runtime facts and effect authority stay in backend owners.
#[derive(Debug)]
pub struct Controller {
    session: Option<Session>,
    snapshot: Option<RuntimeSnapshot>,
    high_watermark: Option<RuntimeSnapshot>,
    epoch: u64,
    persistence_revision: u64,
    snapshot_observed_at: Option<u64>,
    ledger: OperationLedger,
    scheduler: crate::scheduler::RecoveryScheduler,
}

impl Controller {
    pub fn new(max_pending: usize) -> Result<Self, ControlError> {
        Ok(Self {
            session: None,
            snapshot: None,
            high_watermark: None,
            epoch: 0,
            persistence_revision: 0,
            snapshot_observed_at: None,
            ledger: OperationLedger::new(max_pending)?,
            scheduler: crate::scheduler::RecoveryScheduler::default(),
        })
    }

    pub fn begin_connect(&mut self) -> Result<ConnectionTicket, ControlError> {
        if self.session.is_some() {
            return Err(ControlError::new(ErrorCode::AlreadyConnected));
        }
        self.epoch = self
            .epoch
            .checked_add(1)
            .ok_or_else(ControlError::invalid)?;
        Ok(ConnectionTicket { epoch: self.epoch })
    }

    pub fn connected(
        &mut self,
        ticket: &ConnectionTicket,
        raw: &Value,
        now: u64,
    ) -> Result<ControlView, ControlError> {
        let session = normalize_session(raw, PROTOCOL_VERSION, now)?;
        if ticket.epoch != self.epoch || self.session.is_some() {
            return Err(ControlError::new(ErrorCode::Aborted));
        }
        if self.ledger.identity_id.as_deref() != Some(session.identity_id()) {
            self.scheduler = crate::scheduler::RecoveryScheduler::default();
        }
        self.ledger.set_identity(session.identity_id());
        self.session = Some(session);
        self.snapshot = None;
        self.high_watermark = None;
        Ok(self.view(now))
    }

    pub fn session_ticket(&mut self, now: u64) -> Result<SessionTicket, ControlError> {
        self.require_permission(READ, now)?;
        Ok(SessionTicket {
            epoch: self.epoch,
            session: self.session.clone().ok_or_else(ControlError::invalid)?,
        })
    }

    fn ticket_current(&self, ticket: &SessionTicket) -> bool {
        ticket.epoch == self.epoch && self.session.as_ref() == Some(&ticket.session)
    }

    pub fn session_refreshed(
        &mut self,
        ticket: &SessionTicket,
        raw: &Value,
        now: u64,
    ) -> Result<ControlView, ControlError> {
        if !self.ticket_current(ticket) {
            return Err(ControlError::new(ErrorCode::StaleGeneration));
        }
        let validate = || -> Result<Session, ControlError> {
            let next = normalize_session(raw, PROTOCOL_VERSION, now)?;
            let old = &ticket.session;
            if next.session_id() != old.session_id() {
                return Err(ControlError::new(ErrorCode::SessionRevoked));
            }
            if next.identity_id() != old.identity_id() {
                return Err(ControlError::new(ErrorCode::SessionIdentityChanged));
            }
            if next.connection_generation() < old.connection_generation() {
                return Err(ControlError::new(ErrorCode::StaleGeneration));
            }
            if next.permission_revision() < old.permission_revision()
                || (next.permission_revision() == old.permission_revision()
                    && next.permissions() != old.permissions())
            {
                return Err(ControlError::new(ErrorCode::StalePermissionRevision));
            }
            Ok(next)
        };
        let next = match validate() {
            Ok(next) => next,
            Err(error) => {
                self.invalidate();
                return Err(error);
            }
        };
        if next.connection_generation() != ticket.session.connection_generation() {
            self.snapshot = None;
        }
        // A successful refresh is a new authenticated observation even when its bytes match.
        // This preserves JS object-incarnation fencing for pre-refresh callbacks.
        self.epoch = self
            .epoch
            .checked_add(1)
            .ok_or_else(ControlError::invalid)?;
        self.session = Some(next);
        Ok(self.view(now))
    }

    pub fn snapshot_received(
        &mut self,
        ticket: &SessionTicket,
        raw: &Value,
        now: u64,
    ) -> Result<ControlView, ControlError> {
        if !self.ticket_current(ticket) {
            return Err(ControlError::new(ErrorCode::StaleGeneration));
        }
        self.require_permission(READ, now)?;
        let result = normalize_snapshot(raw, &ticket.session)
            .and_then(|next| validate_snapshot_transition(self.high_watermark.as_ref(), &next));
        match result {
            Ok(snapshot) => {
                self.high_watermark = Some(snapshot.clone());
                self.snapshot = Some(snapshot);
                self.snapshot_observed_at = Some(now);
                Ok(self.view(now))
            }
            Err(error) => {
                if matches!(
                    error.code,
                    ErrorCode::InvalidInput | ErrorCode::SnapshotDrift
                ) {
                    self.snapshot = None;
                }
                Err(error)
            }
        }
    }

    pub fn snapshot_failed(&mut self, ticket: &SessionTicket, error: &ControlError) {
        if self.ticket_current(ticket) {
            self.snapshot = None;
            self.session_failed(ticket, error);
        }
    }

    pub fn session_failed(&mut self, ticket: &SessionTicket, error: &ControlError) {
        if self.ticket_current(ticket)
            && (matches!(
                error.code,
                ErrorCode::SessionExpired
                    | ErrorCode::SessionRevoked
                    | ErrorCode::SessionIdentityChanged
                    | ErrorCode::StalePermissionRevision
                    | ErrorCode::ProtocolMismatch
            ) || (error.code == ErrorCode::PermissionDenied
                && error.details.get("status").and_then(Value::as_u64) == Some(403)))
        {
            self.invalidate();
        }
    }

    pub fn view(&mut self, now: u64) -> ControlView {
        self.expire(now);
        let pending = self.ledger.pending_views();
        let completed = self.ledger.completed_views();
        ControlView {
            connected: self.session.is_some(),
            authenticated: self.session.is_some(),
            session_id: self.session.as_ref().map(|s| s.session_id().to_owned()),
            identity_id: self.session.as_ref().map(|s| s.identity_id().to_owned()),
            connection_generation: self.session.as_ref().map(Session::connection_generation),
            permission_revision: self.session.as_ref().map(Session::permission_revision),
            permissions: self
                .session
                .as_ref()
                .map(|s| s.permissions().to_vec())
                .unwrap_or_default(),
            expires_at: self.session.as_ref().map(Session::expires_at),
            stale: self.snapshot.is_none(),
            snapshot: self.snapshot.clone(),
            pending_count: pending.len(),
            completed_count: completed.len(),
            indeterminate_count: pending
                .iter()
                .filter(|op| op.state == OperationState::Indeterminate)
                .count(),
            pending_max_age_ms: pending
                .iter()
                .map(|op| now.saturating_sub(op.created_at))
                .max()
                .unwrap_or(0),
            snapshot_age_ms: self
                .snapshot
                .as_ref()
                .and(self.snapshot_observed_at)
                .map(|time| now.saturating_sub(time)),
            pending,
            completed,
            recovery_metrics: self.scheduler.metrics(),
        }
    }

    fn confirmation_view(&self) -> ConfirmationView<'_> {
        ConfirmationView {
            session: self.session.as_ref(),
            snapshot: self.snapshot.as_ref(),
            connected: self.session.is_some(),
            authenticated: self.session.is_some(),
            stale: self.snapshot.is_none(),
        }
    }

    pub fn capture_confirmation(
        &mut self,
        input: &SubmissionInput,
        now: u64,
    ) -> Result<Confirmation, ControlError> {
        self.expire(now);
        capture_confirmation(&self.confirmation_view(), &input.confirmation_input())
    }

    pub fn begin_submit(
        &mut self,
        input: SubmissionInput,
        now: u64,
    ) -> Result<SubmissionAdmission, ControlError> {
        let (method, permission) = route(input.action);
        self.require_permission(permission, now)?;
        assert_stable_identifier(&input.operation_id)?;
        let session = self.session.clone().ok_or_else(ControlError::invalid)?;
        let snapshot = self
            .snapshot
            .clone()
            .ok_or_else(|| ControlError::new(ErrorCode::StaleRevision))?;
        if input.displayed_revision != snapshot.revision() {
            return Err(ControlError::new(ErrorCode::StaleRevision));
        }
        let intent = build_operation_intent(
            &json!({"action":input.action,"targetId":input.target_id,
            "generation":snapshot.generation(),"displayedRevision":input.displayed_revision,"reason":input.reason}),
        )?;
        let digest = digest_operation_intent(&intent)?;
        if let Some(supplied) = &input.semantic_digest {
            assert_sha256(supplied)?;
            if supplied != &digest {
                return Err(ControlError::new(ErrorCode::OperationConflict));
            }
        }
        if input.confirmation.is_some() {
            assert_confirmation(
                input.confirmation.as_ref(),
                &self.confirmation_view(),
                &input.confirmation_input(),
            )?;
        }
        let request = RequestEnvelope {
            protocol_version: PROTOCOL_VERSION.to_owned(),
            method: method.to_owned(),
            operation_id: input.operation_id.clone(),
            semantic_digest: digest,
            action: input.action.as_str().to_owned(),
            target_id: input.target_id.clone(),
            reason: input.reason.clone(),
            session_id: session.session_id().to_owned(),
            connection_generation: session.connection_generation(),
            generation: snapshot.generation(),
            displayed_revision: snapshot.revision(),
            snapshot_digest: snapshot.semantic_digest().to_owned(),
        };
        Ok(match self.ledger.reserve(request, now)? {
            SubmitAdmission::New(dispatch) => {
                SubmissionAdmission::New(Box::new(SubmissionTicket {
                    dispatch,
                    observer: SessionTicket {
                        epoch: self.epoch,
                        session,
                    },
                    snapshot,
                    input,
                    persistence_revision: self.persistence_revision,
                }))
            }
            SubmitAdmission::InFlight(view) => SubmissionAdmission::InFlight(view),
            SubmitAdmission::Existing(view) => SubmissionAdmission::Existing(view),
        })
    }

    pub fn recovery_record(&self, ticket: &SubmissionTicket) -> Result<Value, ControlError> {
        self.ledger.recovery_record(&ticket.dispatch)
    }

    /// Recheck after persistence settles and immediately before the transport call.
    pub fn revalidate_dispatch(
        &mut self,
        ticket: &SubmissionTicket,
        now: u64,
    ) -> Result<(), ControlError> {
        self.require_permission(route(ticket.input.action).1, now)
            .map_err(|error| error.with_dispatch(false))?;
        if !self.ticket_current(&ticket.observer)
            || self.snapshot.as_ref() != Some(&ticket.snapshot)
            || self.persistence_revision != ticket.persistence_revision
        {
            return Err(ControlError::unsent(ErrorCode::StaleRevision));
        }
        self.ledger.recovery_record(&ticket.dispatch)?;
        if ticket.input.confirmation.is_some() {
            assert_confirmation(
                ticket.input.confirmation.as_ref(),
                &self.confirmation_view(),
                &ticket.input.confirmation_input(),
            )?;
        }
        Ok(())
    }

    pub fn submission_acknowledged(
        &mut self,
        ticket: &SubmissionTicket,
        acknowledgement: &Value,
        now: u64,
    ) -> Result<OperationView, ControlError> {
        self.ledger
            .acknowledge(&ticket.dispatch, acknowledgement, now)
    }

    pub fn submission_failed(
        &mut self,
        ticket: &SubmissionTicket,
        error: &ControlError,
        now: u64,
    ) -> Result<OperationView, ControlError> {
        self.session_failed(&ticket.observer, error);
        self.ledger.fail(&ticket.dispatch, error, now)
    }

    pub fn begin_lookup(
        &mut self,
        operation_id: &str,
        now: u64,
    ) -> Result<LookupAdmission, ControlError> {
        let observer = self.session_ticket(now)?;
        assert_stable_identifier(operation_id)?;
        if let Some(entry) = self.ledger.completed_entry(operation_id) {
            return Ok(LookupAdmission::Local(entry.view()));
        }
        let entry = self
            .ledger
            .active_entry(operation_id)
            .ok_or_else(ControlError::invalid)?;
        if entry.state == OperationState::Submitting {
            return Ok(LookupAdmission::Local(entry.view()));
        }
        Ok(LookupAdmission::Query(LookupTicket {
            observer,
            request: entry.request.clone(),
        }))
    }

    pub fn lookup_received(
        &mut self,
        ticket: &LookupTicket,
        observation: &Value,
        now: u64,
    ) -> Result<OperationView, ControlError> {
        self.require_permission(READ, now)?;
        if !self.ticket_current(&ticket.observer) {
            return Err(ControlError::new(ErrorCode::StaleGeneration));
        }
        self.ledger.observe(&ticket.request, observation, now)
    }

    pub fn lookup_failed(&mut self, ticket: &LookupTicket, error: &ControlError) {
        self.session_failed(&ticket.observer, error);
    }
    pub fn export_recovery(&self) -> Value {
        self.ledger.export_recovery()
    }
    pub fn restore_recovery(&mut self, state: &Value) -> Result<(), ControlError> {
        self.ledger.restore_recovery(state)
    }

    pub fn persistence_changed(&mut self) -> Result<(), ControlError> {
        if self
            .ledger
            .pending_views()
            .iter()
            .any(|entry| entry.state == OperationState::Submitting)
        {
            return Err(ControlError::invalid());
        }
        self.persistence_revision = self
            .persistence_revision
            .checked_add(1)
            .ok_or_else(ControlError::invalid)?;
        Ok(())
    }

    pub fn close(&mut self) -> Option<Session> {
        self.epoch = self.epoch.saturating_add(1);
        let previous = self.session.clone();
        self.invalidate();
        previous
    }

    fn expire(&mut self, now: u64) {
        if self
            .session
            .as_ref()
            .is_some_and(|session| session.expires_at() <= now)
        {
            self.invalidate();
        }
    }
    fn invalidate(&mut self) {
        self.session = None;
        self.snapshot = None;
        self.high_watermark = None;
    }
    fn require_permission(&mut self, permission: &str, now: u64) -> Result<(), ControlError> {
        if self
            .session
            .as_ref()
            .is_some_and(|session| session.expires_at() <= now)
        {
            self.invalidate();
            return Err(ControlError::new(ErrorCode::SessionExpired));
        }
        let session = self
            .session
            .as_ref()
            .ok_or_else(|| ControlError::new(ErrorCode::NotConnected))?;
        if !session
            .permissions()
            .iter()
            .any(|granted| granted == permission)
        {
            return Err(ControlError::new(ErrorCode::PermissionDenied));
        }
        Ok(())
    }
}

fn route(action: Action) -> (&'static str, &'static str) {
    match action {
        Action::RequestStart => ("runtime/start", "hepta://ui.control/runtime.start"),
        Action::RequestStop => ("runtime/stop", "hepta://ui.control/runtime.stop"),
        Action::RequestQuarantine
        | Action::RequestReconcile
        | Action::RequestRetry
        | Action::RequestRollback => ("runtime/request", "hepta://ui.control/runtime.request"),
    }
}
