//! Bounded diagnostics for a lost exact health observation.
//!
//! Only local identifiers, elapsed time and fixed error categories are emitted.
//! The observer still publishes every failed probe as unhealthy immediately.
//! It never waits for stderr or queue capacity. Lazy initialization still has
//! channel/thread creation overhead and is not a zero-cost timing guarantee.

use std::io::Write;
use std::sync::OnceLock;
use std::sync::mpsc::SyncSender;
use std::sync::mpsc::sync_channel;
use std::time::Duration;

use codex_hepta_contracts::AgentId;

use crate::ProcessDriverError;

use super::HealthProbeObservation;

const MAX_HEALTH_LOSS_REPORTS: u8 = 8;
const HEALTH_REPORT_QUEUE_CAPACITY: usize = 32;

static HEALTH_REPORTER: OnceLock<Option<SyncSender<HealthProbeReport>>> = OnceLock::new();

#[derive(Debug)]
pub(super) enum HealthProbeFailureKind {
    Io(std::io::ErrorKind),
    Json(serde_json::error::Category),
}

pub(super) struct HealthProbeFailure {
    pub(super) kind: HealthProbeFailureKind,
    error: ProcessDriverError,
}

impl std::fmt::Debug for HealthProbeFailure {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        // Existing private-query callers retain their original error context.
        // Runtime diagnostics below only read the fixed classification.
        std::fmt::Debug::fmt(&self.error, formatter)
    }
}

impl From<std::io::Error> for HealthProbeFailure {
    fn from(error: std::io::Error) -> Self {
        Self {
            kind: HealthProbeFailureKind::Io(error.kind()),
            error: error.into(),
        }
    }
}

impl From<serde_json::Error> for HealthProbeFailure {
    fn from(error: serde_json::Error) -> Self {
        Self {
            kind: HealthProbeFailureKind::Json(error.classify()),
            error: error.into(),
        }
    }
}

#[derive(Default)]
pub(super) struct HealthProbeDiagnostics {
    loss_reports: u8,
}

enum HealthProbeOutcome {
    Observation { exact_identity: bool, ready: bool },
    Io(std::io::ErrorKind),
    Json(serde_json::error::Category),
}

pub(super) struct HealthProbeReport {
    agent_id: AgentId,
    request_id: u64,
    elapsed: Duration,
    report: u8,
    outcome: HealthProbeOutcome,
}

fn start_health_reporter() -> Option<SyncSender<HealthProbeReport>> {
    let (sender, receiver) = sync_channel::<HealthProbeReport>(HEALTH_REPORT_QUEUE_CAPACITY);
    std::thread::Builder::new()
        .name("hepta-health-diagnostics".to_string())
        .spawn(move || {
            for report in receiver {
                // Only this background worker can wait on stderr. If output
                // stalls, producers drop reports when the bounded queue fills.
                let mut stderr = std::io::stderr().lock();
                let _ = report.write_to(&mut stderr);
            }
        })
        .ok()
        .map(|_worker| sender)
}

pub(super) fn try_enqueue_report(
    sender: Option<&SyncSender<HealthProbeReport>>,
    report: HealthProbeReport,
) {
    if let Some(sender) = sender {
        // Full/disconnected queues are deliberately lossy. In particular,
        // never fall back to a blocking send or to output on the caller.
        let _ = sender.try_send(report);
    }
}

impl HealthProbeDiagnostics {
    pub(super) fn record(
        &mut self,
        agent_id: &AgentId,
        request_id: u64,
        elapsed: Duration,
        observation: &Result<HealthProbeObservation, HealthProbeFailure>,
    ) {
        self.record_with(agent_id, request_id, elapsed, observation, |report| {
            // Initialization runs once, even when thread creation fails. Other
            // callers can wait for initialization, but never for output.
            let sender = HEALTH_REPORTER.get_or_init(start_health_reporter);
            try_enqueue_report(sender.as_ref(), report);
        });
    }

    pub(super) fn record_with(
        &mut self,
        agent_id: &AgentId,
        request_id: u64,
        elapsed: Duration,
        observation: &Result<HealthProbeObservation, HealthProbeFailure>,
        submit: impl FnOnce(HealthProbeReport),
    ) {
        if self.loss_reports >= MAX_HEALTH_LOSS_REPORTS {
            return;
        }
        // Count attempts, including dropped reports, so unavailable output
        // cannot cause unlimited submissions from one probe worker.
        self.loss_reports += 1;
        let outcome = match observation {
            Ok(value) => HealthProbeOutcome::Observation {
                exact_identity: value.exact_identity,
                ready: value.ready,
            },
            Err(failure) => match &failure.kind {
                HealthProbeFailureKind::Io(kind) => HealthProbeOutcome::Io(*kind),
                HealthProbeFailureKind::Json(category) => HealthProbeOutcome::Json(*category),
            },
        };
        submit(HealthProbeReport {
            agent_id: agent_id.clone(),
            request_id,
            elapsed,
            report: self.loss_reports,
            outcome,
        });
    }
}

impl HealthProbeReport {
    pub(super) fn write_to(&self, output: &mut impl Write) -> std::io::Result<()> {
        let agent_id = &self.agent_id;
        let request_id = self.request_id;
        let elapsed_us = self.elapsed.as_micros();
        let report = self.report;
        match &self.outcome {
            HealthProbeOutcome::Observation {
                exact_identity,
                ready,
            } => writeln!(
                output,
                "hepta-health agent={agent_id} request_id={request_id} elapsed_us={elapsed_us} exact_identity={exact_identity} ready={ready} report={report}/{MAX_HEALTH_LOSS_REPORTS}"
            ),
            HealthProbeOutcome::Io(kind) => writeln!(
                output,
                "hepta-health agent={agent_id} request_id={request_id} elapsed_us={elapsed_us} io_kind={kind:?} report={report}/{MAX_HEALTH_LOSS_REPORTS}"
            ),
            HealthProbeOutcome::Json(category) => writeln!(
                output,
                "hepta-health agent={agent_id} request_id={request_id} elapsed_us={elapsed_us} json_category={category:?} report={report}/{MAX_HEALTH_LOSS_REPORTS}"
            ),
        }
    }
}
