//! Per-publication bounded evidence; never an authority or recovery witness.
use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;

use crate::CognitiveCheckpointCommand;
use crate::CognitiveCheckpointReason;
use crate::CognitiveCheckpointRequest;

/// Fixed local phase of one original Current acknowledgement.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum CheckpointStage {
    #[default]
    Start,
    WaitingCoordinator,
    Serialize,
    TransportExchange,
    ReserveStream,
    WritePrefix,
    WriteBody,
    ReadPrefix,
    ReadBody,
    ValidateResponse,
    ValidateHead,
    ValidateTransition,
    Finished,
}
/// Static failure classification; no server text or authority payloads.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CheckpointFailureCause {
    OuterTimeout,
    PublisherUnavailable,
    PublisherRefused,
    CutMismatch,
    Timeout,
    Refused(Option<CognitiveCheckpointReason>),
    Unknown(Option<CognitiveCheckpointReason>),
    Encode,
    Size,
    Decode,
    Identity,
    MissingFields,
    HeadMismatch,
    TransitionMismatch,
    Io(Option<i32>),
    PeerUnavailable,
    SlotBusy,
    SlotEmpty,
    Deadline,
    Late,
    Cancelled,
}
/// A copied first failure from one attempt. Missing data never permits retry.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CheckpointFailure {
    pub stage: CheckpointStage,
    pub command: Option<CognitiveCheckpointCommand>,
    pub request_sequence: Option<u64>,
    pub cause: Option<CheckpointFailureCause>,
    pub elapsed_ns: Option<u64>,
    pub incomplete: bool,
}
/// Optional, nonblocking diagnostics shared only by one publication future.
/// Recording failures cannot change its result, deadline, transport or fence.
pub struct CheckpointDiagnostics {
    state: Mutex<CheckpointFailure>,
    first: OnceLock<CheckpointFailure>,
    claimed: AtomicBool,
    incomplete: AtomicBool,
    started: Instant,
}
impl Default for CheckpointDiagnostics {
    fn default() -> Self {
        Self {
            state: Mutex::new(CheckpointFailure::default()),
            first: OnceLock::new(),
            claimed: AtomicBool::new(false),
            incomplete: AtomicBool::new(false),
            started: Instant::now(),
        }
    }
}
impl CheckpointDiagnostics {
    pub fn stage(&self, stage: CheckpointStage) {
        if let Ok(mut state) = self.state.try_lock() {
            state.stage = stage;
        } else {
            self.incomplete.store(true, Ordering::Release);
        }
    }
    pub fn request(&self, request: &CognitiveCheckpointRequest) {
        if let Ok(mut state) = self.state.try_lock() {
            state.command = Some(request.command);
            state.request_sequence = request
                .request_id
                .get(16..)
                .and_then(|value| u64::from_str_radix(value, 16).ok());
        } else {
            self.incomplete.store(true, Ordering::Release);
        }
    }
    pub fn fail(&self, cause: CheckpointFailureCause) {
        if self
            .claimed
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return;
        }
        let mut failure = match self.state.try_lock() {
            Ok(state) => *state,
            Err(_) => CheckpointFailure {
                incomplete: true,
                ..Default::default()
            },
        };
        failure.cause = Some(cause);
        failure.elapsed_ns = u64::try_from(self.started.elapsed().as_nanos()).ok();
        failure.incomplete |= self.incomplete.load(Ordering::Acquire);
        let _ = self.first.set(failure);
    }
    pub fn first(&self) -> Option<CheckpointFailure> {
        self.first.get().copied()
    }
}

#[cfg(test)]
#[path = "cognitive_checkpoint_diagnostic_tests.rs"]
mod tests;
