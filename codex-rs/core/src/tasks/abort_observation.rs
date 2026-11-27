/// Last entered stage of the task-owned abort cleanup.
///
/// This is diagnostic state only. No branch, admission decision, retry, or
/// recovery authority depends on it. A cancelled terminalizer retains the value
/// with its existing handoff witness; a snapshot does not prove that the stage
/// completed or identify which nested operation was waiting.
#[derive(Clone, Copy, Debug)]
pub(super) enum TaskAbortStage {
    NotEntered,
    CancelledAuthority,
    AlreadyCancelled,
    CodeModeInterrupt,
    TaskNotification,
    TaskHandleQuiescence,
    TaskAbortHook,
    RolloutFlush,
    InterruptedMarkerRecord,
    InterruptedMarkerFlush,
    StartedAtRead,
    TimingProfile,
    TerminalEventPersistence,
    GuardianCleanup,
    Complete,
}
