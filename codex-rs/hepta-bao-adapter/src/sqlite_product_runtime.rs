//! Product composition for the async SQLite Bao owner.
//!
//! This is the normal durable ingress/recovery surface for selected product
//! hosts. The JSON owner remains a bounded migration/reference oracle. Recovery
//! workers lease rows through the SQLite queue and never redispatch a secret
//! read or re-enter a consumer.

use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use super::*;
use crate::SqliteBaoOwnerErrorV1;
use crate::SqliteBaoOwnerMetricsV1;
use crate::SqliteBaoOwnerV1;
use crate::SqliteConsumptionRecordV1;
use crate::SqliteReconciliationClaimV1;

const MAX_RUNTIME_LEASE_MS: u64 = 5 * 60 * 1_000;
const WORKER_DURATION_SAMPLE_LIMIT: usize = 256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoSqliteProductRuntimeConfigV1 {
    pub forward_executor_id: String,
    pub recovery_worker_id: String,
    pub forward_execution_lease_ms: u64,
    pub recovery_lease_ms: u64,
    pub recovery_batch_limit: u32,
    pub recovery_retry_base_ms: u64,
    pub recovery_retry_max_ms: u64,
}

impl Default for BaoSqliteProductRuntimeConfigV1 {
    fn default() -> Self {
        Self {
            forward_executor_id: "secrets.heptabao.forward".to_owned(),
            recovery_worker_id: "secrets.heptabao.recovery".to_owned(),
            forward_execution_lease_ms: 180_000,
            recovery_lease_ms: 60_000,
            recovery_batch_limit: 32,
            recovery_retry_base_ms: 1_000,
            recovery_retry_max_ms: 60_000,
        }
    }
}

impl BaoSqliteProductRuntimeConfigV1 {
    pub(crate) fn validate(&self) -> Result<(), BaoFinalUseHostError> {
        if !consumer_id(&self.forward_executor_id)
            || !consumer_id(&self.recovery_worker_id)
            || self.forward_executor_id == self.recovery_worker_id
            || self.forward_execution_lease_ms == 0
            || self.forward_execution_lease_ms > MAX_RUNTIME_LEASE_MS
            || self.recovery_lease_ms == 0
            || self.recovery_lease_ms > MAX_RUNTIME_LEASE_MS
            || self.recovery_batch_limit == 0
            || self.recovery_batch_limit > 1_024
            || self.recovery_retry_base_ms == 0
            || self.recovery_retry_base_ms > self.recovery_retry_max_ms
        {
            return Err(BaoFinalUseHostError::InvalidRuntimeConfiguration);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoRecoveryBatchReportV1 {
    pub claimed: u64,
    pub succeeded: u64,
    pub terminal_failed: u64,
    pub rescheduled: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoRecoveryWorkerMetricsV1 {
    pub batches: u64,
    pub claimed: u64,
    pub succeeded: u64,
    pub terminal_failed: u64,
    pub rescheduled: u64,
    pub awaiting_original_evidence: u64,
    pub awaiting_settlement: u64,
    pub identity_conflicts: u64,
    pub owner_failures: u64,
    pub last_batch_duration_micros: u64,
    pub max_batch_duration_micros: u64,
    pub p50_batch_duration_micros: u64,
    pub p95_batch_duration_micros: u64,
    pub p99_batch_duration_micros: u64,
}

#[derive(Default)]
struct BaoRecoveryWorkerMetricsOwnerV1 {
    batches: u64,
    claimed: u64,
    succeeded: u64,
    terminal_failed: u64,
    rescheduled: u64,
    awaiting_original_evidence: u64,
    awaiting_settlement: u64,
    identity_conflicts: u64,
    owner_failures: u64,
    batch_duration_samples_micros: VecDeque<u64>,
    last_batch_duration_micros: u64,
    max_batch_duration_micros: u64,
}

impl BaoRecoveryWorkerMetricsOwnerV1 {
    fn record(
        &mut self,
        started: Instant,
        report: &BaoRecoveryBatchReportV1,
        classes: &[BaoProductErrorClassV1],
    ) {
        self.batches = self.batches.saturating_add(1);
        self.claimed = self.claimed.saturating_add(report.claimed);
        self.succeeded = self.succeeded.saturating_add(report.succeeded);
        self.terminal_failed = self.terminal_failed.saturating_add(report.terminal_failed);
        self.rescheduled = self.rescheduled.saturating_add(report.rescheduled);
        for class in classes {
            match class {
                BaoProductErrorClassV1::AwaitingOriginalEvidence => {
                    self.awaiting_original_evidence =
                        self.awaiting_original_evidence.saturating_add(1);
                }
                BaoProductErrorClassV1::AwaitingSettlement => {
                    self.awaiting_settlement = self.awaiting_settlement.saturating_add(1);
                }
                BaoProductErrorClassV1::IdentityConflict => {
                    self.identity_conflicts = self.identity_conflicts.saturating_add(1);
                }
                BaoProductErrorClassV1::DurableOwnerFailure
                | BaoProductErrorClassV1::CommitIndeterminate
                | BaoProductErrorClassV1::OwnerBusy
                | BaoProductErrorClassV1::CapacityRejected => {
                    self.owner_failures = self.owner_failures.saturating_add(1);
                }
                BaoProductErrorClassV1::AdmissionRejected
                | BaoProductErrorClassV1::ReconciliationRequired
                | BaoProductErrorClassV1::HistoricalTerminalFailure
                | BaoProductErrorClassV1::ExternalControlFailure => {}
            }
        }
        let micros = elapsed_micros(started);
        self.last_batch_duration_micros = micros;
        self.max_batch_duration_micros = self.max_batch_duration_micros.max(micros);
        if self.batch_duration_samples_micros.len() == WORKER_DURATION_SAMPLE_LIMIT {
            self.batch_duration_samples_micros.pop_front();
        }
        self.batch_duration_samples_micros.push_back(micros);
    }

    fn snapshot(&self) -> BaoRecoveryWorkerMetricsV1 {
        let mut samples = self
            .batch_duration_samples_micros
            .iter()
            .copied()
            .collect::<Vec<_>>();
        samples.sort_unstable();
        BaoRecoveryWorkerMetricsV1 {
            batches: self.batches,
            claimed: self.claimed,
            succeeded: self.succeeded,
            terminal_failed: self.terminal_failed,
            rescheduled: self.rescheduled,
            awaiting_original_evidence: self.awaiting_original_evidence,
            awaiting_settlement: self.awaiting_settlement,
            identity_conflicts: self.identity_conflicts,
            owner_failures: self.owner_failures,
            last_batch_duration_micros: self.last_batch_duration_micros,
            max_batch_duration_micros: self.max_batch_duration_micros,
            p50_batch_duration_micros: operation_percentile(&samples, 50),
            p95_batch_duration_micros: operation_percentile(&samples, 95),
            p99_batch_duration_micros: operation_percentile(&samples, 99),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SqliteBaoProductRuntimeMetricsV1 {
    pub operations: BaoOperationMetricsV1,
    pub owner: SqliteBaoOwnerMetricsV1,
    pub recovery_worker: BaoRecoveryWorkerMetricsV1,
}

pub struct SqliteBaoProductRuntimeV1 {
    host: Arc<BaoFinalUseHost>,
    owner: Arc<SqliteBaoOwnerV1>,
    config: BaoSqliteProductRuntimeConfigV1,
    recovery_metrics: Mutex<BaoRecoveryWorkerMetricsOwnerV1>,
}

impl std::fmt::Debug for SqliteBaoProductRuntimeV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("SqliteBaoProductRuntimeV1")
            .field("owner_fenced", &self.owner.is_fenced())
            .field("recovery_batch_limit", &self.config.recovery_batch_limit)
            .finish_non_exhaustive()
    }
}

impl SqliteBaoProductRuntimeV1 {
    pub fn new(
        host: Arc<BaoFinalUseHost>,
        owner: Arc<SqliteBaoOwnerV1>,
        config: BaoSqliteProductRuntimeConfigV1,
    ) -> Result<Self, BaoFinalUseHostError> {
        config.validate()?;
        if owner.is_fenced() {
            return Err(BaoFinalUseHostError::Unavailable);
        }
        Ok(Self {
            host,
            owner,
            config,
            recovery_metrics: Mutex::new(Default::default()),
        })
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    #[test]
    fn runtime_configuration_is_bounded_and_has_distinct_workers() {
        assert!(
            BaoSqliteProductRuntimeConfigV1::default()
                .validate()
                .is_ok()
        );
        let mut invalid = BaoSqliteProductRuntimeConfigV1::default();
        invalid.recovery_worker_id = invalid.forward_executor_id.clone();
        assert_eq!(
            invalid.validate(),
            Err(BaoFinalUseHostError::InvalidRuntimeConfiguration)
        );
        invalid = BaoSqliteProductRuntimeConfigV1::default();
        invalid.recovery_batch_limit = 1_025;
        assert_eq!(
            invalid.validate(),
            Err(BaoFinalUseHostError::InvalidRuntimeConfiguration)
        );
    }

    #[test]
    fn retry_backoff_is_bounded() {
        assert_eq!(retry_delay_ms(1_000, 60_000, 0), 1_000);
        assert_eq!(retry_delay_ms(1_000, 60_000, 3), 8_000);
        assert_eq!(retry_delay_ms(1_000, 60_000, 63), 60_000);
    }
}

#[path = "sqlite_runtime_ingress.rs"]
mod sqlite_runtime_ingress;
#[path = "sqlite_runtime_recovery.rs"]
mod sqlite_runtime_recovery;

#[path = "sqlite_runtime_dispatch.rs"]
mod sqlite_runtime_dispatch;
#[path = "sqlite_runtime_reconcile_claim.rs"]
mod sqlite_runtime_reconcile_claim;
#[path = "sqlite_runtime_uncertainty.rs"]
mod sqlite_runtime_uncertainty;

#[path = "sqlite_runtime_settlement.rs"]
mod sqlite_runtime_settlement;
use sqlite_runtime_settlement::clock_now_for_saga;
use sqlite_runtime_settlement::elapsed_micros;
use sqlite_runtime_settlement::historical_result;
use sqlite_runtime_settlement::historical_result_or_pending;
use sqlite_runtime_settlement::recovery_error_digest;
use sqlite_runtime_settlement::release_execution_claim_if_pending;
use sqlite_runtime_settlement::reservation_evidence;
use sqlite_runtime_settlement::reservation_terminal_abort_code;
use sqlite_runtime_settlement::retry_delay_ms;
use sqlite_runtime_settlement::settle_sqlite_terminal_row;
use sqlite_runtime_settlement::validate_sqlite_reservation;
