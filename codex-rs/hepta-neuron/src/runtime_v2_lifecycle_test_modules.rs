#[cfg(test)]
fn crash_cut(phase: &str) {
    if std::env::var("HEPTA_NEURON_V2_CLOSURE_CHILD").as_deref() == Ok("crash")
        && std::env::var("HEPTA_NEURON_V2_CLOSURE_CUT").as_deref() == Ok(phase)
    {
        std::process::exit(73);
    }
}

#[cfg(not(test))]
fn crash_cut(_phase: &str) {}

#[cfg(test)]
mod status_code_tests {
    use super::*;

    #[test]
    fn operation_codes_are_stable_and_distinguish_reconciliation() {
        let absent = NeuronOperationStatusV2::NotRecorded;
        assert_eq!(absent.stable_code(), "not_recorded");
        assert!(!absent.is_terminal());
        assert!(!absent.requires_reconciliation());

        let reserved = NeuronOperationStatusV2::NotExecuted;
        assert_eq!(reserved.stable_code(), "reserved_not_executed");
        assert!(!reserved.is_terminal());
        assert!(reserved.requires_reconciliation());

        let unknown = NeuronOperationStatusV2::OutcomeUnknown;
        assert_eq!(unknown.stable_code(), "outcome_unknown");
        assert!(!unknown.is_terminal());
        assert!(unknown.requires_reconciliation());

        let failed = NeuronOperationStatusV2::Failed(NeuronOperationFailureV2::ModelRejected);
        assert_eq!(failed.stable_code(), "failed");
        assert!(failed.is_terminal());
        assert!(!failed.requires_reconciliation());
    }

    #[test]
    fn error_codes_do_not_collapse_unknown_outcomes_into_failures() {
        assert_eq!(
            NeuronRuntimeV2Error::Store(GenerationStoreError::Indeterminate).stable_code(),
            "store_outcome_unknown"
        );
        assert_eq!(
            NeuronRuntimeV2Error::Model(NeuronModelError::Indeterminate).stable_code(),
            "model_outcome_unknown"
        );
        assert_eq!(
            NeuronRuntimeV2Error::TerminalFailure(NeuronOperationFailureV2::ModelRejected)
                .stable_code(),
            "terminal_failure"
        );
    }
}

#[cfg(test)]
#[path = "runtime_v2_recovery_policy_tests.rs"]
mod recovery_policy_tests;
