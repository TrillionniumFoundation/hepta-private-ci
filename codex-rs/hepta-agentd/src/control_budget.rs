//! Host-local transport and preparation budgets. These are not authority leases.
use crate::AgentdMethod;
use std::time::Duration;

pub(crate) const FRAME_IO_TIMEOUT: Duration = Duration::from_secs(2);
pub(crate) const OWNER_INPUT_TIMEOUT: Duration = Duration::from_secs(5);
pub(crate) const OWNER_PREPARATION_TIMEOUT: Duration = Duration::from_secs(5);

pub(crate) fn operation_timeout(method: &AgentdMethod) -> Duration {
    match method {
        AgentdMethod::ObjectiveStart { .. } => {
            OWNER_INPUT_TIMEOUT + OWNER_PREPARATION_TIMEOUT + FRAME_IO_TIMEOUT
        }
        _ => FRAME_IO_TIMEOUT,
    }
}

pub(crate) fn response_timeout(method: &AgentdMethod) -> Duration {
    operation_timeout(method) + FRAME_IO_TIMEOUT
}
