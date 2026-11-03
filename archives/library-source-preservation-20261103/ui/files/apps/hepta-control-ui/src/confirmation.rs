use serde::{Deserialize, Serialize};

use crate::canonical::{assert_canonical_text, assert_stable_identifier};
use crate::contract::{Action, Session};
use crate::error::{ControlError, ErrorCode, Result};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ConfirmationInput {
    pub operation_id: String,
    pub action: Action,
    pub target_id: String,
    pub reason: String,
}

/// Operator consent bound to the current display; it does not grant authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ConfirmationContext {
    pub session_id: String,
    pub identity_id: String,
    pub permission_revision: u64,
    pub connection_generation: u64,
    pub generation: u64,
    pub displayed_revision: u64,
    pub snapshot_digest: String,
    pub target_id: String,
    pub target_revision: u64,
    pub target_digest: String,
    pub action: Action,
    pub reason: String,
    pub operation_id: String,
}

pub fn capture_confirmation(
    session: Option<&Session>,
    snapshot: Option<&crate::projection::Snapshot>,
    input: &ConfirmationInput,
) -> Result<ConfirmationContext> {
    let stale = || ControlError::new(ErrorCode::StaleRevision).not_dispatched();
    let session = session
        .filter(|session| session.authenticated && !session.revoked)
        .ok_or_else(stale)?;
    let snapshot = snapshot.ok_or_else(stale)?;
    if snapshot.session_id != session.session_id
        || snapshot.connection_generation != session.connection_generation
    {
        return Err(stale());
    }
    let target = snapshot
        .modules
        .iter()
        .find(|module| module.id == input.target_id)
        .ok_or_else(stale)?;
    assert_stable_identifier(&input.operation_id)?;
    assert_canonical_text(&input.reason, /*max_bytes*/ 1024)?;
    Ok(ConfirmationContext {
        session_id: session.session_id.clone(),
        identity_id: session.identity_id.clone(),
        permission_revision: session.permission_revision,
        connection_generation: session.connection_generation,
        generation: snapshot.generation,
        displayed_revision: snapshot.revision,
        snapshot_digest: snapshot.semantic_digest.clone(),
        target_id: input.target_id.clone(),
        target_revision: target.revision,
        target_digest: target.semantic_digest.clone(),
        action: input.action,
        reason: input.reason.clone(),
        operation_id: input.operation_id.clone(),
    })
}

pub fn assert_confirmation(
    context: &ConfirmationContext,
    session: Option<&Session>,
    snapshot: Option<&crate::projection::Snapshot>,
    input: &ConfirmationInput,
) -> Result<()> {
    if *context != capture_confirmation(session, snapshot, input)? {
        return Err(ControlError::new(ErrorCode::StaleRevision).not_dispatched());
    }
    Ok(())
}

pub fn retained_target<'a>(previous: &'a str, ids: &'a [String], initialized: bool) -> &'a str {
    if ids.iter().any(|id| id == previous) {
        previous
    } else if initialized {
        ""
    } else {
        ids.first().map_or("", String::as_str)
    }
}
