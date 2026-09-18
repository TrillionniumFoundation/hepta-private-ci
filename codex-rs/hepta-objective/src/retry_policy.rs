use crate::ObjectiveAdmissionError;
use crate::ObjectiveError;

/// Caller guidance for a rejected/unavailable objective admission.
///
/// Error codes remain stable for compatibility. This directive prevents the
/// broad `OBJ-E007` bucket from being interpreted as permission to blindly
/// replay an unchanged request.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectiveRetryDirectiveV1 {
    /// A transient bounded-capacity failure may be retried with the same input.
    RetrySameInput,
    /// The same authenticated source may become admissible after clock time
    /// advances into the configured future-skew window.
    RetryAfterTime,
    /// Obtain a fresh observation/source digest before trying again.
    RefreshSource,
    /// Construct a new/corrected request (deadline, locale, or other contract
    /// input) rather than replaying the rejected bytes.
    CorrectRequest,
    /// Replaying the same input is not expected to change the outcome.
    DoNotRetrySameInput,
}

#[must_use]
pub const fn objective_admission_retry_directive_v1(
    error: &ObjectiveAdmissionError,
) -> ObjectiveRetryDirectiveV1 {
    match error {
        ObjectiveAdmissionError::Compiler(ObjectiveError::FeasibilityBudgetExhausted) => {
            ObjectiveRetryDirectiveV1::RetrySameInput
        }
        ObjectiveAdmissionError::SourceFromFuture => ObjectiveRetryDirectiveV1::RetryAfterTime,
        ObjectiveAdmissionError::SourceStale => ObjectiveRetryDirectiveV1::RefreshSource,
        ObjectiveAdmissionError::LocaleNotAllowed
        | ObjectiveAdmissionError::DeadlineMissing
        | ObjectiveAdmissionError::DeadlineBeforeObservation
        | ObjectiveAdmissionError::DeadlineExpired => ObjectiveRetryDirectiveV1::CorrectRequest,
        _ => ObjectiveRetryDirectiveV1::DoNotRetrySameInput,
    }
}

#[must_use]
pub const fn objective_admission_blind_retry_safe_v1(error: &ObjectiveAdmissionError) -> bool {
    matches!(
        objective_admission_retry_directive_v1(error),
        ObjectiveRetryDirectiveV1::RetrySameInput
    )
}
