//! Local operator consent binding. This never grants runtime authority.
use crate::error::{ControlError, ErrorCode};
use crate::projection::{RuntimeSnapshot, Session};
use serde::Serialize;

pub struct ConfirmationView<'a> {
    pub session: Option<&'a Session>,
    pub snapshot: Option<&'a RuntimeSnapshot>,
    pub connected: bool,
    pub authenticated: bool,
    pub stale: bool,
}

pub struct ConfirmationInput<'a> {
    pub target_id: &'a str,
    pub action: &'a str,
    pub reason: &'a str,
    pub operation_id: &'a str,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Confirmation {
    session_id: String,
    identity_id: String,
    permission_revision: u64,
    connection_generation: u64,
    generation: u64,
    displayed_revision: u64,
    snapshot_digest: String,
    target_id: String,
    target_revision: u64,
    target_digest: String,
    action: String,
    reason: String,
    operation_id: String,
}

pub fn capture_confirmation(
    view: &ConfirmationView<'_>,
    input: &ConfirmationInput<'_>,
) -> Result<Confirmation, ControlError> {
    let unavailable = || ControlError::unsent(ErrorCode::StaleRevision);
    if !view.connected || !view.authenticated || view.stale {
        return Err(unavailable());
    }
    let session = view.session.ok_or_else(unavailable)?;
    let snapshot = view.snapshot.ok_or_else(unavailable)?;
    let target = snapshot
        .modules()
        .iter()
        .find(|module| module.id() == input.target_id)
        .ok_or_else(unavailable)?;
    Ok(Confirmation {
        session_id: session.session_id().to_owned(),
        identity_id: session.identity_id().to_owned(),
        permission_revision: session.permission_revision(),
        connection_generation: session.connection_generation(),
        generation: snapshot.generation(),
        displayed_revision: snapshot.revision(),
        snapshot_digest: snapshot.semantic_digest().to_owned(),
        target_id: input.target_id.to_owned(),
        target_revision: target.revision(),
        target_digest: target.semantic_digest().to_owned(),
        action: input.action.to_owned(),
        reason: input.reason.to_owned(),
        operation_id: input.operation_id.to_owned(),
    })
}

pub fn assert_confirmation(
    context: Option<&Confirmation>,
    view: &ConfirmationView<'_>,
    input: &ConfirmationInput<'_>,
) -> Result<(), ControlError> {
    let now = capture_confirmation(view, input)?;
    if context != Some(&now) {
        return Err(ControlError::unsent(ErrorCode::StaleRevision).retryable(true));
    }
    Ok(())
}

pub fn retained_target(previous: &str, ids: &[String], initialized: bool) -> String {
    if ids.iter().any(|id| id == previous) {
        return previous.to_owned();
    }
    if initialized {
        return String::new();
    }
    ids.first().cloned().unwrap_or_default()
}

#[cfg(test)]
#[path = "../tests/unit/confirmation_tests.rs"]
mod tests;
