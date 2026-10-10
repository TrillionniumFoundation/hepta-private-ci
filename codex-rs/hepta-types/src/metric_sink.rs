//! Cross-plane telemetry port. No metric, sink or timer grants runtime authority.

use crate::Digest32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PhaseMetricKindV1 {
    Admission,
    Microbatch,
    Cas,
    Signature,
    Cns,
    NeuronFeature,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PhaseMetricEventV1 {
    pub scope_digest: Digest32,
    pub operation_digest: Digest32,
    pub phase: PhaseMetricKindV1,
    pub latency_micros: u64,
    pub succeeded: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PhaseMetricSinkErrorV1 {
    Unavailable,
    Backpressure,
}

/// Evidence owns persistence. Cognitive/control owners only emit bounded
/// observations through this deliberately non-authorizing port.
pub trait PhaseMetricSinkV1: std::fmt::Debug + Send + Sync {
    fn record(&self, sample: PhaseMetricEventV1) -> Result<(), PhaseMetricSinkErrorV1>;
    /// Healthy means no observed loss, failed commit, or corrupt writer state.
    fn healthy(&self) -> bool;
    /// Explicit durable flush barrier for external qualification/export only.
    fn flush(&self) -> Result<(), PhaseMetricSinkErrorV1>;
}
