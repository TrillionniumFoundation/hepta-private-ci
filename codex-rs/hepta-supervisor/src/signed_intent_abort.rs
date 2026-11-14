//! Explicit local abort of a recovered signed intent.
//!
//! An abort only fences the old grant. It never infers a successful release
//! transition or replaces the signed recovery decision for a release journal.

use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;

use crate::SupervisorError;
use crate::lease::read_lease;
use crate::lease::read_matrix_lease;
use crate::release_transaction::read_release_transaction;
use crate::runtime::AgentSlot;
use crate::signed_intent::SignedIntentRecoveryAction;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_recovery_directive;
use crate::signed_intent::write_intent;

pub(crate) fn consume_abort_directive<P>(
    record: &AgentRecord,
    slot: &mut AgentSlot<P>,
    intent: &SignedSupervisorIntent,
) -> Result<bool, SupervisorError> {
    let Some(directive) = read_recovery_directive(record.layout.run_root())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
    else {
        return Ok(false);
    };
    // A previous directive remains as an audit record. It cannot authorize an
    // abort after any digest-bound field, including the status, has changed.
    if directive.intent_sha256 != intent.intent_sha256 {
        return Ok(false);
    }
    match directive.action {
        SignedIntentRecoveryAction::Abort => {}
    }

    if slot.runtime.is_some()
        || slot.matrix.runtime.is_some()
        || slot.release_change.is_some()
        || !matches!(
            record.lifecycle.lifecycle,
            AgentLifecycle::Stopped | AgentLifecycle::Failed
        )
    {
        return Ok(false);
    }
    // A failed adoption may leave no runtime handle while its lease still
    // represents an unobserved process. Both owners must be quiescent.
    if read_lease(record.layout.run_root())?.is_some()
        || read_matrix_lease(record.layout.matrixd_process_lease())?.is_some()
    {
        return Ok(false);
    }
    if read_release_transaction(record.layout.run_root())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        .is_some_and(|transaction| !transaction.phase.terminal())
    {
        return Ok(false);
    }

    let aborted = intent
        .with_status(SignedIntentStatus::Aborted)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    write_intent(record.layout.run_root(), &aborted)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    slot.signed_intent = Some(aborted);
    Ok(true)
}
