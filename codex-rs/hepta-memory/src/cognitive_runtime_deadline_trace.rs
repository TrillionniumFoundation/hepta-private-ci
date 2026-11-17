use std::fmt;
use std::sync::Arc;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;

use super::MAX_FEDERATION_SOURCES_PER_AGENT;

// Each scope owns one retrieval's observations; the key does not own shared data.
tokio::task_local! {
    pub(crate) static CURRENT: Arc<DeadlineTrace>;
    pub(super) static DISCOVERY: AttemptTrace;
}

#[derive(Default)]
pub(crate) struct DeadlineTrace {
    stages: [AtomicU8; MAX_FEDERATION_SOURCES_PER_AGENT],
    discovery_stages: [AtomicU8; MAX_FEDERATION_SOURCES_PER_AGENT],
}

#[repr(u8)]
pub(super) enum Stage {
    BeforeExecute = 1,
    BeforeControlWait = 2,
    PreAuthorityWait = 3,
    RequestWait = 4,
    PostAuthorityWait = 5,
}

#[repr(u8)]
pub(crate) enum DiscoveryStage {
    PathChecks = 1,
    ReadOnlyPool = 2,
    QueryOnly = 3,
    IntegrityChecks = 4,
    OwnerAndSchema = 5,
    CapabilityQuery = 6,
    CapabilityDecode = 7,
    Complete = 8,
}

#[derive(Clone)]
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

pub(crate) fn record_discovery(stage: DiscoveryStage) {
    let _ = DISCOVERY.try_with(|attempt| {
        if let Some(slot) = attempt.trace.discovery_stages.get(attempt.index) {
            slot.store(stage as u8, Ordering::Relaxed);
        }
    });
}

impl fmt::Debug for DeadlineTrace {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let stages = self
            .stages
            .each_ref()
            .map(|slot| match slot.load(Ordering::Relaxed) {
                1 => "before_execute",
                2 => "before_control_wait",
                3 => "pre_authority_wait",
                4 => "request_wait",
                5 => "post_authority_wait",
                _ => "unavailable",
            });
        let discovery_stages =
            self.discovery_stages
                .each_ref()
                .map(|slot| match slot.load(Ordering::Relaxed) {
                    1 => "path_checks",
                    2 => "read_only_pool",
                    3 => "query_only",
                    4 => "integrity_checks",
                    5 => "owner_and_schema",
                    6 => "capability_query",
                    7 => "capability_decode",
                    8 => "complete",
                    _ => "unavailable",
                });
        let mut first = "unavailable";
        let mut last = "unavailable";
        let mut recorded = 0;
        // Enumeration order is not completion order or evidence that I/O was polled.
        for stage in stages {
            if stage == "unavailable" {
                continue;
            }
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
            .field("stages", &stages)
            .field("last_discovery_phases", &discovery_stages)
            .finish()
    }
}
