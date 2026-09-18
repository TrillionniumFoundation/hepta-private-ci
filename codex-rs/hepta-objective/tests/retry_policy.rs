use codex_hepta_objective::ObjectiveAdmissionError;
use codex_hepta_objective::ObjectiveError;
use codex_hepta_objective::ObjectiveRetryDirectiveV1;
use codex_hepta_objective::objective_admission_blind_retry_safe_v1;
use codex_hepta_objective::objective_admission_retry_directive_v1;

#[test]
fn availability_variants_do_not_share_one_blind_retry_policy() {
    let cases = [
        (
            ObjectiveAdmissionError::Compiler(ObjectiveError::FeasibilityBudgetExhausted),
            ObjectiveRetryDirectiveV1::RetrySameInput,
            true,
        ),
        (
            ObjectiveAdmissionError::SourceFromFuture,
            ObjectiveRetryDirectiveV1::RetryAfterTime,
            false,
        ),
        (
            ObjectiveAdmissionError::SourceStale,
            ObjectiveRetryDirectiveV1::RefreshSource,
            false,
        ),
        (
            ObjectiveAdmissionError::LocaleNotAllowed,
            ObjectiveRetryDirectiveV1::CorrectRequest,
            false,
        ),
        (
            ObjectiveAdmissionError::DeadlineMissing,
            ObjectiveRetryDirectiveV1::CorrectRequest,
            false,
        ),
        (
            ObjectiveAdmissionError::DeadlineBeforeObservation,
            ObjectiveRetryDirectiveV1::CorrectRequest,
            false,
        ),
        (
            ObjectiveAdmissionError::DeadlineExpired,
            ObjectiveRetryDirectiveV1::CorrectRequest,
            false,
        ),
    ];

    for (error, expected, blind_retry_safe) in cases {
        assert_eq!(expected, objective_admission_retry_directive_v1(&error));
        assert_eq!(
            blind_retry_safe,
            objective_admission_blind_retry_safe_v1(&error)
        );
    }
}

#[test]
fn non_availability_rejections_never_default_to_same_input_retry() {
    let errors = [
        ObjectiveAdmissionError::ProfileDigestMismatch,
        ObjectiveAdmissionError::InputSchemaMismatch,
        ObjectiveAdmissionError::PrincipalScopeMismatch,
        ObjectiveAdmissionError::UnsupportedComparator,
    ];

    for error in errors {
        assert_eq!(
            ObjectiveRetryDirectiveV1::DoNotRetrySameInput,
            objective_admission_retry_directive_v1(&error)
        );
        assert!(!objective_admission_blind_retry_safe_v1(&error));
    }
}
