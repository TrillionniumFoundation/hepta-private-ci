#![allow(
    clippy::expect_used,
    reason = "deterministic property tests require explicit conversion context"
)]

use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFailureDisposition;
use codex_hepta_automation::AutomationRuntimePolicyV1;
use codex_hepta_automation::AutomationRuntimeSloV1;
use codex_hepta_automation::CircuitRuntimeProfileV1;
use codex_hepta_automation::classify_automation_error;

fn xorshift64(mut value: u64) -> u64 {
    value ^= value << 13;
    value ^= value >> 7;
    value ^= value << 17;
    value
}

#[test]
fn deterministic_property_sweep_preserves_runtime_bounds() {
    let mut state = 0x4d59_5df4_d0f3_3173_u64;
    for _ in 0..20_000 {
        state = xorshift64(state);
        let recovery_budget = u16::try_from(state % 300).expect("bounded recovery budget");
        state = xorshift64(state);
        let admission_budget = u16::try_from(state % 300).expect("bounded admission budget");
        state = xorshift64(state);
        let provider_in_flight = u16::try_from(state % 4).expect("bounded provider budget");
        state = xorshift64(state);
        let consecutive_failures = u8::try_from(state % 40).expect("bounded failure budget");
        state = xorshift64(state);
        let base_backoff_ms = state % 2_000;
        state = xorshift64(state);
        let max_backoff_ms = state % 8_000;

        state = xorshift64(state);
        let dispatch_timeout_ms = state % 10_000;
        state = xorshift64(state);
        let unknown_reconciliation_ms = state % 20_000;
        state = xorshift64(state);
        let lease_expiry_ms = state % 20_000;
        state = xorshift64(state);
        let writer_epoch_fence_ms = state % 2_000;
        let slo = AutomationRuntimeSloV1 {
            dispatch_timeout_ms,
            unknown_reconciliation_ms,
            lease_expiry_ms,
            writer_epoch_fence_ms,
        };
        let slo_is_valid = dispatch_timeout_ms > 0
            && unknown_reconciliation_ms >= dispatch_timeout_ms
            && lease_expiry_ms > dispatch_timeout_ms
            && writer_epoch_fence_ms > 0;
        assert_eq!(slo.validate().is_ok(), slo_is_valid);

        let policy = AutomationRuntimePolicyV1 {
            recovery_budget_per_cycle: recovery_budget,
            admission_budget_per_cycle: admission_budget,
            max_provider_in_flight: provider_in_flight,
            max_consecutive_pre_admission_failures: consecutive_failures,
            base_retry_backoff_ms: base_backoff_ms,
            max_retry_backoff_ms: max_backoff_ms,
            slo,
        };
        let policy_is_valid = (1..=256).contains(&recovery_budget)
            && (1..=256).contains(&admission_budget)
            && provider_in_flight == 1
            && (1..=32).contains(&consecutive_failures)
            && base_backoff_ms > 0
            && max_backoff_ms >= base_backoff_ms
            && slo_is_valid;
        assert_eq!(policy.validate().is_ok(), policy_is_valid);

        state = xorshift64(state);
        let max_steps = u32::try_from(state % 4_300).expect("bounded steps");
        state = xorshift64(state);
        let max_depth = u16::try_from(state % 1_100).expect("bounded depth");
        state = xorshift64(state);
        let max_feedback_rounds = u16::try_from(state % 300).expect("bounded feedback");
        state = xorshift64(state);
        let cost_budget_units = state % 8;
        let profile = CircuitRuntimeProfileV1 {
            max_steps,
            max_depth,
            max_feedback_rounds,
            cost_budget_units,
        };
        let profile_is_valid = (1..=4_096).contains(&max_steps)
            && (1..=1_024).contains(&max_depth)
            && max_feedback_rounds <= 256
            && cost_budget_units > 0;
        assert_eq!(profile.validate().is_ok(), profile_is_valid);
    }
}

#[test]
fn retry_and_failure_properties_never_blindly_redispatch_unknown_work() {
    let policy = AutomationRuntimePolicyV1::default();
    let mut previous = 0;
    for failure in 1..=u8::MAX {
        let delay = policy.retry_delay_ms(failure);
        assert!(delay >= previous);
        assert!(delay <= policy.max_retry_backoff_ms);
        previous = delay;
    }

    let cases = [
        (
            AutomationError::AccessDenied,
            AutomationFailureDisposition::Fence,
        ),
        (
            AutomationError::TimerFenced,
            AutomationFailureDisposition::Fence,
        ),
        (
            AutomationError::Corrupt,
            AutomationFailureDisposition::FailStop,
        ),
        (
            AutomationError::Invalid,
            AutomationFailureDisposition::FailStop,
        ),
        (
            AutomationError::Unavailable,
            AutomationFailureDisposition::Retry,
        ),
        (
            AutomationError::Dispatch,
            AutomationFailureDisposition::Retry,
        ),
        (
            AutomationError::DispatchUnknown,
            AutomationFailureDisposition::Reconcile,
        ),
        (
            AutomationError::Conflict,
            AutomationFailureDisposition::Isolate,
        ),
    ];
    for (error, expected) in cases {
        assert_eq!(classify_automation_error(&error), expected);
    }
}
