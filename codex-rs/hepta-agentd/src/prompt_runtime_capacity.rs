//! Reserve a complete bounded terminal observation before accepting dispatch.
use super::*;

// Each u32 token position needs at most 10 digits and one separator. The fixed
// part bounds all digest arrays, keys and maximum escaped identity/reason fields.
const TERMINAL_BYTES: u64 =
    codex_hepta_types::MAX_PROMPT_TOKEN_POSITIONS_V1 as u64 * 11 + 16 * 1024;

pub(super) fn reserved_bytes(state: &PromptRuntimeState) -> Result<u64, AgentdPromptRuntimeError> {
    let mut remaining = 0_u64;
    for attempt in state.dispatch_records.keys() {
        let current = match state.terminal_records.get(attempt) {
            Some(record) if record.outcome != PromptRuntimeTerminalOutcomeV1::Indeterminate => {
                continue;
            }
            Some(record) => {
                serde_json::to_vec(&stored_terminal(record))
                    .map_err(|_| AgentdPromptRuntimeError::Unavailable)?
                    .len() as u64
                    + 1
            }
            None => 0,
        };
        remaining = remaining
            .checked_add(TERMINAL_BYTES.saturating_sub(current))
            .ok_or(AgentdPromptRuntimeError::CapacityExceeded)?;
    }
    Ok(remaining)
}

pub(super) fn admit(
    state: &PromptRuntimeState,
    bytes: usize,
    limit: u64,
) -> Result<(), AgentdPromptRuntimeError> {
    if (bytes as u64)
        .checked_add(reserved_bytes(state)?)
        .is_none_or(|total| total > limit)
    {
        return Err(AgentdPromptRuntimeError::CapacityExceeded);
    }
    Ok(())
}
