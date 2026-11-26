//! sqlite runtime recovery implementation.

use super::*;

impl SqliteBaoProductRuntimeV1 {
    pub async fn reconcile_consumption<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        operation_id: &str,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let terminal = self
            .owner
            .consumption_result(operation_id)
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        if let Some(result) = historical_result(terminal.operation) {
            return result;
        }
        let now_unix_ms = self.host.product_now()?;
        let mut claim = self
            .owner
            .claim_reconciliation_operation(
                &self.config.recovery_worker_id,
                operation_id,
                now_unix_ms,
                self.config.recovery_lease_ms,
            )
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        let started = Instant::now();
        let result = self
            .host
            .reconcile_sqlite_claim(authbus, &self.owner, &claim, evidence)
            .await;
        self.host.record_recovery_metric(started, &result);
        if let Err(error) = &result {
            self.reschedule_claim(&mut claim, error).await?;
        }
        result
    }

    pub async fn reconcile_due<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        evidence: &mut E,
    ) -> Result<BaoRecoveryBatchReportV1, BaoProductHostError> {
        let batch_started = Instant::now();
        let mut report = BaoRecoveryBatchReportV1 {
            claimed: 0,
            succeeded: 0,
            terminal_failed: 0,
            rescheduled: 0,
        };
        let mut classes = Vec::new();
        for _ in 0..self.config.recovery_batch_limit {
            // Lease work only when this worker can execute it. A slow observer
            // must not consume the leases of later rows waiting in this batch.
            let now_unix_ms = self.host.product_now()?;
            let mut claims = self
                .owner
                .claim_due_reconciliation(
                    &self.config.recovery_worker_id,
                    now_unix_ms,
                    self.config.recovery_lease_ms,
                    /*limit*/ 1,
                )
                .await
                .map_err(BaoProductHostError::SqliteStore)?;
            let Some(mut claim) = claims.pop() else {
                break;
            };
            report.claimed = report.claimed.saturating_add(1);
            let started = Instant::now();
            let result = self
                .host
                .reconcile_sqlite_claim(authbus, &self.owner, &claim, evidence)
                .await;
            self.host.record_recovery_metric(started, &result);
            match &result {
                Ok(_) => report.succeeded = report.succeeded.saturating_add(1),
                Err(BaoProductHostError::TerminalFailure(_)) => {
                    report.terminal_failed = report.terminal_failed.saturating_add(1);
                    classes.push(BaoProductErrorClassV1::HistoricalTerminalFailure);
                }
                Err(error) => {
                    classes.push(error.class());
                    self.reschedule_claim(&mut claim, error).await?;
                    report.rescheduled = report.rescheduled.saturating_add(1);
                }
            }
        }
        if let Ok(mut metrics) = self.recovery_metrics.lock() {
            metrics.record(batch_started, &report, &classes);
        }
        Ok(report)
    }

    pub async fn metrics(&self) -> Result<SqliteBaoProductRuntimeMetricsV1, BaoProductHostError> {
        let now_unix_ms = self.host.product_now()?;
        let owner = self
            .owner
            .metrics(now_unix_ms)
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        let recovery_worker = self
            .recovery_metrics
            .lock()
            .map(|metrics| metrics.snapshot())
            .unwrap_or_else(|_| BaoRecoveryWorkerMetricsOwnerV1::default().snapshot());
        Ok(SqliteBaoProductRuntimeMetricsV1 {
            operations: self.host.operation_metrics(),
            owner,
            recovery_worker,
        })
    }

    pub(super) async fn reschedule_claim(
        &self,
        claim: &mut SqliteReconciliationClaimV1,
        error: &BaoProductHostError,
    ) -> Result<(), BaoProductHostError> {
        let latest = match self
            .owner
            .consumption_result(&claim.record.operation.operation_id)
            .await
        {
            Ok(record) => record,
            Err(SqliteBaoOwnerErrorV1::OperationNotFound) => return Ok(()),
            Err(error) => return Err(BaoProductHostError::SqliteStore(error)),
        };
        if latest.operation.state.is_terminal() {
            return Ok(());
        }
        claim.record = latest;
        let observed_at_unix_ms = self.host.product_now()?;
        let delay = retry_delay_ms(
            self.config.recovery_retry_base_ms,
            self.config.recovery_retry_max_ms,
            claim.attempt_count,
        );
        let next_attempt_at_unix_ms =
            observed_at_unix_ms
                .checked_add(delay)
                .ok_or(BaoProductHostError::SqliteStore(
                    SqliteBaoOwnerErrorV1::CapacityExceeded,
                ))?;
        let error_sha256 = recovery_error_digest(error.class());
        self.owner
            .record_claimed_reconciliation_failure(
                claim,
                observed_at_unix_ms,
                next_attempt_at_unix_ms,
                error_sha256,
            )
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        Ok(())
    }
}
