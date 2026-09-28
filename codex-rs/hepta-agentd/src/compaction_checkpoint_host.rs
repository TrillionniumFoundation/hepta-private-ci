//! Named Agentd product host for durable cognitive compaction checkpoints.
//!
//! The host composes the existing production writer owner with the canonical
//! compact.engine coordinator. It does not mint memory-write or compaction
//! authority and it never accepts a raw candidate, proof or trust key.

use std::collections::VecDeque;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_compact_engine::{
    CompactionCoordinatorErrorV2, CompactionPublicationReceiptV2, DurableCompactionError,
    DurableCompactionOutboxEventV1, MemoryCheckpointCoordinatorV2,
    VerifiedCompactionPublicationV1, VerifiedCompactionSelectionV2,
};
use codex_hepta_types::Digest32;
use tokio::sync::Mutex;
use tokio::sync::MutexGuard;

pub use crate::error::CompactEngineCommitStateV1;
pub use crate::error::CompactEngineErrorCodeV1;
pub use crate::error::CompactEngineRecoveryActionV1;
use crate::{AgentdError, AgentdProductionWriterHost};

pub const AGENTD_COMPACTION_SCHEDULER_CALLER_V1: &str = "agentd.runtime.compaction-scheduler.v1";
const MAX_COMPACTION_HOST_TIMING_SAMPLES: usize = 512;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CompactEngineLatencySummaryV1 {
    pub p50_micros: u64,
    pub p95_micros: u64,
    pub p99_micros: u64,
    pub maximum_micros: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CompactEngineHostMetricsV1 {
    pub sample_count: u64,
    pub successful_operations: u64,
    pub failed_operations: u64,
    pub queue_wait: CompactEngineLatencySummaryV1,
    pub end_to_end: CompactEngineLatencySummaryV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct CompactEngineHostTimingSampleV1 {
    queue_wait_micros: u64,
    end_to_end_micros: u64,
    succeeded: bool,
}

#[derive(Clone)]
pub struct AgentdCompactionCheckpointHostV1 {
    production_writer: Arc<AgentdProductionWriterHost>,
    owner_id: String,
    coordinator: Arc<Mutex<MemoryCheckpointCoordinatorV2>>,
    timing_samples: Arc<Mutex<VecDeque<CompactEngineHostTimingSampleV1>>>,
}

impl AgentdCompactionCheckpointHostV1 {
    #[allow(clippy::too_many_arguments)]
    pub async fn open(
        production_writer: Arc<AgentdProductionWriterHost>,
        database_url: &str,
        pinned_root_key: [u8; 32],
        manifest_chain: &[Vec<u8>],
        lease_token: &str,
        lease_epoch: u64,
        lease_expires_at_unix_seconds: u64,
        now_unix_seconds: u64,
    ) -> Result<Self, AgentdError> {
        production_writer
            .writer()
            .verify_current_authority()
            .await?;
        let owner_id = production_writer
            .writer()
            .owner_agent_id()
            .as_str()
            .to_string();
        let coordinator = MemoryCheckpointCoordinatorV2::open_with_manifest_chain(
            database_url,
            &owner_id,
            pinned_root_key,
            manifest_chain,
            lease_token,
            lease_epoch,
            lease_expires_at_unix_seconds,
            now_unix_seconds,
        )
        .await
        .map_err(compaction_error)?;
        coordinator
            .verify_integrity(now_unix_seconds)
            .await
            .map_err(compaction_error)?;
        coordinator
            .reconcile_claims(now_unix_seconds)
            .await
            .map_err(compaction_error)?;
        production_writer
            .writer()
            .verify_current_authority()
            .await?;
        Ok(Self {
            production_writer,
            owner_id,
            coordinator: Arc::new(Mutex::new(coordinator)),
            timing_samples: Arc::new(Mutex::new(VecDeque::new())),
        })
    }

    #[must_use]
    pub fn owner_agent_id(&self) -> &str {
        &self.owner_id
    }

    /// Returns bounded process-local observations. These values describe this
    /// host generation only; they are not a production SLO or durable receipt.
    pub async fn metrics_snapshot(&self) -> CompactEngineHostMetricsV1 {
        let samples = self.timing_samples.lock().await;
        summarize_metrics(&samples)
    }

    // Validate after the queue wait, not before it. The returned guard keeps
    // one host operation serialized while its owner authority is checked.
    async fn checked_coordinator(
        &self,
    ) -> Result<(MutexGuard<'_, MemoryCheckpointCoordinatorV2>, u64), AgentdError> {
        let waiting = Instant::now();
        let coordinator = self.coordinator.lock().await;
        let queue_wait_micros = duration_micros(waiting.elapsed());
        self.production_writer
            .writer()
            .verify_current_authority()
            .await?;
        Ok((coordinator, queue_wait_micros))
    }

    async fn record_timing(
        &self,
        queue_wait_micros: u64,
        end_to_end_micros: u64,
        succeeded: bool,
    ) {
        let mut samples = self.timing_samples.lock().await;
        if samples.len() == MAX_COMPACTION_HOST_TIMING_SAMPLES {
            samples.pop_front();
        }
        samples.push_back(CompactEngineHostTimingSampleV1 {
            queue_wait_micros,
            end_to_end_micros,
            succeeded,
        });
    }

    pub async fn renew_owner_lease(
        &self,
        lease_expires_at_unix_seconds: u64,
        now_unix_seconds: u64,
    ) -> Result<(), AgentdError> {
        let (coordinator, _) = self.checked_coordinator().await?;
        coordinator
            .renew_lease(lease_expires_at_unix_seconds, now_unix_seconds)
            .await
            .map_err(compaction_error)
    }

    pub async fn install_successor_manifest(
        &self,
        manifest_bytes: &[u8],
        now_unix_seconds: u64,
    ) -> Result<Digest32, AgentdError> {
        let (mut coordinator, _) = self.checked_coordinator().await?;
        coordinator
            .install_successor_manifest(manifest_bytes, now_unix_seconds)
            .await
            .map_err(compaction_error)
    }

    pub async fn publish_checkpoint(
        &self,
        idempotency_key: &str,
        publication: &VerifiedCompactionPublicationV1,
        retain_source_until_unix_seconds: u64,
        now_unix_seconds: u64,
    ) -> Result<CompactionPublicationReceiptV2, AgentdError> {
        let started = Instant::now();
        let checked = self.checked_coordinator().await;
        let (coordinator, queue_wait_micros) = match checked {
            Ok(value) => value,
            Err(error) => {
                self.record_timing(0, duration_micros(started.elapsed()), false)
                    .await;
                return Err(error);
            }
        };
        let result = coordinator
            .publish_verified_checkpoint(
                idempotency_key,
                publication,
                retain_source_until_unix_seconds,
                now_unix_seconds,
            )
            .await
            .map_err(compaction_error);
        drop(coordinator);
        self.record_timing(
            queue_wait_micros,
            duration_micros(started.elapsed()),
            result.is_ok(),
        )
        .await;
        result
    }

    pub async fn recover_current_checkpoint(
        &self,
        scope_id: &str,
        purpose_id: &str,
        now_unix_seconds: u64,
    ) -> Result<Option<VerifiedCompactionSelectionV2>, AgentdError> {
        let started = Instant::now();
        let checked = self.checked_coordinator().await;
        let (coordinator, queue_wait_micros) = match checked {
            Ok(value) => value,
            Err(error) => {
                self.record_timing(0, duration_micros(started.elapsed()), false)
                    .await;
                return Err(error);
            }
        };
        let selection = coordinator
            .recover_current_checkpoint(scope_id, purpose_id, now_unix_seconds)
            .await
            .map_err(compaction_error);
        drop(coordinator);
        let result = match selection {
            Ok(selection) => self
                .production_writer
                .writer()
                .verify_current_authority()
                .await
                .map(|()| selection),
            Err(error) => Err(error),
        };
        self.record_timing(
            queue_wait_micros,
            duration_micros(started.elapsed()),
            result.is_ok(),
        )
        .await;
        result
    }

    pub async fn revoke_checkpoint(
        &self,
        checkpoint_digest: Digest32,
        reason_digest: Digest32,
        revoked_at_unix_seconds: u64,
    ) -> Result<Digest32, AgentdError> {
        let (coordinator, _) = self.checked_coordinator().await?;
        coordinator
            .revoke_checkpoint(checkpoint_digest, reason_digest, revoked_at_unix_seconds)
            .await
            .map_err(compaction_error)
    }

    pub async fn release_source_retention(
        &self,
        checkpoint_digest: Digest32,
        now_unix_seconds: u64,
    ) -> Result<(), AgentdError> {
        let (coordinator, _) = self.checked_coordinator().await?;
        coordinator
            .release_source_retention(checkpoint_digest, now_unix_seconds)
            .await
            .map_err(compaction_error)
    }

    pub async fn claim_next_publication_event(
        &self,
        now_unix_seconds: u64,
        claim_token: &str,
    ) -> Result<Option<DurableCompactionOutboxEventV1>, AgentdError> {
        let (coordinator, _) = self.checked_coordinator().await?;
        coordinator
            .claim_next_outbox(now_unix_seconds, claim_token)
            .await
            .map_err(compaction_error)
    }

    pub async fn complete_publication_event(
        &self,
        event: &DurableCompactionOutboxEventV1,
        delivered_at_unix_seconds: u64,
    ) -> Result<(), AgentdError> {
        let (coordinator, _) = self.checked_coordinator().await?;
        coordinator
            .complete_outbox(event, delivered_at_unix_seconds)
            .await
            .map_err(compaction_error)
    }

    pub async fn reconcile_startup(&self, now_unix_seconds: u64) -> Result<u64, AgentdError> {
        let (coordinator, _) = self.checked_coordinator().await?;
        coordinator
            .verify_integrity(now_unix_seconds)
            .await
            .map_err(compaction_error)?;
        coordinator
            .reconcile_claims(now_unix_seconds)
            .await
            .map_err(compaction_error)
    }
}

fn summarize_metrics(
    samples: &VecDeque<CompactEngineHostTimingSampleV1>,
) -> CompactEngineHostMetricsV1 {
    let sample_count = u64::try_from(samples.len()).unwrap_or(u64::MAX);
    let successful_operations =
        u64::try_from(samples.iter().filter(|sample| sample.succeeded).count())
            .unwrap_or(u64::MAX);
    let failed_operations = sample_count.saturating_sub(successful_operations);
    let queue_wait = samples
        .iter()
        .map(|sample| sample.queue_wait_micros)
        .collect::<Vec<_>>();
    let end_to_end = samples
        .iter()
        .map(|sample| sample.end_to_end_micros)
        .collect::<Vec<_>>();
    CompactEngineHostMetricsV1 {
        sample_count,
        successful_operations,
        failed_operations,
        queue_wait: summarize_latency(queue_wait),
        end_to_end: summarize_latency(end_to_end),
    }
}

fn summarize_latency(mut values: Vec<u64>) -> CompactEngineLatencySummaryV1 {
    if values.is_empty() {
        return CompactEngineLatencySummaryV1::default();
    }
    values.sort_unstable();
    CompactEngineLatencySummaryV1 {
        p50_micros: percentile(&values, 50),
        p95_micros: percentile(&values, 95),
        p99_micros: percentile(&values, 99),
        maximum_micros: values.last().copied().unwrap_or_default(),
    }
}

fn percentile(values: &[u64], percentile: usize) -> u64 {
    let rank = values
        .len()
        .saturating_mul(percentile)
        .saturating_add(99)
        / 100;
    values[rank.saturating_sub(1).min(values.len().saturating_sub(1))]
}

fn duration_micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}

fn compaction_error(error: CompactionCoordinatorErrorV2) -> AgentdError {
    let message = error.to_string();
    let (code, action, commit_state) = match &error {
        CompactionCoordinatorErrorV2::Invalid(_) => (
            CompactEngineErrorCodeV1::InvalidInput,
            CompactEngineRecoveryActionV1::CorrectRequest,
            CompactEngineCommitStateV1::NotCommitted,
        ),
        CompactionCoordinatorErrorV2::Admission(_) => (
            CompactEngineErrorCodeV1::AdmissionRejected,
            CompactEngineRecoveryActionV1::CorrectRequest,
            CompactEngineCommitStateV1::NotCommitted,
        ),
        CompactionCoordinatorErrorV2::Corrupt(_) => (
            CompactEngineErrorCodeV1::CorruptState,
            CompactEngineRecoveryActionV1::StopWrites,
            CompactEngineCommitStateV1::Unknown,
        ),
        CompactionCoordinatorErrorV2::Durable(durable) => match durable {
            DurableCompactionError::Invalid(_) => (
                CompactEngineErrorCodeV1::InvalidInput,
                CompactEngineRecoveryActionV1::CorrectRequest,
                CompactEngineCommitStateV1::NotCommitted,
            ),
            DurableCompactionError::Conflict(_) => (
                CompactEngineErrorCodeV1::OwnerConflict,
                CompactEngineRecoveryActionV1::RetrySameOperation,
                CompactEngineCommitStateV1::Unknown,
            ),
            DurableCompactionError::Corrupt(_) => (
                CompactEngineErrorCodeV1::CorruptState,
                CompactEngineRecoveryActionV1::StopWrites,
                CompactEngineCommitStateV1::Unknown,
            ),
            DurableCompactionError::Capacity(_) => (
                CompactEngineErrorCodeV1::CapacityExceeded,
                CompactEngineRecoveryActionV1::Backpressure,
                CompactEngineCommitStateV1::NotCommitted,
            ),
            DurableCompactionError::Indeterminate(_) => (
                CompactEngineErrorCodeV1::OutcomeIndeterminate,
                CompactEngineRecoveryActionV1::ReconcileSameOperation,
                CompactEngineCommitStateV1::Unknown,
            ),
            DurableCompactionError::Sql(_) => (
                CompactEngineErrorCodeV1::StorageUnavailable,
                CompactEngineRecoveryActionV1::ReopenOwner,
                CompactEngineCommitStateV1::Unknown,
            ),
        },
    };
    AgentdError::CompactEngine {
        code,
        action,
        commit_state,
        message,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn latency_summary_uses_nearest_rank_percentiles() {
        let summary = summarize_latency((1_u64..=100).collect());
        assert_eq!(summary.p50_micros, 50);
        assert_eq!(summary.p95_micros, 95);
        assert_eq!(summary.p99_micros, 99);
        assert_eq!(summary.maximum_micros, 100);
    }

    #[test]
    fn empty_latency_summary_is_zeroed() {
        assert_eq!(
            summarize_latency(Vec::new()),
            CompactEngineLatencySummaryV1::default()
        );
    }
}
