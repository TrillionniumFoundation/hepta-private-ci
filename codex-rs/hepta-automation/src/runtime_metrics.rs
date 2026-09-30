//! Bounded operational metrics for the durable automation owner.
//!
//! Store-derived gauges are read from one owner database without changing
//! business state. Process counters are monotone for the current Agentd process;
//! a restart begins a new process epoch and must be labelled by host/generation
//! by the metrics exporter.

use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use serde::Deserialize;
use serde::Serialize;

use crate::AutomationError;
use crate::AutomationStore;

pub const AUTOMATION_UNKNOWN_EFFECT_AGE_SECONDS: &str =
    "automation_unknown_effect_age_seconds";
pub const AUTOMATION_RECOVERY_SWEEP_LAG: &str = "automation_recovery_sweep_lag";
pub const AUTOMATION_RECOVERY_BUDGET_SATURATION_TOTAL: &str =
    "automation_recovery_budget_saturation_total";
pub const AUTOMATION_TIMER_WRITER_EPOCH: &str = "automation_timer_writer_epoch";
pub const AUTOMATION_TIMER_DRAIN_BLOCKED_TOTAL: &str =
    "automation_timer_drain_blocked_total";
pub const AUTOMATION_CIRCUIT_RECOVERY_REQUIRED_TOTAL: &str =
    "automation_circuit_recovery_required_total";
pub const AUTOMATION_CIRCUIT_RESERVED_COST_UNITS: &str =
    "automation_circuit_reserved_cost_units";
pub const AUTOMATION_CIRCUIT_RESUME_LATENCY_SECONDS: &str =
    "automation_circuit_resume_latency_seconds";
pub const AUTOMATION_OCCURRENCE_PARKED_SECONDS: &str =
    "automation_occurrence_parked_seconds";
pub const AUTOMATION_DESTINATION_DEDUPE_CONFLICT_TOTAL: &str =
    "automation_destination_dedupe_conflict_total";

static RECOVERY_BUDGET_SATURATION_TOTAL: AtomicU64 = AtomicU64::new(0);
static TIMER_DRAIN_BLOCKED_TOTAL: AtomicU64 = AtomicU64::new(0);
static CIRCUIT_RECOVERY_REQUIRED_TOTAL: AtomicU64 = AtomicU64::new(0);
static DESTINATION_DEDUPE_CONFLICT_TOTAL: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AutomationRuntimeMetricsV1 {
    pub unknown_effect_age_seconds: u64,
    pub recovery_sweep_lag: u64,
    pub recovery_budget_saturation_total: u64,
    pub timer_writer_epoch: u64,
    pub timer_drain_blocked_total: u64,
    pub circuit_recovery_required_total: u64,
    pub circuit_recovery_required_current: u64,
    pub circuit_reserved_cost_units: u64,
    pub circuit_resume_latency_seconds: u64,
    pub occurrence_parked_seconds: u64,
    pub destination_dedupe_conflict_total: u64,
}

pub fn record_automation_recovery_budget_saturation() {
    increment(&RECOVERY_BUDGET_SATURATION_TOTAL);
}

pub fn record_automation_timer_drain_blocked() {
    increment(&TIMER_DRAIN_BLOCKED_TOTAL);
}

pub fn record_automation_circuit_recovery_required() {
    increment(&CIRCUIT_RECOVERY_REQUIRED_TOTAL);
}

pub fn record_automation_destination_dedupe_conflict() {
    increment(&DESTINATION_DEDUPE_CONFLICT_TOTAL);
}

impl AutomationStore {
    /// Read bounded owner-local gauges and the current process counters.
    pub async fn runtime_metrics_v1(
        &self,
        now_ms: u64,
    ) -> Result<AutomationRuntimeMetricsV1, AutomationError> {
        let owner = self.owner_agent_id().as_str();
        let oldest_unknown: Option<i64> = sqlx::query_scalar(
            "SELECT MIN(o.observed_at_ms)
             FROM taskflow_effect_dispatch_observations o
             LEFT JOIN taskflow_effect_dispatch_reconciliations r
               ON r.owner_agent_id = o.owner_agent_id
              AND r.run_id = o.run_id
              AND r.step_id = o.step_id
              AND r.attempt = o.attempt
             WHERE o.owner_agent_id = ?
               AND o.observation = 'indeterminate'
               AND r.owner_agent_id IS NULL",
        )
        .bind(owner)
        .fetch_one(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        let recovery_sweep_lag: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM automation_recovery_frontier WHERE owner_agent_id = ?",
        )
        .bind(owner)
        .fetch_one(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        let circuit_recovery_required_current: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM neural_circuit_runs
             WHERE owner_agent_id = ? AND state = 'recovery_required'",
        )
        .bind(owner)
        .fetch_one(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        let circuit_reserved_cost_units: Option<i64> = sqlx::query_scalar(
            "SELECT SUM(reserved_cost_units) FROM neural_circuit_runs
             WHERE owner_agent_id = ?",
        )
        .bind(owner)
        .fetch_one(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        let maximum_resume_latency_ms: Option<i64> = sqlx::query_scalar(
            "SELECT MAX(r.committed_at_ms - i.created_at_ms)
             FROM neural_circuit_activation_intents i
             JOIN neural_circuit_activation_receipts r
               ON r.owner_agent_id = i.owner_agent_id
              AND r.run_id = i.run_id
              AND r.activation_seq = i.activation_seq
             WHERE i.owner_agent_id = ?
               AND r.committed_at_ms >= i.created_at_ms",
        )
        .bind(owner)
        .fetch_one(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        let oldest_parked: Option<i64> = sqlx::query_scalar(
            "SELECT MIN(updated_at_ms) FROM automation_occurrence_lifecycle
             WHERE owner_agent_id = ?
               AND overlap_policy = 'forbid'
               AND state IN ('admitted', 'running', 'indeterminate')",
        )
        .bind(owner)
        .fetch_one(self.taskflow_pool())
        .await
        .map_err(unavailable)?;

        Ok(AutomationRuntimeMetricsV1 {
            unknown_effect_age_seconds: age_seconds(now_ms, oldest_unknown)?,
            recovery_sweep_lag: non_negative(recovery_sweep_lag)?,
            recovery_budget_saturation_total: RECOVERY_BUDGET_SATURATION_TOTAL
                .load(Ordering::Relaxed),
            timer_writer_epoch: u64::try_from(self.timer_epoch())
                .map_err(|_| AutomationError::Corrupt)?,
            timer_drain_blocked_total: TIMER_DRAIN_BLOCKED_TOTAL.load(Ordering::Relaxed),
            circuit_recovery_required_total: CIRCUIT_RECOVERY_REQUIRED_TOTAL
                .load(Ordering::Relaxed),
            circuit_recovery_required_current: non_negative(
                circuit_recovery_required_current,
            )?,
            circuit_reserved_cost_units: optional_non_negative(circuit_reserved_cost_units)?,
            circuit_resume_latency_seconds: optional_non_negative(maximum_resume_latency_ms)?
                / 1_000,
            occurrence_parked_seconds: age_seconds(now_ms, oldest_parked)?,
            destination_dedupe_conflict_total: DESTINATION_DEDUPE_CONFLICT_TOTAL
                .load(Ordering::Relaxed),
        })
    }
}

fn increment(counter: &AtomicU64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
        Some(value.saturating_add(1))
    });
}

fn non_negative(value: i64) -> Result<u64, AutomationError> {
    u64::try_from(value).map_err(|_| AutomationError::Corrupt)
}

fn optional_non_negative(value: Option<i64>) -> Result<u64, AutomationError> {
    value.map_or(Ok(0), non_negative)
}

fn age_seconds(now_ms: u64, observed_ms: Option<i64>) -> Result<u64, AutomationError> {
    let Some(observed_ms) = observed_ms else {
        return Ok(0);
    };
    let observed_ms = non_negative(observed_ms)?;
    Ok(now_ms.saturating_sub(observed_ms) / 1_000)
}

fn unavailable(_: sqlx::Error) -> AutomationError {
    AutomationError::Unavailable
}

#[cfg(test)]
mod tests {
    use codex_hepta_contracts::AgentId;

    use super::*;

    #[tokio::test]
    async fn fresh_owner_exports_all_named_metrics_without_mutating_state() {
        let temp = tempfile::tempdir().expect("temp");
        let store = AutomationStore::open_root(
            temp.path().join("automation"),
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
        )
        .await
        .expect("store");
        let before = store.timer_status().await.expect("before");
        let metrics = store.runtime_metrics_v1(10_000).await.expect("metrics");
        let after = store.timer_status().await.expect("after");
        assert_eq!(before, after);
        assert_eq!(metrics.timer_writer_epoch, before.writer_epoch);
        assert_eq!(metrics.unknown_effect_age_seconds, 0);
        assert_eq!(metrics.recovery_sweep_lag, 0);
        assert_eq!(metrics.circuit_reserved_cost_units, 0);
        assert_eq!(metrics.occurrence_parked_seconds, 0);
        for name in [
            AUTOMATION_UNKNOWN_EFFECT_AGE_SECONDS,
            AUTOMATION_RECOVERY_SWEEP_LAG,
            AUTOMATION_RECOVERY_BUDGET_SATURATION_TOTAL,
            AUTOMATION_TIMER_WRITER_EPOCH,
            AUTOMATION_TIMER_DRAIN_BLOCKED_TOTAL,
            AUTOMATION_CIRCUIT_RECOVERY_REQUIRED_TOTAL,
            AUTOMATION_CIRCUIT_RESERVED_COST_UNITS,
            AUTOMATION_CIRCUIT_RESUME_LATENCY_SECONDS,
            AUTOMATION_OCCURRENCE_PARKED_SECONDS,
            AUTOMATION_DESTINATION_DEDUPE_CONFLICT_TOTAL,
        ] {
            assert!(name.starts_with("automation_"));
        }
        store.close().await;
    }

    #[test]
    fn process_counters_are_monotone_and_saturating() {
        let before = TIMER_DRAIN_BLOCKED_TOTAL.load(Ordering::Relaxed);
        record_automation_timer_drain_blocked();
        assert!(TIMER_DRAIN_BLOCKED_TOTAL.load(Ordering::Relaxed) >= before.saturating_add(1));
    }
}
