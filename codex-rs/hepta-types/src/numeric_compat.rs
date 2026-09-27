use crate::ContractRegistryV1;
use crate::NumericConversionError;
use crate::NumericConversionReceiptV1;
use crate::NumericSignalSchemaV1;
use crate::NumericSignalV1;

/// Backward-compatible registry validation entrypoint.
///
/// The V1 public signature remains the original pure arithmetic receipt. New
/// consumers that require an explicit registry-admission receipt must opt into
/// `rescale_signal_registered_receipt_v1` or the generation-bound V2 API.
pub fn rescale_signal_registered(
    source: &NumericSignalV1,
    target: &NumericSignalSchemaV1,
    registry: &ContractRegistryV1,
) -> Result<(NumericSignalV1, NumericConversionReceiptV1), NumericConversionError> {
    let (output, registered) =
        crate::numeric_conversion::rescale_signal_registered(source, target, registry)?;
    Ok((output, registered.conversion))
}
