//! Importable host composition for the durable secrets.heptabao runtime.
//!
//! A product host supplies independently governed authority, consumer
//! registration, trusted time and checkpoint services, then calls
//! `compose_hepta_secrets_runtime`. Composition alone is not activation evidence.
//! Recovery claims exactly one operation at a time; the configured sweep limit
//! controls work performed rather than rows leased ahead of execution.

use std::sync::Arc;
use std::sync::Mutex;

use crate::BaoAuthBusEvidenceProvider;
use crate::BaoFinalUseHost;
use crate::BaoFinalUseHostError;
use crate::BaoProductHostError;
use crate::BaoRecoveryBatchReportV1;
use crate::BaoSqliteProductRuntimeConfigV1;
use crate::SqliteBaoOwnerV1;
use crate::SqliteBaoProductRuntimeMetricsV1;
use crate::SqliteBaoProductRuntimeV1;
use codex_hepta_authbus::AuthBusAuthorityHost;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoJustInTimeRecoveryMetricsV1 {
    pub sweeps: u64,
    pub claims_started_just_in_time: u64,
    pub no_work_sweeps: u64,
    pub claim_to_execution_start_micros_max: Option<u64>,
    pub lease_remaining_at_execution_start_ms_min: Option<u64>,
    pub claim_expired_before_execution_total: Option<u64>,
    pub reclaim_total: Option<u64>,
    pub claim_conflict_total: u64,
    pub oldest_reconciliation_age_seconds: Option<u64>,
}

#[derive(Default)]
struct BaoJustInTimeRecoveryMetricsOwnerV1 {
    sweeps: u64,
    claims_started_just_in_time: u64,
    no_work_sweeps: u64,
}

pub struct HeptaSecretsProductRuntimeV1 {
    runtime: SqliteBaoProductRuntimeV1,
    max_claims_per_sweep: u32,
    jit_metrics: Mutex<BaoJustInTimeRecoveryMetricsOwnerV1>,
}

impl HeptaSecretsProductRuntimeV1 {
    pub fn runtime(&self) -> &SqliteBaoProductRuntimeV1 {
        &self.runtime
    }

    /// Claims one due row, executes/reconciles it, and only then asks for the
    /// next row. No later row consumes lease time behind an earlier operation.
    pub async fn reconcile_due_just_in_time<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        evidence: &mut E,
    ) -> Result<BaoRecoveryBatchReportV1, BaoProductHostError> {
        let mut aggregate = BaoRecoveryBatchReportV1 {
            claimed: 0,
            succeeded: 0,
            terminal_failed: 0,
            rescheduled: 0,
        };
        let mut no_work = true;
        for _ in 0..self.max_claims_per_sweep {
            let report = self.runtime.reconcile_due(authbus, evidence).await?;
            if report.claimed == 0 {
                break;
            }
            no_work = false;
            aggregate.claimed = aggregate.claimed.saturating_add(report.claimed);
            aggregate.succeeded = aggregate.succeeded.saturating_add(report.succeeded);
            aggregate.terminal_failed = aggregate
                .terminal_failed
                .saturating_add(report.terminal_failed);
            aggregate.rescheduled = aggregate.rescheduled.saturating_add(report.rescheduled);
        }
        if let Ok(mut metrics) = self.jit_metrics.lock() {
            metrics.sweeps = metrics.sweeps.saturating_add(1);
            metrics.claims_started_just_in_time = metrics
                .claims_started_just_in_time
                .saturating_add(aggregate.claimed);
            if no_work {
                metrics.no_work_sweeps = metrics.no_work_sweeps.saturating_add(1);
            }
        }
        Ok(aggregate)
    }

    pub async fn operational_metrics(
        &self,
    ) -> Result<
        (
            SqliteBaoProductRuntimeMetricsV1,
            BaoJustInTimeRecoveryMetricsV1,
        ),
        BaoProductHostError,
    > {
        let runtime = self.runtime.metrics().await?;
        let (sweeps, claims_started_just_in_time, no_work_sweeps) = self
            .jit_metrics
            .lock()
            .map(|metrics| {
                (
                    metrics.sweeps,
                    metrics.claims_started_just_in_time,
                    metrics.no_work_sweeps,
                )
            })
            .unwrap_or((0, 0, 0));
        let projected = BaoJustInTimeRecoveryMetricsV1 {
            sweeps,
            claims_started_just_in_time,
            no_work_sweeps,
            // These three values require timestamps at the SQLite claim/execute
            // boundary. They remain explicit unknowns rather than fabricated 0s.
            claim_to_execution_start_micros_max: None,
            lease_remaining_at_execution_start_ms_min: None,
            claim_expired_before_execution_total: None,
            reclaim_total: None,
            claim_conflict_total: runtime.recovery_worker.identity_conflicts,
            oldest_reconciliation_age_seconds: runtime
                .owner
                .oldest_due_reconciliation_age_ms
                .map(|value| value / 1_000),
        };
        Ok((runtime, projected))
    }
}

pub fn compose_hepta_secrets_runtime(
    host: Arc<BaoFinalUseHost>,
    owner: Arc<SqliteBaoOwnerV1>,
    mut runtime_config: BaoSqliteProductRuntimeConfigV1,
) -> Result<HeptaSecretsProductRuntimeV1, BaoFinalUseHostError> {
    runtime_config.validate()?;
    let max_claims_per_sweep = runtime_config.recovery_batch_limit;
    // The production caller never leases a batch. The outer loop above controls
    // throughput while this inner runtime claims and consumes one row at a time.
    runtime_config.recovery_batch_limit = 1;
    let runtime = SqliteBaoProductRuntimeV1::new(host, owner, runtime_config)?;
    Ok(HeptaSecretsProductRuntimeV1 {
        runtime,
        max_claims_per_sweep,
        jit_metrics: Mutex::new(Default::default()),
    })
}

#[cfg(test)]
#[path = "product_bootstrap_tests.rs"]
mod tests;
