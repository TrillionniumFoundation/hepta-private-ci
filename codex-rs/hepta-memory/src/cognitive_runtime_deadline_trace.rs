use std::fmt;
use std::sync::Arc;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;

use super::MAX_FEDERATION_SOURCES_PER_AGENT;

// Each scope owns one retrieval's observations; the key does not own shared data.
tokio::task_local! {
    pub(crate) static CURRENT: Arc<DeadlineTrace>;
}

#[derive(Default)]
pub(crate) struct DeadlineTrace {
    stages: [AtomicU8; MAX_FEDERATION_SOURCES_PER_AGENT],
}

#[repr(u8)]
pub(super) enum Stage {
    BeforeExecute = 1,
    BeforeControlWait = 2,
    PreAuthorityWait = 3,
    RequestWait = 4,
    PostAuthorityWait = 5,
}

pub(super) struct AttemptTrace {
    trace: Arc<DeadlineTrace>,
    index: usize,
}

pub(super) fn attempt(index: usize) -> Option<AttemptTrace> {
    CURRENT
        .try_with(|trace| AttemptTrace {
            trace: Arc::clone(trace),
            index,
        })
        .ok()
}

impl AttemptTrace {
    pub(super) fn record(&self, stage: Stage) {
        if let Some(slot) = self.trace.stages.get(self.index) {
            slot.store(stage as u8, Ordering::Relaxed);
        }
    }
}

impl fmt::Debug for DeadlineTrace {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let mut first = "unavailable";
        let mut last = "unavailable";
        let mut recorded = 0;
        // Enumeration order is not completion order or evidence that I/O was polled.
        for slot in &self.stages {
            let stage = match slot.load(Ordering::Relaxed) {
                1 => "before_execute",
                2 => "before_control_wait",
                3 => "pre_authority_wait",
                4 => "request_wait",
                5 => "post_authority_wait",
                _ => continue,
            };
            if recorded == 0 {
                first = stage;
            }
            last = stage;
            recorded += 1;
        }
        formatter
            .debug_struct("PeerDeadlineTrace")
            .field("order", &"selected_reader")
            .field("recorded", &recorded)
            .field("first", &first)
            .field("last", &last)
            .finish()
    }
}
