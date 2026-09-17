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
    match run_read_only_vertical(request) {
        Ok(receipt) => Ok(ReadOnlyVerticalOutcomeV1::Completed(receipt)),
        Err(ReadOnlyVerticalError::ObjectiveExplicitAbstain) => {
            Ok(ReadOnlyVerticalOutcomeV1::ExplicitAbstain)
        }
        Err(error) => Err(error),
    }
}
