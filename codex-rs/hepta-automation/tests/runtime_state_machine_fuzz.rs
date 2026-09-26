use codex_hepta_automation::AutomationBatchLimits;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFailureDisposition;
use codex_hepta_automation::MAX_AUTOMATION_ADMISSION_BATCH;
use codex_hepta_automation::MAX_NEURAL_CIRCUIT_FEEDBACK_ROUNDS;
use codex_hepta_automation::MAX_NEURAL_CIRCUIT_RUNTIME_DEPTH;
use codex_hepta_automation::NeuralCircuitRuntimeBudgetV1;
use codex_hepta_automation::bounded_automation_retry_delay_ms;
use codex_hepta_automation::classify_automation_error;

fn xorshift64(mut value: u64) -> u64 {
    value ^= value << 13;
    value ^= value >> 7;
    value ^= value << 17;
    value
}

#[test]
fn deterministic_property_sweep_preserves_all_runtime_bounds() {
    let mut state = 0x4d59_5df4_d0f3_3173_u64;
    for _ in 0..20_000 {
        state = xorshift64(state);
        let admissions = usize::try_from(state % 96).expect("bounded usize");
        assert_eq!(
            AutomationBatchLimits::new(admissions).is_ok(),
            (1..=MAX_AUTOMATION_ADMISSION_BATCH).contains(&admissions)
        );

        state = xorshift64(state);
        let depth = u32::try_from(state % 300).expect("bounded depth");
        state = xorshift64(state);
        let feedback = u32::try_from(state % 48).expect("bounded feedback");
        assert_eq!(
            NeuralCircuitRuntimeBudgetV1::new(depth, feedback).is_ok(),
            depth > 0
                && depth <= MAX_NEURAL_CIRCUIT_RUNTIME_DEPTH
                && feedback <= MAX_NEURAL_CIRCUIT_FEEDBACK_ROUNDS
        );

        state = xorshift64(state);
        let attempt = u8::try_from(state % 32).expect("bounded attempt");
        let delay = bounded_automation_retry_delay_ms(attempt);
        assert!((250..=4_000).contains(&delay));
    }
}

#[test]
fn failure_state_machine_never_retries_unknown_or_corrupt_outcomes() {
    let cases = [
        (
            AutomationError::AccessDenied,
            AutomationFailureDisposition::FailStop,
        ),
        (
            AutomationError::TimerFenced,
            AutomationFailureDisposition::FailStop,
        ),
        (
            AutomationError::Corrupt,
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
            AutomationError::Invalid,
            AutomationFailureDisposition::Isolate,
        ),
        (
            AutomationError::Conflict,
            AutomationFailureDisposition::Isolate,
        ),
        (
            AutomationError::DispatchUnknown,
            AutomationFailureDisposition::Reconcile,
        ),
    ];
    for (error, expected) in cases {
        assert_eq!(classify_automation_error(&error), expected);
    }
}
