//! An executable target-host pressure matrix contract. The harness never
//! substitutes synthetic samples for a real NeuronRuntime/inference host.

use codex_hepta_types::Digest32;

pub const SCOPE_MATRIX_V1: [usize; 4] = [64, 256, 1_024, 4_096];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ScopeMatrixEvidenceClassV1 {
    SourceFixture,
    TargetHost,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LatencyDistributionV1 {
    pub p50_micros: u64,
    pub p95_micros: u64,
    pub p99_micros: u64,
}

impl LatencyDistributionV1 {
    fn valid(self) -> bool {
        self.p50_micros <= self.p95_micros
            && self.p95_micros <= self.p99_micros
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScopeMatrixSampleV1 {
    pub scope_count: usize,
    pub evidence_class: ScopeMatrixEvidenceClassV1,
    pub source_head_digest: Digest32,
    pub runtime_manifest_digest: Digest32,
    pub target_host_digest: Option<Digest32>,
    pub independent_observer_digest: Option<Digest32>,
    pub total_requests: u64,
    pub terminal_requests: u64,
    pub indeterminate_requests: u64,
    pub model_latency: LatencyDistributionV1,
    pub end_to_end_latency: LatencyDistributionV1,
    pub journal_fsync_latency: LatencyDistributionV1,
    pub witness_fsync_latency: LatencyDistributionV1,
    pub queue_age_latency: LatencyDistributionV1,
    pub bytes_written: u64,
    pub journal_bytes: u64,
    pub communication_bytes: u64,
    pub peak_resident_bytes: u64,
    pub maximum_queue_depth: u64,
    pub replay_frames_per_second: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ScopeMatrixErrorV1 {
    InvalidSample,
    MissingHostEvidence,
    WrongScopeCount,
}

impl ScopeMatrixSampleV1 {
    pub fn validate(&self) -> Result<(), ScopeMatrixErrorV1> {
        if !SCOPE_MATRIX_V1.contains(&self.scope_count)
            || self.source_head_digest.is_zero()
            || self.runtime_manifest_digest.is_zero()
            || self.total_requests < self.scope_count as u64
            || self.terminal_requests + self.indeterminate_requests > self.total_requests
            || !self.model_latency.valid()
            || !self.end_to_end_latency.valid()
            || !self.journal_fsync_latency.valid()
            || !self.witness_fsync_latency.valid()
            || !self.queue_age_latency.valid()
            || self.peak_resident_bytes == 0
            || self.replay_frames_per_second == 0
        {
            return Err(ScopeMatrixErrorV1::InvalidSample);
        }
        if self.evidence_class == ScopeMatrixEvidenceClassV1::TargetHost {
            match (self.target_host_digest, self.independent_observer_digest) {
                (Some(host), Some(observer))
                    if !host.is_zero() && !observer.is_zero() && host != observer => {}
                _ => return Err(ScopeMatrixErrorV1::MissingHostEvidence),
            }
        }
        Ok(())
    }
}

/// The actual target-host runner is injected by Agentd/acceptance harness.
/// Its sample must bind the exact host, runtime manifest and source head.
pub trait ScopeMatrixTargetV1 {
    type Error;

    fn run_scope_count(&mut self, count: usize) -> Result<ScopeMatrixSampleV1, Self::Error>;
}

#[derive(Debug)]
pub enum ScopeMatrixRunErrorV1<E> {
    Host(E),
    Contract(ScopeMatrixErrorV1),
}

pub fn run_scope_matrix_v1<R: ScopeMatrixTargetV1>(
    target: &mut R,
) -> Result<Vec<ScopeMatrixSampleV1>, ScopeMatrixRunErrorV1<R::Error>> {
    let mut samples = Vec::with_capacity(SCOPE_MATRIX_V1.len());
    for count in SCOPE_MATRIX_V1 {
        let observation = target
            .run_scope_count(count)
            .map_err(ScopeMatrixRunErrorV1::Host)?;
        observation
            .validate()
            .map_err(ScopeMatrixRunErrorV1::Contract)?;
        if observation.scope_count != count {
            return Err(ScopeMatrixRunErrorV1::Contract(
                ScopeMatrixErrorV1::WrongScopeCount,
            ));
        }
        samples.push(observation);
    }
    Ok(samples)
}

#[cfg(test)]
#[path = "scope_matrix_tests.rs"]
mod tests;
