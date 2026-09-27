use serde::Deserialize;
use serde::Serialize;

use crate::AutomationError;

pub const AUTOMATION_RUNTIME_POLICY_SCHEMA_VERSION: u32 = 1;
const MAX_CYCLE_BUDGET: u16 = 256;
const MAX_RETRY_FAILURES: u8 = 32;

/// Runtime action selected after a scheduler or provider-boundary error.
///
/// The classification is intentionally separate from the error itself: the
/// durable owner records the concrete error while Agentd applies the bounded
/// operational policy. `Reconcile` never permits a fresh provider identity.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationFailureDisposition {
    Fence,
    FailStop,
    Retry,
    Reconcile,
    Isolate,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationRuntimeSloV1 {
    pub dispatch_timeout_ms: u64,
    pub unknown_reconciliation_ms: u64,
    pub lease_expiry_ms: u64,
    pub writer_epoch_fence_ms: u64,
}

impl Default for AutomationRuntimeSloV1 {
    fn default() -> Self {
        Self {
            dispatch_timeout_ms: 5_000,
            unknown_reconciliation_ms: 300_000,
            lease_expiry_ms: 30_000,
            writer_epoch_fence_ms: 1_000,
        }
    }
}

impl AutomationRuntimeSloV1 {
    pub fn validate(&self) -> Result<(), AutomationError> {
        if self.dispatch_timeout_ms == 0
            || self.unknown_reconciliation_ms < self.dispatch_timeout_ms
            || self.lease_expiry_ms <= self.dispatch_timeout_ms
            || self.writer_epoch_fence_ms == 0
        {
            return Err(AutomationError::Invalid);
        }
        Ok(())
    }
}

/// Bounded Agentd scheduling policy. It changes throughput and retry pacing,
/// never occurrence identity, durable ownership, provider authority or the
/// TaskFlow state machine.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationRuntimePolicyV1 {
    pub recovery_budget_per_cycle: u16,
    pub admission_budget_per_cycle: u16,
    pub max_provider_in_flight: u16,
    pub max_consecutive_pre_admission_failures: u8,
    pub base_retry_backoff_ms: u64,
    pub max_retry_backoff_ms: u64,
    pub slo: AutomationRuntimeSloV1,
}

impl Default for AutomationRuntimePolicyV1 {
    fn default() -> Self {
        Self {
            recovery_budget_per_cycle: 8,
            admission_budget_per_cycle: 16,
            // Provider contact remains serialized. Batching removes the fixed
            // 250-ms idle gap without introducing a second concurrency owner.
            max_provider_in_flight: 1,
            max_consecutive_pre_admission_failures: 3,
            base_retry_backoff_ms: 250,
            max_retry_backoff_ms: 5_000,
            slo: AutomationRuntimeSloV1::default(),
        }
    }
}

impl AutomationRuntimePolicyV1 {
    pub fn validate(&self) -> Result<(), AutomationError> {
        if !(1..=MAX_CYCLE_BUDGET).contains(&self.recovery_budget_per_cycle)
            || !(1..=MAX_CYCLE_BUDGET).contains(&self.admission_budget_per_cycle)
            || self.max_provider_in_flight != 1
            || !(1..=MAX_RETRY_FAILURES).contains(&self.max_consecutive_pre_admission_failures)
            || self.base_retry_backoff_ms == 0
            || self.max_retry_backoff_ms < self.base_retry_backoff_ms
        {
            return Err(AutomationError::Invalid);
        }
        self.slo.validate()
    }

    #[must_use]
    pub fn retry_delay_ms(&self, consecutive_failure: u8) -> u64 {
        let shift = u32::from(consecutive_failure.saturating_sub(1)).min(63);
        let factor = 1_u64.checked_shl(shift).unwrap_or(u64::MAX);
        self.base_retry_backoff_ms
            .saturating_mul(factor)
            .min(self.max_retry_backoff_ms)
    }
}

/// Classify one owner error without weakening its durable semantics.
#[must_use]
pub const fn classify_automation_error(error: &AutomationError) -> AutomationFailureDisposition {
    match error {
        AutomationError::AccessDenied | AutomationError::TimerFenced => {
            AutomationFailureDisposition::Fence
        }
        AutomationError::Corrupt | AutomationError::Invalid => {
            AutomationFailureDisposition::FailStop
        }
        AutomationError::Unavailable | AutomationError::Dispatch => {
            AutomationFailureDisposition::Retry
        }
        AutomationError::DispatchUnknown => AutomationFailureDisposition::Reconcile,
        AutomationError::Conflict => AutomationFailureDisposition::Isolate,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_policy_is_bounded_and_dispatch_fits_inside_the_lease() {
        let policy = AutomationRuntimePolicyV1::default();
        policy.validate().expect("default policy");
        assert_eq!(policy.max_provider_in_flight, 1);
        assert!(policy.slo.dispatch_timeout_ms < policy.slo.lease_expiry_ms);
    }

    #[test]
    fn retry_backoff_is_exponential_and_capped() {
        let policy = AutomationRuntimePolicyV1::default();
        assert_eq!(policy.retry_delay_ms(1), 250);
        assert_eq!(policy.retry_delay_ms(2), 500);
        assert_eq!(policy.retry_delay_ms(8), 5_000);
        assert_eq!(policy.retry_delay_ms(u8::MAX), 5_000);
    }

    #[test]
    fn failure_classes_preserve_unknown_and_fencing_boundaries() {
        assert_eq!(
            classify_automation_error(&AutomationError::DispatchUnknown),
            AutomationFailureDisposition::Reconcile
        );
        assert_eq!(
            classify_automation_error(&AutomationError::AccessDenied),
            AutomationFailureDisposition::Fence
        );
        assert_eq!(
            classify_automation_error(&AutomationError::Conflict),
            AutomationFailureDisposition::Isolate
        );
        assert_eq!(
            classify_automation_error(&AutomationError::Unavailable),
            AutomationFailureDisposition::Retry
        );
    }
}
