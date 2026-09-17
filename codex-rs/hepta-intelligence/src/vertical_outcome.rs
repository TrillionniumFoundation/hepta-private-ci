use crate::vertical::ReadOnlyVerticalError;
use crate::vertical::ReadOnlyVerticalReceipt;
use crate::vertical::ReadOnlyVerticalRequest;
use crate::vertical::run_read_only_vertical;

/// Non-error control outcome for the read-only vertical facade.
///
/// The legacy `run_read_only_vertical` entry point is retained for compatibility
/// and historically represents objective abstention with
/// `ReadOnlyVerticalError::ObjectiveExplicitAbstain`. New callers should use this
/// wrapper so metrics/retry/telemetry can distinguish a successful safety
/// abstention from a system failure without changing the legacy function's ABI.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReadOnlyVerticalOutcomeV1 {
    Completed(ReadOnlyVerticalReceipt),
    ExplicitAbstain,
}

pub fn run_read_only_vertical_outcome_v1(
    request: ReadOnlyVerticalRequest,
) -> Result<ReadOnlyVerticalOutcomeV1, ReadOnlyVerticalError> {
    normalize_vertical_result(run_read_only_vertical(request))
}

fn normalize_vertical_result(
    result: Result<ReadOnlyVerticalReceipt, ReadOnlyVerticalError>,
) -> Result<ReadOnlyVerticalOutcomeV1, ReadOnlyVerticalError> {
    match result {
        Ok(receipt) => Ok(ReadOnlyVerticalOutcomeV1::Completed(receipt)),
        Err(ReadOnlyVerticalError::ObjectiveExplicitAbstain) => {
            Ok(ReadOnlyVerticalOutcomeV1::ExplicitAbstain)
        }
        Err(error) => Err(error),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn explicit_abstain_is_a_successful_control_outcome() {
        assert!(matches!(
            normalize_vertical_result(Err(ReadOnlyVerticalError::ObjectiveExplicitAbstain)),
            Ok(ReadOnlyVerticalOutcomeV1::ExplicitAbstain)
        ));
    }

    #[test]
    fn unrelated_vertical_failures_remain_errors() {
        assert!(matches!(
            normalize_vertical_result(Err(ReadOnlyVerticalError::DigestMismatch("fixture"))),
            Err(ReadOnlyVerticalError::DigestMismatch("fixture"))
        ));
    }
}
