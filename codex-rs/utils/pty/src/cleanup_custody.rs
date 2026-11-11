use std::io;

/// A cleanup observation of the retained native owner. It does not supply the
/// command's exit status and never changes the result of an earlier operation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProcessCleanupObservation {
    NoTerminalObservation,
    OwnerTerminated { owner_exit_code: Option<i32> },
}

/// Keeps the original native owner alive independently of a take-once
/// terminator. Implementations must query that same retained object without
/// waiting, reopening it by PID, restarting work, or granting a new deadline.
pub trait ProcessCleanupCustody: Send + Sync {
    fn observe_cleanup(&self) -> io::Result<ProcessCleanupObservation>;
}
