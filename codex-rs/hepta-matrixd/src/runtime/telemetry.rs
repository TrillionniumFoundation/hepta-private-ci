//! Identity-free numeric observations. These counters are never scheduling state.
use std::sync::Mutex;
use std::time::Instant;

use serde::Serialize;
use tokio::sync::Semaphore;
use tokio::sync::SemaphorePermit;

use super::MatrixRuntimeError;

#[derive(Clone, Copy)]
pub(super) enum GateKind {
    Admission,
    Projection,
}

#[derive(Clone, Default, Serialize)]
struct GateMeasurements {
    acquisitions: u64,
    wait_ns_sum: u64,
    wait_ns_max: u64,
    hold_ns_sum: u64,
    hold_ns_max: u64,
}

#[derive(Clone, Default, Serialize)]
struct Measurements {
    admission_gate: GateMeasurements,
    projection_gate: GateMeasurements,
    ignored_event_type: u64,
    ignored_malformed_content: u64,
    ignored_message_type: u64,
    ignored_empty_body: u64,
    ignored_relation: u64,
}

impl Measurements {
    fn gate(&mut self, kind: GateKind) -> &mut GateMeasurements {
        match kind {
            GateKind::Admission => &mut self.admission_gate,
            GateKind::Projection => &mut self.projection_gate,
        }
    }
}

#[derive(Default)]
pub(super) struct RuntimeTelemetry {
    values: Mutex<Measurements>,
}

pub(super) struct OperationGuard<'a> {
    _permit: SemaphorePermit<'a>,
    telemetry: &'a RuntimeTelemetry,
    kind: GateKind,
    acquired: Instant,
}

impl RuntimeTelemetry {
    pub(super) async fn acquire<'a>(
        &'a self,
        semaphore: &'a Semaphore,
        kind: GateKind,
    ) -> Result<OperationGuard<'a>, MatrixRuntimeError> {
        let started = Instant::now();
        let permit = semaphore.acquire().await.map_err(|_| {
            MatrixRuntimeError::Protocol("Matrix runtime operation gate closed".to_string())
        })?;
        let wait = elapsed_ns(started);
        let mut values = self
            .values
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let gate = values.gate(kind);
        gate.acquisitions = gate.acquisitions.saturating_add(1);
        gate.wait_ns_sum = gate.wait_ns_sum.saturating_add(wait);
        gate.wait_ns_max = gate.wait_ns_max.max(wait);
        drop(values);
        Ok(OperationGuard {
            _permit: permit,
            telemetry: self,
            kind,
            acquired: Instant::now(),
        })
    }

    pub(super) fn ignored(&self, reason: super::input::InputRejection) {
        use super::input::InputRejection;
        let mut values = self
            .values
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let count = match reason {
            InputRejection::EventType => &mut values.ignored_event_type,
            InputRejection::Malformed => &mut values.ignored_malformed_content,
            InputRejection::MessageType => &mut values.ignored_message_type,
            InputRejection::EmptyBody => &mut values.ignored_empty_body,
            InputRejection::Relation => &mut values.ignored_relation,
        };
        *count = count.saturating_add(1);
    }

    pub(super) fn snapshot(&self) -> serde_json::Value {
        let values = self
            .values
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        serde_json::json!({
            "schema": "hepta.channel-matrix-ingress-metrics.v1",
            "scope": "process_lifetime_completed_acquisitions_not_latency_percentiles",
            "measurements": &*values,
            "authority_granted": false
        })
    }
}

impl Drop for OperationGuard<'_> {
    fn drop(&mut self) {
        let hold = elapsed_ns(self.acquired);
        let mut values = self
            .telemetry
            .values
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let gate = values.gate(self.kind);
        gate.hold_ns_sum = gate.hold_ns_sum.saturating_add(hold);
        gate.hold_ns_max = gate.hold_ns_max.max(hold);
    }
}

fn elapsed_ns(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX)
}
