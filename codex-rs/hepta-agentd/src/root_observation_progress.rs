//! Non-authorizing progress of the original feed and its startup caller.
//! Events reuse existing request samples plus one optional wake sample, which
//! never participates in any authority decision or trusted-clock formula.
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(crate) enum RefreshPhase {
    #[default]
    Unstarted,
    Sleeping,
    Awake,
    WaitingSerial,
    RequestInFlight,
    ReplyReceived,
    Accepting,
    Accepted,
    SynchronizingConsumers,
    Validated,
}
pub(crate) enum RefreshEvent {
    Sleeping,
    Woke { boottime_ns: Option<u64> },
    WaitingSerial,
    Started(u64),
    Replied(u64),
    Accepting,
    Accepted,
    SynchronizingConsumers,
    Validated,
}
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(crate) enum AttachStage {
    #[default]
    Unstarted,
    Connected,
    OpeningFrontiers,
    ActivatingOwners,
    ReadingCurrent,
    OpeningWriter,
    InstallingWriter,
    Attached,
}
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(crate) struct ObservationProgress {
    pub refresh_phase: RefreshPhase,
    pub request_sequence: u64,
    pub wake_ns: Option<u64>,
    pub request_started_ns: Option<u64>,
    pub reply_ended_ns: Option<u64>,
    pub previous_request_started_ns: Option<u64>,
    pub previous_reply_ended_ns: Option<u64>,
    pub accepted_request_started_ns: Option<u64>,
    pub validated_request_started_ns: Option<u64>,
    pub attach_stage: AttachStage,
    pub incomplete: bool,
}
#[derive(Default)]
pub(super) struct ProgressCell {
    value: Mutex<ObservationProgress>,
    lost_event: AtomicBool,
}
impl ProgressCell {
    fn update(&self, update: impl FnOnce(&mut ObservationProgress)) {
        if let Ok(mut value) = self.value.try_lock() {
            update(&mut value);
        } else {
            self.lost_event.store(true, Ordering::Release);
        }
    }
    pub(super) fn refresh(&self, event: RefreshEvent) {
        self.update(|value| {
            value.refresh_phase = match event {
                RefreshEvent::Sleeping => RefreshPhase::Sleeping,
                RefreshEvent::Woke { boottime_ns } => {
                    value.wake_ns = boottime_ns;
                    RefreshPhase::Awake
                }
                RefreshEvent::WaitingSerial => RefreshPhase::WaitingSerial,
                RefreshEvent::Started(started) => {
                    value.request_sequence = value.request_sequence.saturating_add(1);
                    value.previous_request_started_ns = value.request_started_ns;
                    value.previous_reply_ended_ns = value.reply_ended_ns;
                    value.request_started_ns = Some(started);
                    value.reply_ended_ns = None;
                    RefreshPhase::RequestInFlight
                }
                RefreshEvent::Replied(ended) => {
                    value.reply_ended_ns = Some(ended);
                    RefreshPhase::ReplyReceived
                }
                RefreshEvent::Accepting => RefreshPhase::Accepting,
                RefreshEvent::Accepted => {
                    value.accepted_request_started_ns = value.request_started_ns;
                    RefreshPhase::Accepted
                }
                RefreshEvent::SynchronizingConsumers => RefreshPhase::SynchronizingConsumers,
                RefreshEvent::Validated => {
                    value.validated_request_started_ns = value.request_started_ns;
                    RefreshPhase::Validated
                }
            };
        });
    }
    pub(super) fn attach(&self, stage: AttachStage) {
        self.update(|value| value.attach_stage = stage);
    }
    pub(super) fn snapshot(&self) -> Option<ObservationProgress> {
        let mut value = *self.value.try_lock().ok()?;
        if value == ObservationProgress::default() {
            return None;
        }
        value.incomplete = self.lost_event.load(Ordering::Acquire);
        Some(value)
    }
}

#[cfg(test)]
#[path = "root_observation_progress_tests.rs"]
mod tests;
