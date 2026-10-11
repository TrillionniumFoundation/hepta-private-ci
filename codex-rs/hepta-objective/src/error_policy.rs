use crate::ObjectiveAdmissionError;
use crate::ObjectiveError;

impl ObjectiveError {
    /// Whether replaying the same semantic input may succeed after a transient
    /// runtime condition changes. Stable error-code families are not blanket
    /// retry instructions.
    #[must_use]
    pub const fn retryable(&self) -> bool {
        matches!(self, Self::FeasibilityBudgetExhausted)
    }
}

impl ObjectiveAdmissionError {
    /// Variant-specific retry policy for admission failures.
    ///
    /// `SourceFromFuture` may become admissible as trusted time advances.
    /// Stale input, locale rejection and invalid/missing/expired deadlines need
    /// new input or configuration rather than blind replay of the same request.
    #[must_use]
    pub const fn retryable(&self) -> bool {
        match self {
            Self::SourceFromFuture => true,
            Self::Compiler(error) => error.retryable(),
            _ => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retry_policy_is_variant_specific() {
        assert!(ObjectiveError::FeasibilityBudgetExhausted.retryable());
        assert!(ObjectiveAdmissionError::SourceFromFuture.retryable());
        assert!(!ObjectiveAdmissionError::LocaleNotAllowed.retryable());
        assert!(!ObjectiveAdmissionError::SourceStale.retryable());
        assert!(!ObjectiveAdmissionError::DeadlineMissing.retryable());
        assert!(!ObjectiveAdmissionError::DeadlineBeforeObservation.retryable());
        assert!(!ObjectiveAdmissionError::DeadlineExpired.retryable());
    }
}
