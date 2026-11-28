use codex_hepta_supervisor::SupervisorError;

#[derive(Clone, Copy)]
pub(super) enum StoppedWaitRequest {
    Observe,
    KillCurrentFence,
}

// SupervisordClient currently flattens the structured server rejection into
// Invalid. Match the complete current rejection, not a substring: only this
// error is emitted before the daemon changes its revision or invokes Kill.
// Different wording, indeterminate outcomes, and transport errors fail closed.
pub(super) fn is_stale_cleanup_kill(error: &SupervisorError) -> bool {
    matches!(
        error,
        SupervisorError::Invalid(message)
            if message == "supervisord rejected request (stale_control_fence): selected Agent changed; refresh before retry"
    )
}

#[cfg(test)]
#[path = "supervisord_cleanup_tests.rs"]
mod tests;
