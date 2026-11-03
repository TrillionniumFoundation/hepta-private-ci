//! Worker-owned synchronous client. Exclusive borrowing serializes admission and session changes.
#[path = "client_operations.rs"]
mod operations;
use crate::contract::{
    self, ConfirmationContext, ConfirmationInput, Method, Observation, OperationIntent,
    OperationRequest, OperationStatus, Permission, Session,
};
use crate::ledger::{OperationLedger, OperationState, OperationView};
use crate::maintenance::{RecoverySchedule, SessionSchedule};
use crate::projection::{Snapshot, normalize_snapshot, validate_snapshot_transition};
use crate::recovery::{Preparation, RecoveryStore};
use crate::{ControlError, ControlTransport, ErrorCode, Result};
use serde_json::{Value, json};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlView {
    pub session: Option<Session>,
    pub snapshot: Option<Snapshot>,
    pub stale: bool,
    pub pending: Vec<OperationView>,
    pub completed: Vec<OperationView>,
    pub storage_error: bool,
}

pub struct RuntimeClient<T: ControlTransport, R: RecoveryStore> {
    transport: T,
    recovery: R,
    session: Option<Session>,
    snapshot: Option<Snapshot>,
    last_snapshot: Option<Snapshot>,
    ledger: OperationLedger,
    clock: Box<dyn Fn() -> u64 + Send + Sync>,
    storage_error: bool,
    recovery_schedule: RecoverySchedule,
    session_schedule: SessionSchedule,
    cleanup_cursor: Option<String>,
}

fn encoded<T: serde::Serialize>(value: &T) -> Result<Value> {
    serde_json::to_value(value).map_err(|_| ControlError::new(ErrorCode::InvalidInput))
}
fn system_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |value| value.as_millis().try_into().unwrap_or(u64::MAX))
}
fn rejects(error: &ControlError) -> bool {
    error.request_dispatched == Some(false)
        || matches!(
            error.code,
            ErrorCode::BackendRejected
                | ErrorCode::OperationConflict
                | ErrorCode::StaleRevision
                | ErrorCode::PermissionDenied
                | ErrorCode::SessionExpired
                | ErrorCode::SessionRevoked
                | ErrorCode::ProtocolMismatch
        )
}

fn validate_endpoint_binding<T: ControlTransport, R: RecoveryStore>(
    transport: &T,
    recovery: &R,
) -> Result<()> {
    recovery.scope().validate()?;
    let invalid = || ControlError::new(ErrorCode::Storage).not_dispatched();
    let endpoint = url::Url::parse(transport.endpoint()).map_err(|_| invalid())?;
    let recovery_endpoint = url::Url::parse(&recovery.scope().endpoint).map_err(|_| invalid())?;
    if endpoint != recovery_endpoint {
        return Err(invalid());
    }
    Ok(())
}

impl<T: ControlTransport, R: RecoveryStore> RuntimeClient<T, R> {
    pub fn new(transport: T, recovery: R, capacity: usize) -> Result<Self> {
        Self::with_clock(transport, recovery, capacity, Box::new(system_now))
    }
    pub fn with_clock(
        transport: T,
        recovery: R,
        capacity: usize,
        clock: Box<dyn Fn() -> u64 + Send + Sync>,
    ) -> Result<Self> {
        validate_endpoint_binding(&transport, &recovery)?;
        Ok(Self {
            transport,
            recovery,
            session: None,
            snapshot: None,
            last_snapshot: None,
            ledger: OperationLedger::new(capacity)?,
            clock,
            storage_error: false,
            recovery_schedule: RecoverySchedule::default(),
            session_schedule: SessionSchedule::default(),
            cleanup_cursor: None,
        })
    }
    pub fn replace_recovery_store(&mut self, recovery: R) -> Result<()> {
        if self.session.is_some() {
            return Err(ControlError::new(ErrorCode::AlreadyConnected));
        }
        validate_endpoint_binding(&self.transport, &recovery)?;
        self.recovery = recovery;
        Ok(())
    }
    pub fn connect(&mut self, manifest: &Value) -> Result<ControlView> {
        if self.session.is_some() {
            return Err(ControlError::new(ErrorCode::AlreadyConnected));
        }
        validate_endpoint_binding(&self.transport, &self.recovery)?;
        let raw = self.transport.connect(manifest)?;
        let session = match contract::normalize_session(
            &raw,
            contract::UI_CONTROL_PROTOCOL_VERSION,
            (self.clock)(),
        ) {
            Ok(session) => session,
            Err(error) => {
                let _ = self.transport.close(&raw);
                return Err(error);
            }
        };
        if session.identity_id != self.recovery.scope().identity_id
            || session.protocol_version != self.recovery.scope().protocol_version
        {
            let _ = self.transport.close(&encoded(&session)?);
            return Err(ControlError::new(ErrorCode::Storage));
        }
        self.ledger.set_identity(&session.identity_id)?;
        let load = self
            .recovery
            .load()
            .and_then(|records| self.ledger.restore(records));
        if let Err(error) = load {
            let _ = self.transport.close(&encoded(&session)?);
            self.storage_error = true;
            return Err(error);
        }
        self.session = Some(session);
        self.snapshot = None;
        self.last_snapshot = None;
        self.session_schedule.succeeded();
        self.view()
    }
    pub fn view(&mut self) -> Result<ControlView> {
        if self
            .session
            .as_ref()
            .is_some_and(|session| session.expires_at <= (self.clock)())
        {
            self.invalidate();
        }
        Ok(ControlView {
            session: self.session.clone(),
            snapshot: self.snapshot.clone(),
            stale: self.snapshot.is_none(),
            pending: self.ledger.pending_views(),
            completed: self.ledger.completed_views(),
            storage_error: self.storage_error,
        })
    }
    fn invalidate(&mut self) {
        self.session = None;
        self.snapshot = None;
        self.last_snapshot = None;
    }
    fn session_for(&mut self, permission: Permission) -> Result<Session> {
        if self
            .session
            .as_ref()
            .is_some_and(|session| session.expires_at <= (self.clock)())
        {
            self.invalidate();
            return Err(ControlError::new(ErrorCode::SessionExpired).not_dispatched());
        }
        let session = self
            .session
            .as_ref()
            .ok_or_else(|| ControlError::new(ErrorCode::NotConnected).not_dispatched())?;
        if session.revoked || !session.authenticated || !session.permissions.contains(&permission) {
            return Err(ControlError::new(ErrorCode::PermissionDenied).not_dispatched());
        }
        Ok(session.clone())
    }
    fn error_authority(&mut self, error: &ControlError) {
        if matches!(
            error.code,
            ErrorCode::SessionExpired
                | ErrorCode::SessionRevoked
                | ErrorCode::SessionIdentityChanged
                | ErrorCode::StalePermissionRevision
                | ErrorCode::ProtocolMismatch
                | ErrorCode::PermissionDenied
        ) {
            self.invalidate();
        }
    }
    pub fn refresh_session(&mut self) -> Result<ControlView> {
        let previous = self.session_for(Permission::Read)?;
        let result = (|| {
            let raw = self.transport.refresh_session(&encoded(&previous)?)?;
            let next = contract::normalize_session(
                &raw,
                contract::UI_CONTROL_PROTOCOL_VERSION,
                (self.clock)(),
            )?;
            if next.session_id != previous.session_id {
                return Err(ControlError::new(ErrorCode::SessionRevoked));
            }
            if next.identity_id != previous.identity_id {
                return Err(ControlError::new(ErrorCode::SessionIdentityChanged));
            }
            if next.connection_generation < previous.connection_generation {
                return Err(ControlError::new(ErrorCode::StaleGeneration));
            }
            if next.permission_revision < previous.permission_revision
                || next.permission_revision == previous.permission_revision
                    && next.permissions != previous.permissions
            {
                return Err(ControlError::new(ErrorCode::StalePermissionRevision));
            }
            if next.connection_generation != previous.connection_generation {
                self.snapshot = None;
            }
            self.session = Some(next);
            Ok(())
        })();
        match result {
            Ok(()) => {
                self.session_schedule.succeeded();
                self.view()
            }
            Err(error) => {
                self.session_schedule.failed();
                if !matches!(error.code, ErrorCode::Transport | ErrorCode::Aborted) {
                    self.invalidate();
                }
                Err(error)
            }
        }
    }
    pub fn refresh_view(&mut self) -> Result<ControlView> {
        let session = self.session_for(Permission::Read)?;
        let result = self
            .transport
            .read_snapshot(&encoded(&session)?)
            .and_then(|raw| {
                let normalized = normalize_snapshot(&raw, &session)?;
                validate_snapshot_transition(self.last_snapshot.as_ref(), normalized)
            });
        match result {
            Ok(snapshot) => {
                self.snapshot = Some(snapshot.clone());
                self.last_snapshot = Some(snapshot);
                self.view()
            }
            Err(error) => {
                self.snapshot = None;
                self.error_authority(&error);
                Err(error)
            }
        }
    }
    pub fn next_session_refresh_ms(&self) -> Option<u64> {
        self.session.as_ref().map(|session| {
            self.session_schedule
                .delay_ms(session.expires_at, (self.clock)())
        })
    }
    pub fn close(&mut self) -> Result<()> {
        let session = self.session.take();
        self.snapshot = None;
        self.last_snapshot = None;
        session.map_or(Ok(()), |session| self.transport.close(&encoded(&session)?))
    }
    pub fn revoke(&mut self) -> Result<()> {
        let session = self.session.take();
        self.snapshot = None;
        self.last_snapshot = None;
        session.map_or(Ok(()), |session| self.transport.revoke(&encoded(&session)?))
    }
}

#[cfg(test)]
#[path = "client_tests.rs"]
mod tests;
