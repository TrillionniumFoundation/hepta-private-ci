//! A failed acknowledgment after signed publication starts is an ambiguous
//! outcome, even when no process action has yet been confirmed. Keep the
//! underlying bounded diagnostic without issuing a success or rejection receipt.

use codex_hepta_contracts::AgentId;

use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::runtime::AgentSlot;
use crate::runtime::bounded_message;

pub(super) fn indeterminate<P>(
    agent_id: &AgentId,
    slot: &mut AgentSlot<P>,
    error: &SupervisorError,
) -> SupervisorError {
    let generation = slot
        .runtime
        .as_ref()
        .map(|runtime| runtime.generation)
        .unwrap_or(/*default*/ 0);
    slot.event(
        generation,
        SupervisorEventKind::DriverFault(bounded_message(error.to_string())),
    );
    SupervisorError::SignedMutationIndeterminate(agent_id.clone())
}
